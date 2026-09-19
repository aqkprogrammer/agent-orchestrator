"""Conversation threads (short-term memory lives in the LangGraph checkpoint)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from orchestrator.api.deps import ContainerDep
from orchestrator.api.schemas import RunOut, ThreadDetail, ThreadOut

router = APIRouter(prefix="/api/threads", tags=["threads"])


@router.get("", response_model=list[ThreadOut])
def list_threads(
    c: ContainerDep, user_id: str = "demo-user", limit: int = Query(default=50, ge=1, le=200)
) -> list[ThreadOut]:
    return [ThreadOut.of(t) for t in c.repo.list_threads(user_id, limit)]


@router.get("/{thread_id}", response_model=ThreadDetail)
def get_thread(thread_id: str, c: ContainerDep) -> ThreadDetail:
    thread = c.repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Thread not found")
    runs = c.repo.list_runs(thread_id=thread_id, limit=200, oldest_first=True)
    state = c.runner.thread_state(thread_id)
    return ThreadDetail(
        thread=ThreadOut.of(thread),
        runs=[RunOut.of(r) for r in runs],
        conversation=state["conversation"],
        checkpoint_id=state["checkpoint_id"],
    )
