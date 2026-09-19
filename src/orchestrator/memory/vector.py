"""Vector index adapters (ChromaDB and a tiny in-process fallback)."""

from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class VectorHit:
    id: str
    score: float  # cosine similarity in [-1, 1]


class VectorIndex(ABC):
    name: str

    @abstractmethod
    def upsert(
        self, id_: str, embedding: list[float], document: str, user_id: str, kind: str
    ) -> None: ...

    @abstractmethod
    def query(self, embedding: list[float], user_id: str, k: int) -> list[VectorHit]: ...

    @abstractmethod
    def delete(self, id_: str) -> None: ...

    @abstractmethod
    def ping(self) -> None: ...


class ChromaVectorIndex(VectorIndex):
    name = "chroma"

    def __init__(
        self,
        *,
        mode: str,
        collection: str,
        path: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        settings = ChromaSettings(anonymized_telemetry=False)
        client: Any
        if mode == "http":
            client = self._connect_http(chromadb, host or "localhost", port or 8000, settings)
        elif mode == "persistent":
            client = chromadb.PersistentClient(path=path or "./data/chroma", settings=settings)
        else:
            client = chromadb.EphemeralClient(settings=settings)
        self.client = client
        self.collection = client.get_or_create_collection(
            collection, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    @staticmethod
    def _connect_http(
        chromadb: Any, host: str, port: int, settings: Any, attempts: int = 10
    ) -> Any:
        """The Chroma server may still be booting when the API/worker start: retry briefly."""
        for attempt in range(1, attempts + 1):
            try:
                client = chromadb.HttpClient(host=host, port=port, settings=settings)
                client.heartbeat()
                return client
            except Exception:
                if attempt == attempts:
                    raise
                time.sleep(min(2.0, 0.25 * attempt))
        raise RuntimeError("unreachable")  # pragma: no cover

    def upsert(
        self, id_: str, embedding: list[float], document: str, user_id: str, kind: str
    ) -> None:
        self.collection.upsert(
            ids=[id_],
            embeddings=[embedding],
            documents=[document],
            metadatas=[{"user_id": user_id, "kind": kind}],
        )

    def query(self, embedding: list[float], user_id: str, k: int) -> list[VectorHit]:
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=k,
            where={"user_id": user_id},
            include=["distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [VectorHit(id=i, score=1.0 - float(d)) for i, d in zip(ids, distances, strict=False)]

    def delete(self, id_: str) -> None:
        self.collection.delete(ids=[id_])

    def ping(self) -> None:
        self.client.heartbeat()


class InMemoryVectorIndex(VectorIndex):
    """Brute-force cosine search. Handy for unit tests and tiny deployments."""

    name = "memory"

    def __init__(self) -> None:
        self._items: dict[str, tuple[list[float], str]] = {}
        self._lock = threading.Lock()

    def upsert(
        self, id_: str, embedding: list[float], document: str, user_id: str, kind: str
    ) -> None:
        with self._lock:
            self._items[id_] = (embedding, user_id)

    def query(self, embedding: list[float], user_id: str, k: int) -> list[VectorHit]:
        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=False))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        with self._lock:
            scored = [
                VectorHit(id=i, score=cosine(embedding, vec))
                for i, (vec, uid) in self._items.items()
                if uid == user_id
            ]
        return sorted(scored, key=lambda h: h.score, reverse=True)[:k]

    def delete(self, id_: str) -> None:
        with self._lock:
            self._items.pop(id_, None)

    def ping(self) -> None:
        return None
