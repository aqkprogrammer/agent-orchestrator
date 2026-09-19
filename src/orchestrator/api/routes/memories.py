"""Long-term memory browser."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from orchestrator.api.deps import ContainerDep
from orchestrator.api.schemas import MemoryCreate, MemoryOut

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
def list_memories(
    c: ContainerDep,
    user_id: str = "demo-user",
    q: str | None = Query(default=None, max_length=500, description="Semantic search query."),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MemoryOut]:
    if q and q.strip():
        hits = c.memory.search(user_id, q, k=min(limit, 50), min_score=0.0)
        return [MemoryOut.of(record, score) for record, score in hits]
    return [MemoryOut.of(m) for m in c.memory.list_for_user(user_id, limit=limit)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MemoryOut)
def create_memory(body: MemoryCreate, c: ContainerDep) -> MemoryOut:
    record = c.memory.add(body.user_id, body.content, kind=body.kind)
    if record is None:
        raise HTTPException(409, "An identical memory already exists")
    return MemoryOut.of(record)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str, c: ContainerDep, user_id: str | None = None) -> Response:
    record = c.repo.get_memory(memory_id)
    if record is None or (user_id is not None and record.user_id != user_id):
        raise HTTPException(404, "Memory not found")
    c.memory.delete(memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
