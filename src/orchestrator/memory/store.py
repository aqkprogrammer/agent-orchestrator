"""Long-term memory: Postgres/SQLite is the source of truth, the vector index is for recall."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from orchestrator.db.models import MemoryRecord
from orchestrator.db.repository import Repository
from orchestrator.memory.embeddings import Embedder
from orchestrator.memory.vector import VectorIndex
from orchestrator.observability import get_logger

log = get_logger(__name__)

MEMORY_KINDS = ("profile", "preference", "fact")


@dataclass
class RecalledMemory:
    record: MemoryRecord
    score: float | None  # None when included as a profile/preference memory
    reason: str  # "semantic" | "profile"


def content_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", content.strip().lower()).rstrip(".")
    return hashlib.sha256(normalized.encode()).hexdigest()


class MemoryStore:
    def __init__(self, repo: Repository, index: VectorIndex, embedder: Embedder) -> None:
        self.repo = repo
        self.index = index
        self.embedder = embedder

    def add(
        self,
        user_id: str,
        content: str,
        *,
        kind: str = "fact",
        source_run_id: str | None = None,
    ) -> MemoryRecord | None:
        """Persist and index a memory. Returns None for duplicates."""
        content = content.strip()
        if not content:
            return None
        if kind not in MEMORY_KINDS:
            kind = "fact"
        record = self.repo.add_memory(
            user_id=user_id,
            content=content,
            content_hash=content_hash(content),
            kind=kind,
            source_run_id=source_run_id,
        )
        if record is None:
            return None
        try:
            self.index.upsert(record.id, self.embedder.embed_one(content), content, user_id, kind)
        except Exception:
            # Keep SQL and the index consistent: a memory that cannot be recalled is removed.
            self.repo.delete_memory(record.id)
            raise
        return record

    def search(
        self, user_id: str, query: str, *, k: int = 5, min_score: float = 0.0
    ) -> list[tuple[MemoryRecord, float]]:
        hits = self.index.query(self.embedder.embed_one(query), user_id, k)
        hits = [h for h in hits if h.score >= min_score]
        records = {r.id: r for r in self.repo.get_memories([h.id for h in hits])}
        return [(records[h.id], round(h.score, 4)) for h in hits if h.id in records]

    def recall(
        self, user_id: str, query: str, *, k: int, profile_k: int, min_score: float
    ) -> list[RecalledMemory]:
        """Semantic top-k plus the user's most recent profile/preference memories."""
        recalled: dict[str, RecalledMemory] = {}
        for record in self.repo.list_memories(
            user_id, kinds=("profile", "preference"), limit=profile_k
        ):
            recalled[record.id] = RecalledMemory(record, None, "profile")
        for record, score in self.search(user_id, query, k=k, min_score=min_score):
            recalled[record.id] = RecalledMemory(record, score, "semantic")
        return list(recalled.values())

    def list_for_user(
        self, user_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[MemoryRecord]:
        return list(self.repo.list_memories(user_id, limit=limit, offset=offset))

    def delete(self, memory_id: str) -> bool:
        deleted = self.repo.delete_memory(memory_id)
        try:
            self.index.delete(memory_id)
        except Exception as exc:  # pragma: no cover - index hiccups must not block deletes
            log.warning("vector_delete_failed", memory_id=memory_id, error=str(exc))
        return deleted
