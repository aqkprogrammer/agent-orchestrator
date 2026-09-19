"""Public API request/response models."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from orchestrator.db.models import (
    ApprovalRecord,
    AuditRecord,
    MemoryRecord,
    RunRecord,
    ThreadRecord,
)
from orchestrator.db.repository import iso

UserId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w.@-]+$")]


class RunCreate(BaseModel):
    task: str = Field(min_length=1, max_length=4000, description="What the agents should do.")
    user_id: UserId = "demo-user"
    thread_id: str | None = Field(
        default=None, description="Continue an existing thread (short-term memory)."
    )


class RunOut(BaseModel):
    id: str
    thread_id: str
    user_id: str
    task: str
    status: str
    final_answer: str | None
    confidence: float | None
    error: str | None
    llm_provider: str
    model: str
    input_tokens: int
    output_tokens: int
    llm_calls: int
    tool_calls: int
    latency_ms: float
    created_at: str | None
    updated_at: str | None
    completed_at: str | None

    @classmethod
    def of(cls, r: RunRecord) -> RunOut:
        return cls(
            id=r.id,
            thread_id=r.thread_id,
            user_id=r.user_id,
            task=r.task,
            status=r.status,
            final_answer=r.final_answer,
            confidence=r.confidence,
            error=r.error,
            llm_provider=r.llm_provider,
            model=r.model,
            input_tokens=r.input_tokens or 0,
            output_tokens=r.output_tokens or 0,
            llm_calls=r.llm_calls or 0,
            tool_calls=r.tool_calls or 0,
            latency_ms=round(r.latency_ms or 0.0, 2),
            created_at=iso(r.created_at),
            updated_at=iso(r.updated_at),
            completed_at=iso(r.completed_at),
        )


class RunEventOut(BaseModel):
    id: int
    run_id: str
    type: str
    agent: str | None
    data: dict[str, Any]
    created_at: str | None


class ThreadOut(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str | None
    updated_at: str | None

    @classmethod
    def of(cls, t: ThreadRecord) -> ThreadOut:
        return cls(
            id=t.id,
            user_id=t.user_id,
            title=t.title,
            created_at=iso(t.created_at),
            updated_at=iso(t.updated_at),
        )


class ThreadDetail(BaseModel):
    thread: ThreadOut
    runs: list[RunOut]
    conversation: list[dict[str, Any]]
    checkpoint_id: str | None


class ApprovalOut(BaseModel):
    id: str
    run_id: str
    thread_id: str
    user_id: str
    kind: str
    agent: str | None
    tool_name: str | None
    args: dict[str, Any]
    reason: str
    risk_level: str
    payload: dict[str, Any]
    status: str
    decision: dict[str, Any] | None
    reviewer: str | None
    created_at: str | None
    decided_at: str | None

    @classmethod
    def of(cls, a: ApprovalRecord) -> ApprovalOut:
        return cls(
            id=a.id,
            run_id=a.run_id,
            thread_id=a.thread_id,
            user_id=a.user_id,
            kind=a.kind,
            agent=a.agent,
            tool_name=a.tool_name,
            args=a.args or {},
            reason=a.reason,
            risk_level=a.risk_level,
            payload=a.payload or {},
            status=a.status,
            decision=a.decision,
            reviewer=a.reviewer,
            created_at=iso(a.created_at),
            decided_at=iso(a.decided_at),
        )


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    args: dict[str, Any] | None = Field(
        default=None, description="Replacement tool arguments (decision=edit, tool approvals)."
    )
    response: str | None = Field(
        default=None,
        max_length=8000,
        description="Reply to an escalation, or the edited final answer (final_review).",
    )
    comment: str | None = Field(default=None, max_length=2000)
    reviewer: str = Field(default="reviewer", min_length=1, max_length=128)


class MemoryOut(BaseModel):
    id: str
    user_id: str
    content: str
    kind: str
    source_run_id: str | None
    created_at: str | None
    score: float | None = None

    @classmethod
    def of(cls, m: MemoryRecord, score: float | None = None) -> MemoryOut:
        return cls(
            id=m.id,
            user_id=m.user_id,
            content=m.content,
            kind=m.kind,
            source_run_id=m.source_run_id,
            created_at=iso(m.created_at),
            score=score,
        )


class MemoryCreate(BaseModel):
    user_id: UserId = "demo-user"
    content: str = Field(min_length=3, max_length=500)
    kind: Literal["profile", "preference", "fact"] = "fact"


class AuditOut(BaseModel):
    id: int
    run_id: str | None
    user_id: str
    agent: str | None
    action: str
    args: dict[str, Any]
    result: dict[str, Any] | None
    status: str
    latency_ms: float
    created_at: str | None

    @classmethod
    def of(cls, a: AuditRecord) -> AuditOut:
        return cls(
            id=a.id,
            run_id=a.run_id,
            user_id=a.user_id,
            agent=a.agent,
            action=a.action,
            args=a.args or {},
            result=a.result,
            status=a.status,
            latency_ms=a.latency_ms or 0.0,
            created_at=iso(a.created_at),
        )
