"""Local knowledge base with BM25 ranking over markdown sections."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from orchestrator.memory.embeddings import tokenize

KB_DIR = Path(__file__).parent / "knowledge_base"


@dataclass(frozen=True)
class Chunk:
    doc: str
    title: str
    section: str
    text: str


def _chunk_file(path: Path) -> list[Chunk]:
    title = path.stem.replace("_", " ").title()
    sections: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif line.strip() and sections:
            sections[-1][1].append(line.strip())
    return [Chunk(path.stem, title, name, " ".join(body)) for name, body in sections if body]


def load_chunks(directory: Path = KB_DIR) -> list[Chunk]:
    return [chunk for path in sorted(directory.glob("*.md")) for chunk in _chunk_file(path)]


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._tokens = [tokenize(f"{c.title} {c.section} {c.text}") for c in chunks]
        self._tf = [Counter(t) for t in self._tokens]
        n = len(chunks)
        df: Counter[str] = Counter()
        for toks in self._tokens:
            df.update(set(toks))
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._avgdl = sum(len(t) for t in self._tokens) / max(n, 1)

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        terms = tokenize(query)
        scored: list[tuple[Chunk, float]] = []
        for chunk, tf, toks in zip(self.chunks, self._tf, self._tokens, strict=True):
            score = 0.0
            for term in terms:
                if term not in tf:
                    continue
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * len(toks) / self._avgdl)
                score += self._idf.get(term, 0.0) * freq * (self.k1 + 1) / denom
            if score > 0:
                scored.append((chunk, round(score, 3)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


@lru_cache
def default_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(load_chunks())
