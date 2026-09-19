"""Human-in-the-loop approvals inbox."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from orchestrator.api.deps import ContainerDep
from orchestrator.api.schemas import ApprovalOut, DecisionIn
from orchestrator.runtime.events import RunEmitter
from orchestrator.tools.base import format_validation_error

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    c: ContainerDep,
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected|edited)$"),
    user_id: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ApprovalOut]:
    records = c.repo.list_approvals(status=status, user_id=user_id, run_id=run_id, limit=limit)
    return [ApprovalOut.of(a) for a in records]


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, c: ContainerDep) -> ApprovalOut:
    approval = c.repo.get_approval(approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    return ApprovalOut.of(approval)


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
def decide(approval_id: str, body: DecisionIn, c: ContainerDep) -> ApprovalOut:
    """Approve, reject or edit a paused action. The run resumes from its checkpoint."""
    approval = c.repo.get_approval(approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    if approval.status != "pending":
        raise HTTPException(409, f"Approval already {approval.status}")

    decision = body.model_dump()
    if body.decision == "edit":
        if approval.kind == "tool":
            tool = c.registry.get(approval.tool_name or "")
            if tool is None or not body.args:
                raise HTTPException(422, "Editing a tool approval requires 'args'")
            try:
                decision["args"] = tool.validate(body.args).model_dump(mode="json")
            except ValidationError as exc:
                raise HTTPException(422, format_validation_error(exc)) from exc
        elif not (body.response and body.response.strip()):
            raise HTTPException(422, "Editing this approval requires 'response'")

    new_status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[body.decision]
    if not c.repo.decide_approval(
        approval_id, status=new_status, decision=decision, reviewer=body.reviewer
    ):
        raise HTTPException(409, "Approval was decided concurrently")
    if not c.repo.transition_run(approval.run_id, ("awaiting_approval",), "queued"):
        raise HTTPException(409, "Run is not awaiting approval")

    RunEmitter(c.repo, c.bus, approval.run_id).emit(
        "approval_resolved",
        approval.agent,
        approval_id=approval_id,
        decision=body.decision,
        reviewer=body.reviewer,
        comment=body.comment,
    )
    c.dispatcher.submit(approval.run_id, approval_id)
    updated = c.repo.get_approval(approval_id)
    return ApprovalOut.of(updated or approval)
