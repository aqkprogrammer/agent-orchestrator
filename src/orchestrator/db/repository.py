"""Data-access layer. Each method runs in its own short transaction."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from orchestrator.db.models import (
    ApprovalRecord,
    AuditRecord,
    MemoryRecord,
    RunEventRecord,
    RunRecord,
    ThreadRecord,
    utcnow,
)

ACTIVE_RUN_STATUSES = ("queued", "running", "awaiting_approval")
TERMINAL_RUN_STATUSES = ("completed", "failed")


class Repository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------ health
    def ping(self) -> None:
        with self._sf() as s:
            s.execute(select(1))

    # ------------------------------------------------------------------ threads
    def create_thread(self, user_id: str, title: str) -> ThreadRecord:
        with self._sf.begin() as s:
            thread = ThreadRecord(user_id=user_id, title=title[:200])
            s.add(thread)
        return thread

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        with self._sf() as s:
            return s.get(ThreadRecord, thread_id)

    def list_threads(self, user_id: str, limit: int = 50) -> Sequence[ThreadRecord]:
        with self._sf() as s:
            stmt = (
                select(ThreadRecord)
                .where(ThreadRecord.user_id == user_id)
                .order_by(ThreadRecord.updated_at.desc())
                .limit(limit)
            )
            return s.scalars(stmt).all()

    def touch_thread(self, thread_id: str) -> None:
        with self._sf.begin() as s:
            s.execute(
                update(ThreadRecord).where(ThreadRecord.id == thread_id).values(updated_at=utcnow())
            )

    # ------------------------------------------------------------------ runs
    def create_run(
        self, *, thread_id: str, user_id: str, task: str, llm_provider: str, model: str
    ) -> RunRecord:
        with self._sf.begin() as s:
            run = RunRecord(
                thread_id=thread_id,
                user_id=user_id,
                task=task,
                status="queued",
                llm_provider=llm_provider,
                model=model,
            )
            s.add(run)
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._sf() as s:
            return s.get(RunRecord, run_id)

    def list_runs(
        self,
        *,
        user_id: str | None = None,
        thread_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        oldest_first: bool = False,
    ) -> Sequence[RunRecord]:
        with self._sf() as s:
            stmt = select(RunRecord)
            if user_id:
                stmt = stmt.where(RunRecord.user_id == user_id)
            if thread_id:
                stmt = stmt.where(RunRecord.thread_id == thread_id)
            if status:
                stmt = stmt.where(RunRecord.status == status)
            order = RunRecord.created_at.asc() if oldest_first else RunRecord.created_at.desc()
            return s.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()

    def active_run_for_thread(self, thread_id: str) -> RunRecord | None:
        with self._sf() as s:
            stmt = select(RunRecord).where(
                RunRecord.thread_id == thread_id, RunRecord.status.in_(ACTIVE_RUN_STATUSES)
            )
            return s.scalars(stmt.limit(1)).first()

    def transition_run(self, run_id: str, from_statuses: Iterable[str], to_status: str) -> bool:
        """Atomically move a run between states. Returns False if the guard did not match."""
        with self._sf.begin() as s:
            result = s.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id, RunRecord.status.in_(tuple(from_statuses)))
                .values(status=to_status, updated_at=utcnow())
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    def update_run(self, run_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        with self._sf.begin() as s:
            s.execute(update(RunRecord).where(RunRecord.id == run_id).values(**fields))

    def add_run_usage(
        self,
        run_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        llm_calls: int,
        tool_calls: int,
        latency_ms: float,
    ) -> None:
        with self._sf.begin() as s:
            s.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id)
                .values(
                    input_tokens=RunRecord.input_tokens + input_tokens,
                    output_tokens=RunRecord.output_tokens + output_tokens,
                    llm_calls=RunRecord.llm_calls + llm_calls,
                    tool_calls=RunRecord.tool_calls + tool_calls,
                    latency_ms=RunRecord.latency_ms + latency_ms,
                    updated_at=utcnow(),
                )
            )

    def run_counts(self, user_id: str | None = None) -> dict[str, int]:
        with self._sf() as s:
            stmt = select(RunRecord.status, func.count()).group_by(RunRecord.status)
            if user_id:
                stmt = stmt.where(RunRecord.user_id == user_id)
            return {str(row[0]): int(row[1]) for row in s.execute(stmt).all()}

    # ------------------------------------------------------------------ events
    def add_event(
        self, run_id: str, type_: str, agent: str | None, data: dict[str, Any]
    ) -> RunEventRecord:
        with self._sf.begin() as s:
            record = RunEventRecord(run_id=run_id, type=type_, agent=agent, data=data)
            s.add(record)
            s.flush()
        return record

    def list_events(self, run_id: str, after_id: int = 0) -> Sequence[RunEventRecord]:
        with self._sf() as s:
            stmt = (
                select(RunEventRecord)
                .where(RunEventRecord.run_id == run_id, RunEventRecord.id > after_id)
                .order_by(RunEventRecord.id.asc())
            )
            return s.scalars(stmt).all()

    # ------------------------------------------------------------------ approvals
    def create_approval(self, **fields: Any) -> ApprovalRecord:
        with self._sf.begin() as s:
            record = ApprovalRecord(**fields)
            s.add(record)
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._sf() as s:
            return s.get(ApprovalRecord, approval_id)

    def list_approvals(
        self,
        *,
        status: str | None = None,
        user_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> Sequence[ApprovalRecord]:
        with self._sf() as s:
            stmt = select(ApprovalRecord)
            if run_id:
                stmt = stmt.where(ApprovalRecord.run_id == run_id)
            if status:
                stmt = stmt.where(ApprovalRecord.status == status)
            if user_id:
                stmt = stmt.where(ApprovalRecord.user_id == user_id)
            return s.scalars(stmt.order_by(ApprovalRecord.created_at.desc()).limit(limit)).all()

    def pending_approval_for_run(self, run_id: str) -> ApprovalRecord | None:
        with self._sf() as s:
            stmt = select(ApprovalRecord).where(
                ApprovalRecord.run_id == run_id, ApprovalRecord.status == "pending"
            )
            return s.scalars(stmt.limit(1)).first()

    def decide_approval(
        self, approval_id: str, *, status: str, decision: dict[str, Any], reviewer: str
    ) -> bool:
        with self._sf.begin() as s:
            result = s.execute(
                update(ApprovalRecord)
                .where(ApprovalRecord.id == approval_id, ApprovalRecord.status == "pending")
                .values(status=status, decision=decision, reviewer=reviewer, decided_at=utcnow())
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ memories
    def add_memory(
        self,
        *,
        user_id: str,
        content: str,
        content_hash: str,
        kind: str,
        source_run_id: str | None,
    ) -> MemoryRecord | None:
        """Insert a memory; returns None if an identical memory already exists for the user."""
        try:
            with self._sf.begin() as s:
                record = MemoryRecord(
                    user_id=user_id,
                    content=content,
                    content_hash=content_hash,
                    kind=kind,
                    source_run_id=source_run_id,
                )
                s.add(record)
            return record
        except IntegrityError:
            return None

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        with self._sf() as s:
            return s.get(MemoryRecord, memory_id)

    def get_memories(self, ids: Sequence[str]) -> list[MemoryRecord]:
        if not ids:
            return []
        with self._sf() as s:
            rows = {
                m.id: m for m in s.scalars(select(MemoryRecord).where(MemoryRecord.id.in_(ids)))
            }
        return [rows[i] for i in ids if i in rows]

    def list_memories(
        self,
        user_id: str,
        *,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[MemoryRecord]:
        with self._sf() as s:
            stmt = select(MemoryRecord).where(MemoryRecord.user_id == user_id)
            if kinds:
                stmt = stmt.where(MemoryRecord.kind.in_(tuple(kinds)))
            stmt = stmt.order_by(MemoryRecord.created_at.desc()).limit(limit).offset(offset)
            return s.scalars(stmt).all()

    def delete_memory(self, memory_id: str) -> bool:
        with self._sf.begin() as s:
            result = s.execute(delete(MemoryRecord).where(MemoryRecord.id == memory_id))
            return bool(result.rowcount)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ audit
    def add_audit(
        self,
        *,
        run_id: str | None,
        user_id: str,
        agent: str | None,
        action: str,
        args: dict[str, Any],
        result: dict[str, Any] | None,
        status: str,
        latency_ms: float = 0.0,
    ) -> AuditRecord:
        with self._sf.begin() as s:
            record = AuditRecord(
                run_id=run_id,
                user_id=user_id,
                agent=agent,
                action=action,
                args=args,
                result=result,
                status=status,
                latency_ms=latency_ms,
            )
            s.add(record)
        return record

    def list_audit(
        self, *, run_id: str | None = None, user_id: str | None = None, limit: int = 200
    ) -> Sequence[AuditRecord]:
        with self._sf() as s:
            stmt = select(AuditRecord)
            if run_id:
                stmt = stmt.where(AuditRecord.run_id == run_id)
            if user_id:
                stmt = stmt.where(AuditRecord.user_id == user_id)
            return s.scalars(stmt.order_by(AuditRecord.id.desc()).limit(limit)).all()


def iso(dt: datetime | None) -> str | None:
    """Serialize timestamps as UTC ISO-8601 (SQLite drops tzinfo on the way back)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()
