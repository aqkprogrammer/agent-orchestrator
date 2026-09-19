"""Runs: create, list, inspect, trace and stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from orchestrator.api.deps import ContainerDep
from orchestrator.api.schemas import (
    ApprovalOut,
    AuditOut,
    RunCreate,
    RunEventOut,
    RunOut,
)
from orchestrator.runtime.events import TERMINAL_EVENTS, RunEmitter, event_to_dict

router = APIRouter(prefix="/api/runs", tags=["runs"])

HEARTBEAT_SECONDS = 15.0


class RunDetail(RunOut):
    pending_approval: ApprovalOut | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunOut)
def create_run(body: RunCreate, c: ContainerDep) -> RunOut:
    task = body.task.strip()
    if not task:
        raise HTTPException(422, "Task must not be blank")
    if len(task) > c.settings.max_task_chars:
        raise HTTPException(422, f"Task exceeds {c.settings.max_task_chars} characters")

    if body.thread_id:
        thread = c.repo.get_thread(body.thread_id)
        if thread is None or thread.user_id != body.user_id:
            raise HTTPException(404, "Thread not found")
        active = c.repo.active_run_for_thread(thread.id)
        if active is not None:
            raise HTTPException(
                409, f"Thread already has an active run ({active.id}, {active.status})"
            )
    else:
        thread = c.repo.create_thread(body.user_id, task[:80])

    run = c.repo.create_run(
        thread_id=thread.id,
        user_id=body.user_id,
        task=task,
        llm_provider=c.llm.name,
        model=c.llm.model,
    )
    RunEmitter(c.repo, c.bus, run.id).emit("run_queued", None, task=task, thread_id=thread.id)
    c.repo.touch_thread(thread.id)
    c.dispatcher.submit(run.id)
    refreshed = c.repo.get_run(run.id)
    return RunOut.of(refreshed or run)


@router.get("", response_model=list[RunOut])
def list_runs(
    c: ContainerDep,
    user_id: str | None = None,
    thread_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RunOut]:
    runs = c.repo.list_runs(
        user_id=user_id, thread_id=thread_id, status=status_, limit=limit, offset=offset
    )
    return [RunOut.of(r) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, c: ContainerDep) -> RunDetail:
    run = c.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    pending = c.repo.pending_approval_for_run(run_id)
    return RunDetail(
        **RunOut.of(run).model_dump(),
        pending_approval=ApprovalOut.of(pending) if pending else None,
    )


@router.get("/{run_id}/events", response_model=list[RunEventOut])
def list_run_events(
    run_id: str, c: ContainerDep, after: int = Query(default=0, ge=0)
) -> list[dict[str, Any]]:
    if c.repo.get_run(run_id) is None:
        raise HTTPException(404, "Run not found")
    return [event_to_dict(e) for e in c.repo.list_events(run_id, after)]


@router.get("/{run_id}/audit", response_model=list[AuditOut])
def list_run_audit(run_id: str, c: ContainerDep) -> list[AuditOut]:
    if c.repo.get_run(run_id) is None:
        raise HTTPException(404, "Run not found")
    return [AuditOut.of(a) for a in reversed(c.repo.list_audit(run_id=run_id))]


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\nevent: run_event\ndata: {json.dumps(event, default=str)}\n\n"


@router.get(
    "/{run_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_run(
    run_id: str,
    request: Request,
    c: ContainerDep,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """Server-Sent Events: replays stored events, then streams live ones until the run ends."""
    if await run_in_threadpool(c.repo.get_run, run_id) is None:
        raise HTTPException(404, "Run not found")
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))

    async def generate() -> AsyncIterator[str]:
        nonlocal cursor
        # Subscribe *before* replaying so nothing published in between is lost.
        sub = await c.bus.subscribe(run_id)
        try:
            yield "retry: 3000\n\n"
            for record in await run_in_threadpool(c.repo.list_events, run_id, cursor):
                event = event_to_dict(record)
                cursor = event["id"]
                yield _sse(event)
                if event["type"] in TERMINAL_EVENTS:
                    return
            while not await request.is_disconnected():
                live = await sub.get(timeout=HEARTBEAT_SECONDS)
                if live is None:
                    yield ": keep-alive\n\n"
                    continue
                if live["id"] <= cursor:
                    continue
                cursor = live["id"]
                yield _sse(live)
                if live["type"] in TERMINAL_EVENTS:
                    return
        finally:
            await sub.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
