"""Executes (and resumes) runs against the compiled graph, persisting outcomes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from langgraph.types import Command

from orchestrator.agents.graph import GraphDeps, build_graph
from orchestrator.db.models import utcnow
from orchestrator.observability import get_logger
from orchestrator.runtime.events import RunEmitter

if TYPE_CHECKING:
    from orchestrator.runtime.container import Container

log = get_logger(__name__)


class RunService:
    def __init__(self, container: Container) -> None:
        self.c = container

    def _graph(self, emitter: RunEmitter) -> Any:
        c = self.c
        deps = GraphDeps(
            settings=c.settings,
            llm=c.llm,
            registry=c.registry,
            policy=c.policy,
            memory=c.memory,
            repo=c.repo,
            emitter=emitter,
        )
        return build_graph(deps, c.checkpointer)

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.c.settings.recursion_limit,
        }

    def execute(self, run_id: str, approval_id: str | None = None) -> None:
        """Start a queued run, or resume it with a human decision when `approval_id` is set."""
        repo = self.c.repo
        if not repo.transition_run(run_id, ("queued",), "running"):
            log.warning("run_not_queued_skipping", run_id=run_id)
            return
        run = repo.get_run(run_id)
        if run is None:  # pragma: no cover - transition guarantees existence
            return
        emitter = RunEmitter(repo, self.c.bus, run_id)
        started = time.perf_counter()
        config = self._config(run.thread_id)
        graph = self._graph(emitter)
        log.info("run_executing", run_id=run_id, resume=bool(approval_id))

        try:
            payload: Any
            if approval_id:
                approval = repo.get_approval(approval_id)
                if approval is None or approval.decision is None:
                    raise RuntimeError(f"Approval {approval_id} has no recorded decision")
                decision = dict(approval.decision)
                emitter.emit(
                    "run_resumed", approval.agent, approval_id=approval_id, decision=decision
                )
                payload = Command(resume=decision)
            else:
                emitter.emit(
                    "run_started",
                    None,
                    task=run.task,
                    provider=run.llm_provider,
                    model=run.model,
                    thread_id=run.thread_id,
                )
                payload = {
                    "task": run.task,
                    "user_id": run.user_id,
                    "run_id": run.id,
                    "thread_id": run.thread_id,
                }

            for _ in graph.stream(payload, config, stream_mode="updates"):
                pass
            snapshot = graph.get_state(config)
            emitter.flush_usage((time.perf_counter() - started) * 1000)

            if snapshot.interrupts:
                interrupt = snapshot.interrupts[0]
                value: dict[str, Any] = dict(interrupt.value)
                approval = repo.create_approval(
                    run_id=run.id,
                    thread_id=run.thread_id,
                    user_id=run.user_id,
                    interrupt_id=interrupt.id,
                    kind=value.get("kind", "tool"),
                    agent=value.get("agent"),
                    tool_name=value.get("tool"),
                    args=value.get("args") or {},
                    reason=value.get("reason", ""),
                    risk_level=value.get("risk_level", "medium"),
                    payload=value,
                )
                repo.update_run(run_id, status="awaiting_approval")
                emitter.emit(
                    "approval_requested",
                    value.get("agent"),
                    approval_id=approval.id,
                    kind=approval.kind,
                    tool=approval.tool_name,
                    args=approval.args,
                    reason=approval.reason,
                    risk_level=approval.risk_level,
                )
                log.info("run_awaiting_approval", run_id=run_id, approval_id=approval.id)
            else:
                values = snapshot.values
                repo.update_run(
                    run_id,
                    status="completed",
                    final_answer=values.get("final_answer"),
                    confidence=values.get("confidence"),
                    completed_at=utcnow(),
                )
                emitter.emit(
                    "run_completed",
                    None,
                    final_answer=values.get("final_answer"),
                    confidence=values.get("confidence"),
                )
                log.info("run_completed", run_id=run_id)
        except Exception as exc:
            log.exception("run_failed", run_id=run_id)
            emitter.flush_usage((time.perf_counter() - started) * 1000)
            message = f"{type(exc).__name__}: {exc}"[:2000]
            repo.update_run(run_id, status="failed", error=message, completed_at=utcnow())
            emitter.emit("run_failed", None, error=message)
        finally:
            repo.touch_thread(run.thread_id)

    def thread_state(self, thread_id: str) -> dict[str, Any]:
        """Read the checkpointed short-term state of a thread."""
        graph = self._graph(RunEmitter(self.c.repo, self.c.bus, "-"))
        snapshot = graph.get_state(self._config(thread_id))
        values = snapshot.values or {}
        return {
            "conversation": values.get("conversation", []),
            "next": list(snapshot.next),
            "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
        }

    def mermaid(self) -> str:
        graph = self._graph(RunEmitter(self.c.repo, self.c.bus, "-"))
        return str(graph.get_graph().draw_mermaid())
