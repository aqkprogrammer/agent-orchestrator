"""The LangGraph state machine: supervisor delegation, tool loops, HITL review, memory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from orchestrator.agents.contracts import FinalAnswer, MemoryExtraction, RouteDecision
from orchestrator.agents.policy import RiskPolicy
from orchestrator.agents.specs import (
    AGENTS,
    FINALIZER_PROMPT,
    MEMORY_PROMPT,
    SUPERVISOR_PROMPT,
    AgentSpec,
)
from orchestrator.agents.tooling import ToolExecutor
from orchestrator.config import Settings
from orchestrator.db.repository import Repository
from orchestrator.llm.base import LLMError, LLMProvider, Message, PromptContext, ToolCall
from orchestrator.memory.store import MemoryStore
from orchestrator.observability import get_logger
from orchestrator.runtime.events import RunEmitter
from orchestrator.tools.base import ToolContext, ToolRegistry, format_validation_error

log = get_logger(__name__)

FINISH = "FINISH"
MAX_CONVERSATION_TURNS = 20


class AgentState(TypedDict, total=False):
    # inputs (set on every new run of the thread)
    run_id: str
    user_id: str
    thread_id: str
    task: str
    # thread-level short-term memory (persisted by the checkpointer)
    conversation: list[dict[str, Any]]
    # per-run working state
    memories: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    visits: dict[str, int]
    supervisor_steps: int
    active_agent: str | None
    instructions: str
    scratch: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    final_answer: str | None
    confidence: float | None


class Decision(TypedDict, total=False):
    decision: Literal["approve", "reject", "edit"]
    args: dict[str, Any] | None
    response: str | None
    comment: str | None
    reviewer: str


@dataclass
class GraphDeps:
    settings: Settings
    llm: LLMProvider
    registry: ToolRegistry
    policy: RiskPolicy
    memory: MemoryStore
    repo: Repository
    emitter: RunEmitter


# ----------------------------------------------------------------------------- helpers
def _memory_lines(state: AgentState) -> list[str]:
    return [m["content"] for m in state.get("memories", [])]


def render_brief(state: AgentState, *, instructions: str = "", include_steps: bool = True) -> str:
    parts = [f"## Task\n{state['task']}"]
    if instructions:
        parts.append(f"## Instructions from the supervisor\n{instructions}")
    memories = _memory_lines(state)
    if memories:
        parts.append("## What we know about the user\n" + "\n".join(f"- {m}" for m in memories))
    history = list(state.get("conversation", [])[:-1])[-6:]
    if history:
        parts.append(
            "## Earlier in this conversation\n"
            + "\n".join(f"{t['role']}: {t['content'][:500]}" for t in history)
        )
    steps = state.get("steps", [])
    if include_steps and steps:
        parts.append(
            "## Results from specialists so far\n"
            + "\n\n".join(f"### {s['agent']}\n{s['output']}" for s in steps)
        )
    return "\n\n".join(parts)


def _context(state: AgentState, agent: str, scratch: list[Message] | None = None) -> PromptContext:
    return PromptContext(
        task=state["task"],
        agent=agent,
        instructions=state.get("instructions", ""),
        memories=_memory_lines(state),
        steps=list(state.get("steps", [])),
        conversation=list(state.get("conversation", [])),
        scratch=scratch or [],
        agents=list(AGENTS),
        visits=dict(state.get("visits", {})),
    )


def _load_scratch(state: AgentState) -> list[Message]:
    return [Message.model_validate(m) for m in state.get("scratch", [])]


def _dump_scratch(scratch: list[Message]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in scratch]


# ----------------------------------------------------------------------------- builder
def build_graph(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    settings, llm, emitter = deps.settings, deps.llm, deps.emitter
    executor = ToolExecutor(deps.registry, deps.repo, emitter)

    def tool_ctx(state: AgentState, agent: str) -> ToolContext:
        return ToolContext(
            user_id=state["user_id"],
            run_id=state.get("run_id"),
            thread_id=state.get("thread_id"),
            memory=deps.memory,
            settings=settings,
            agent=agent,
        )

    def run_calls(
        state: AgentState, spec: AgentSpec, calls: list[ToolCall], scratch: list[Message]
    ) -> dict[str, Any] | None:
        """Execute calls in order; stop at the first one that needs a human."""
        ctx = tool_ctx(state, spec.name)
        for index, call in enumerate(calls):
            prepared = executor.prepare(ctx, call, spec.tools)
            if isinstance(prepared, Message):
                scratch.append(prepared)
                continue
            tool, args = prepared
            decision = deps.policy.evaluate_tool(tool, args.model_dump())
            if decision.requires_approval:
                return {
                    "kind": decision.kind,
                    "agent": spec.name,
                    "tool": tool.name,
                    "tool_description": tool.description,
                    "call": call.model_dump(),
                    "args": args.model_dump(mode="json"),
                    "reason": decision.reason,
                    "risk_level": decision.risk_level,
                    "remaining": [c.model_dump() for c in calls[index + 1 :]],
                }
            scratch.append(executor.run(ctx, tool, call, args))
        return None

    # ------------------------------------------------------------------ nodes
    def intake(state: AgentState) -> Command[Literal["supervisor"]]:
        recalled = deps.memory.recall(
            state["user_id"],
            state["task"],
            k=settings.memory_recall_k,
            profile_k=settings.memory_profile_k,
            min_score=settings.memory_min_score,
        )
        memories = [
            {
                "id": r.record.id,
                "content": r.record.content,
                "kind": r.record.kind,
                "score": r.score,
                "reason": r.reason,
            }
            for r in recalled
        ]
        emitter.emit("memory_recalled", None, memories=memories)
        turn = {"role": "user", "content": state["task"], "run_id": state.get("run_id")}
        conversation = [*state.get("conversation", []), turn][-MAX_CONVERSATION_TURNS:]
        return Command(
            goto="supervisor",
            update={
                "conversation": conversation,
                "memories": memories,
                "steps": [],
                "visits": {},
                "supervisor_steps": 0,
                "active_agent": None,
                "instructions": "",
                "scratch": [],
                "pending_action": None,
                "final_answer": None,
                "confidence": None,
            },
        )

    def supervisor(state: AgentState) -> Command[Any]:
        steps_taken = state.get("supervisor_steps", 0)
        visits = dict(state.get("visits", {}))
        if steps_taken >= settings.max_supervisor_steps:
            emitter.emit(
                "routing",
                "supervisor",
                next=FINISH,
                reasoning=f"Loop limit of {settings.max_supervisor_steps} delegations reached.",
                forced=True,
            )
            return Command(goto="finalize")

        roster = "\n".join(f"- {a.name}: {a.description}" for a in AGENTS.values())
        system = SUPERVISOR_PROMPT.format(roster=roster, options=", ".join([*AGENTS, FINISH]))
        brief = render_brief(state)
        if visits:
            brief += "\n\n## Delegations so far\n" + ", ".join(
                f"{k} x{v}" for k, v in visits.items()
            )
        decision, meta = llm.structured(
            system=system,
            messages=[Message(role="user", content=brief)],
            schema=RouteDecision,
            context=_context(state, "supervisor"),
        )
        emitter.llm_call("supervisor", meta, "route")

        target = decision.next.strip()
        forced_reason = None
        if target.upper() == FINISH:
            target = FINISH
        elif target.lower() not in AGENTS:
            forced_reason = f"Unknown agent '{target}' requested; finishing instead."
            target = FINISH
        else:
            target = target.lower()
            if visits.get(target, 0) >= settings.max_agent_visits:
                forced_reason = f"'{target}' already ran {visits[target]} times; finishing."
                target = FINISH

        emitter.emit(
            "routing",
            "supervisor",
            next=target,
            instructions=decision.instructions,
            reasoning=forced_reason or decision.reasoning,
            forced=forced_reason is not None,
        )
        if target == FINISH:
            return Command(goto="finalize", update={"supervisor_steps": steps_taken + 1})
        visits[target] = visits.get(target, 0) + 1
        return Command(
            goto=target,
            update={
                "supervisor_steps": steps_taken + 1,
                "visits": visits,
                "active_agent": target,
                "instructions": decision.instructions,
                "scratch": [],
            },
        )

    def make_worker(spec: AgentSpec) -> Callable[[AgentState], Command[Any]]:
        tool_specs = [t.spec() for t in deps.registry.subset(spec.tools)]

        def worker(state: AgentState) -> Command[Any]:
            scratch = _load_scratch(state)
            instructions = state.get("instructions", "")
            if not scratch:
                emitter.emit("agent_started", spec.name, instructions=instructions)
            brief = render_brief(state, instructions=instructions)
            rounds = sum(1 for m in scratch if m.role == "assistant")
            output: str | None = None
            while output is None:
                if rounds >= settings.max_tool_rounds:
                    last = next((m.content for m in reversed(scratch) if m.role == "assistant"), "")
                    output = last or "Stopped after reaching the tool-call limit."
                    emitter.emit("warning", spec.name, message="Tool-round limit reached.")
                    break
                response = llm.chat(
                    system=spec.system_prompt,
                    messages=[Message(role="user", content=brief), *scratch],
                    tools=tool_specs,
                    context=_context(state, spec.name, scratch),
                )
                emitter.llm_call(spec.name, response, "act")
                rounds += 1
                scratch.append(
                    Message(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                        raw=response.raw,
                    )
                )
                if not response.tool_calls:
                    output = response.content or "(no output)"
                    break
                if response.content:
                    emitter.emit("agent_message", spec.name, text=response.content)
                pending = run_calls(state, spec, response.tool_calls, scratch)
                if pending is not None:
                    return Command(
                        goto="human_review",
                        update={"scratch": _dump_scratch(scratch), "pending_action": pending},
                    )

            tool_count = sum(1 for m in scratch if m.role == "tool")
            emitter.emit("agent_completed", spec.name, output=output, tool_calls=tool_count)
            step = {
                "agent": spec.name,
                "instructions": instructions,
                "output": output,
                "tool_calls": tool_count,
            }
            return Command(
                goto="supervisor",
                update={
                    "steps": [*state.get("steps", []), step],
                    "scratch": [],
                    "active_agent": None,
                    "pending_action": None,
                },
            )

        worker.__name__ = f"{spec.name}_worker"
        return worker

    def human_review(state: AgentState) -> Command[Any]:
        pending = state.get("pending_action")
        if not pending:  # defensive: nothing to review
            return Command(goto="finalize")
        request = {k: v for k, v in pending.items() if k not in {"remaining", "call"}}

        # --- the graph pauses here until a human decides (Command(resume=...)) ---
        raw_decision: Decision = interrupt(request)

        choice = raw_decision.get("decision", "reject")
        reviewer = raw_decision.get("reviewer") or "reviewer"
        comment = raw_decision.get("comment") or ""

        if pending["kind"] == "final_review":
            answer = state.get("final_answer") or ""
            if choice == "edit" and raw_decision.get("response"):
                answer = raw_decision["response"] or answer
            elif choice == "reject":
                answer = (
                    "A human reviewer did not approve the drafted answer, so it was withheld."
                    + (f" Reviewer note: {comment}" if comment else "")
                )
            return Command(goto="memorize", update={"final_answer": answer, "pending_action": None})

        agent = pending["agent"]
        spec = AGENTS[agent]
        ctx = tool_ctx(state, agent)
        scratch = _load_scratch(state)
        call = ToolCall.model_validate(pending["call"])

        if pending["kind"] == "escalation":
            answered = choice != "reject"
            payload = {
                "status": "answered" if answered else "declined",
                "human_response": raw_decision.get("response") or comment or None,
                "reviewer": reviewer,
            }
            scratch.append(
                executor.record_human(
                    ctx, call, pending["args"], payload, "approved" if answered else "rejected"
                )
            )
        elif choice in ("approve", "edit"):
            tool = deps.registry.get(pending["tool"])
            args = raw_decision.get("args") if choice == "edit" else None
            if tool is None:  # pragma: no cover - registry is static
                raise RuntimeError(f"Tool {pending['tool']} disappeared from the registry")
            try:
                validated = tool.validate(args or pending["args"])
                scratch.append(executor.run(ctx, tool, call, validated, approved_by=reviewer))
            except ValidationError as exc:
                scratch.append(
                    executor.record_human(
                        ctx,
                        call,
                        args or pending["args"],
                        {"error": f"Edited arguments invalid: {format_validation_error(exc)}"},
                        "error",
                    )
                )
        else:
            payload = {"status": "rejected_by_human", "comment": comment, "reviewer": reviewer}
            scratch.append(executor.record_human(ctx, call, pending["args"], payload, "rejected"))

        remaining = [ToolCall.model_validate(c) for c in pending.get("remaining", [])]
        next_pending = run_calls(state, spec, remaining, scratch)
        if next_pending is not None:
            return Command(
                goto="human_review",
                update={"scratch": _dump_scratch(scratch), "pending_action": next_pending},
            )
        return Command(
            goto=agent, update={"scratch": _dump_scratch(scratch), "pending_action": None}
        )

    def finalize(state: AgentState) -> Command[Any]:
        result, meta = llm.structured(
            system=FINALIZER_PROMPT,
            messages=[Message(role="user", content=render_brief(state))],
            schema=FinalAnswer,
            context=_context(state, "finalizer"),
        )
        emitter.llm_call("finalizer", meta, "finalize")
        emitter.emit(
            "final_answer", "finalizer", answer=result.answer, confidence=result.confidence
        )
        decision = deps.policy.evaluate_answer(result.confidence)
        update: dict[str, Any] = {"final_answer": result.answer, "confidence": result.confidence}
        if decision.requires_approval:
            update["pending_action"] = {
                "kind": "final_review",
                "agent": "finalizer",
                "tool": None,
                "args": {"answer": result.answer, "confidence": result.confidence},
                "reason": decision.reason,
                "risk_level": decision.risk_level,
            }
            return Command(goto="human_review", update=update)
        return Command(goto="memorize", update=update)

    def memorize(state: AgentState) -> dict[str, Any]:
        saved: list[dict[str, Any]] = []
        try:
            extraction, meta = llm.structured(
                system=MEMORY_PROMPT,
                messages=[Message(role="user", content=state["task"])],
                schema=MemoryExtraction,
                context=_context(state, "memory"),
            )
            emitter.llm_call("memory", meta, "extract_memories")
            for item in extraction.memories[:5]:
                record = deps.memory.add(
                    state["user_id"],
                    item.content,
                    kind=item.kind,
                    source_run_id=state.get("run_id"),
                )
                if record is not None:
                    saved.append({"id": record.id, "content": record.content, "kind": record.kind})
        except LLMError as exc:  # memory is best-effort; never fail a finished run over it
            log.warning("memory_extraction_failed", error=str(exc))
        emitter.emit("memory_saved", "memory", memories=saved)
        turn = {
            "role": "assistant",
            "content": state.get("final_answer") or "",
            "run_id": state.get("run_id"),
        }
        return {"conversation": [*state.get("conversation", []), turn][-MAX_CONVERSATION_TURNS:]}

    # ------------------------------------------------------------------ wiring
    graph = StateGraph(AgentState)
    graph.add_node("intake", intake, destinations=("supervisor",))
    graph.add_node("supervisor", supervisor, destinations=(*AGENTS, "finalize"))
    for spec in AGENTS.values():
        graph.add_node(
            spec.name,
            make_worker(spec),  # type: ignore[arg-type]
            destinations=("supervisor", "human_review"),
        )
    graph.add_node(
        "human_review", human_review, destinations=(*AGENTS, "human_review", "memorize", "finalize")
    )
    graph.add_node("finalize", finalize, destinations=("human_review", "memorize"))
    graph.add_node("memorize", memorize)
    graph.add_edge(START, "intake")
    graph.add_edge("memorize", END)
    return graph.compile(checkpointer=checkpointer)
