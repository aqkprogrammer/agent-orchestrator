"""Text embedders: an offline hashing embedder and an OpenAI-backed one."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from itertools import pairwise
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS_TEXT = (
    "a an and are as at be but by can could did do does for from had has have how i "
    "if in into is it its me my of on or our please so that the their them there "
    "these they this to us was we were what when where which who why will with "
    "would you your about just also than then too very"
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


def _stem(word: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ers", "ies", "ied", "es", "ed", "er", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS]


class Embedder(ABC):
    dim: int
    name: str

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder(Embedder):
    """Deterministic feature-hashing embedder (unigrams + bigrams, signed, L2-normalised).

    Not semantic in the neural sense, but lexical overlap after stemming and stop-word
    removal is a solid, dependency-free baseline and keeps tests fully offline.
    """

    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[tuple[str, float]]:
        tokens = tokenize(text)
        feats = [(t, 1.0) for t in tokens]
        feats += [(f"{a}_{b}", 0.5) for a, b in pairwise(tokens)]
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat, weight in self._features(text):
                digest = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[idx] += sign * weight
            norm = math.sqrt(sum(v * v for v in vec))
            if norm == 0:
                vec[0] = 1e-6  # Chroma rejects all-zero vectors under cosine distance
                norm = 1e-6
            vectors.append([v / norm for v in vec])
        return vectors


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, *, api_key: str | None, model: str, base_url: str | None = None) -> None:
        import openai

        self.client: Any = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.dim = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in response.data]
