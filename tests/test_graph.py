"""Graph-level tests driving the RunService directly (no HTTP)."""

from __future__ import annotations

from typing import Any

from orchestrator.config import Settings
from orchestrator.db.models import RunRecord
from orchestrator.runtime.container import Container


def start(container: Container, task: str, user: str = "u1", thread_id: str | None = None) -> str:
    repo = container.repo
    tid = thread_id or repo.create_thread(user, task[:40]).id
    run = repo.create_run(thread_id=tid, user_id=user, task=task, llm_provider="mock", model="m")
    container.runner.execute(run.id)
    return run.id


def decide(container: Container, run_id: str, decision: dict[str, Any]) -> None:
    repo = container.repo
    approval = repo.pending_approval_for_run(run_id)
    assert approval is not None
    status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[decision["decision"]]
    assert repo.decide_approval(approval.id, status=status, decision=decision, reviewer="t")
    assert repo.transition_run(run_id, ("awaiting_approval",), "queued")
    container.runner.execute(run_id, approval.id)


def get(container: Container, run_id: str) -> RunRecord:
    run = container.repo.get_run(run_id)
    assert run is not None
    return run


def event_types(container: Container, run_id: str) -> list[str]:
    return [e.type for e in container.repo.list_events(run_id)]


def test_simple_run_delegates_and_completes(container: Container) -> None:
    run_id = start(container, "Calculate 15% of 2,340 and add 12 * 49")
    run = get(container, run_id)
    assert run.status == "completed"
    assert "(15/100)*2340 = 351" in (run.final_answer or "")
    assert "12 * 49 = 588" in (run.final_answer or "")
    types = event_types(container, run_id)
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "routing" in types and "tool_result" in types
    audit = container.repo.list_audit(run_id=run_id)
    assert {a.action for a in audit} == {"calculator"}
    assert run.llm_calls >= 4 and run.input_tokens > 0


def test_refund_hitl_interrupt_approve_resume(container: Container) -> None:
    run_id = start(container, "Order ORD-1042 arrived damaged. Please refund $250.")
    assert get(container, run_id).status == "awaiting_approval"
    approval = container.repo.pending_approval_for_run(run_id)
    assert approval and approval.tool_name == "issue_refund" and approval.risk_level == "high"
    # nothing executed yet
    assert not [a for a in container.repo.list_audit(run_id=run_id) if a.action == "issue_refund"]

    decide(container, run_id, {"decision": "approve", "reviewer": "lead"})
    run = get(container, run_id)
    assert run.status == "completed"
    assert "Refund rf_" in (run.final_answer or "")
    refunds = [a for a in container.repo.list_audit(run_id=run_id) if a.action == "issue_refund"]
    assert len(refunds) == 1 and refunds[0].status == "approved"
    types = event_types(container, run_id)
    assert types.count("approval_requested") == 1
    assert "run_resumed" in types


def test_edit_changes_tool_arguments(container: Container) -> None:
    run_id = start(container, "Please refund $250 for ORD-1042")
    decide(
        container,
        run_id,
        {
            "decision": "edit",
            "args": {"order_id": "ORD-1042", "amount": 120.0, "reason": "partial"},
        },
    )
    refund = next(a for a in container.repo.list_audit(run_id=run_id) if a.action == "issue_refund")
    assert refund.args["amount"] == 120.0
    assert "$120.00" in (get(container, run_id).final_answer or "")


def test_chained_approvals_with_rejection(container: Container) -> None:
    run_id = start(container, "Refund $300 on ORD-1001 and email me at pat@example.com to confirm")
    decide(container, run_id, {"decision": "approve"})
    assert get(container, run_id).status == "awaiting_approval"
    email = container.repo.pending_approval_for_run(run_id)
    assert email and email.tool_name == "send_email"
    decide(container, run_id, {"decision": "reject", "comment": "Wrong address"})
    run = get(container, run_id)
    assert run.status == "completed"
    assert "Email was NOT sent" in (run.final_answer or "")
    statuses = {a.action: a.status for a in container.repo.list_audit(run_id=run_id)}
    assert statuses["send_email"] == "rejected"
    assert statuses["issue_refund"] == "approved"


def test_small_refund_is_auto_approved(container: Container) -> None:
    run_id = start(container, "Refund $40 on ORD-1002 please")
    run = get(container, run_id)
    assert run.status == "completed"
    assert container.repo.list_approvals(run_id=run_id) == []


def test_escalation_passes_human_response_to_agent(container: Container) -> None:
    run_id = start(container, "I want to speak to a manager about ORD-1003")
    approval = container.repo.pending_approval_for_run(run_id)
    assert approval and approval.kind == "escalation"
    decide(container, run_id, {"decision": "approve", "response": "Offer a 20% voucher."})
    assert "Offer a 20% voucher." in (get(container, run_id).final_answer or "")


def test_low_confidence_answer_goes_to_review(container: Container) -> None:
    run_id = start(container, "Forecast next quarter's churn for the Pro plan")
    approval = container.repo.pending_approval_for_run(run_id)
    assert approval and approval.kind == "final_review"
    decide(container, run_id, {"decision": "edit", "response": "We cannot forecast churn yet."})
    run = get(container, run_id)
    assert run.status == "completed"
    assert run.final_answer == "We cannot forecast churn yet."


def test_memory_persists_across_threads(container: Container) -> None:
    start(container, "My name is Dana and I prefer concise answers. What is the Pro plan price?")
    memories = {m.content for m in container.memory.list_for_user("u1")}
    assert {"User's name is Dana", "User prefers concise answers"} <= memories

    run_id = start(container, "Draft a short welcome note for me")  # new thread
    recalled = next(
        e for e in container.repo.list_events(run_id) if e.type == "memory_recalled"
    ).data["memories"]
    assert any(m["content"] == "User's name is Dana" for m in recalled)
    assert (get(container, run_id).final_answer or "").startswith("Hi Dana,")


def test_thread_short_term_memory(container: Container) -> None:
    first = start(container, "What does the Pro plan include?")
    tid = get(container, first).thread_id
    start(container, "And how much is Starter?", thread_id=tid)
    state = container.runner.thread_state(tid)
    roles = [t["role"] for t in state["conversation"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_supervisor_loop_limit(settings: Settings) -> None:
    limited = settings.model_copy(update={"max_supervisor_steps": 1})
    c = Container(limited, synchronous_runs=True)
    try:
        run_id = start(c, "Research the refund policy, calculate 2+2 and write a summary")
        assert get(c, run_id).status == "completed"
        routing = [e.data for e in c.repo.list_events(run_id) if e.type == "routing"]
        assert routing[-1]["forced"] is True
        assert len([e for e in c.repo.list_events(run_id) if e.type == "agent_started"]) == 1
    finally:
        c.close()


def test_llm_failure_marks_run_failed(container: Container) -> None:
    from orchestrator.llm.base import LLMError

    def boom(**_: Any) -> Any:
        raise LLMError("provider down")

    container.llm.structured = boom  # type: ignore[method-assign]
    run_id = start(container, "What is the refund policy?")
    run = get(container, run_id)
    assert run.status == "failed"
    assert "provider down" in (run.error or "")
    assert event_types(container, run_id)[-1] == "run_failed"


def test_graph_mermaid(container: Container) -> None:
    mermaid = container.runner.mermaid()
    for node in ("supervisor", "researcher", "human_review", "finalize", "memorize"):
        assert node in mermaid
