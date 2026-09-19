from __future__ import annotations

from orchestrator.memory.embeddings import HashingEmbedder, tokenize
from orchestrator.runtime.container import Container


def test_hashing_embedder_is_normalized_and_deterministic() -> None:
    emb = HashingEmbedder(64)
    a, b = emb.embed(["refund policy", "refund policy"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert emb.embed_one("")  # never all-zero
    assert tokenize("The refunds were approved") == ["refund", "approv"]


def test_store_dedupes_searches_and_isolates_users(container: Container) -> None:
    store = container.memory
    first = store.add("alice", "User's name is Alice", kind="profile")
    assert first is not None
    assert store.add("alice", "  user's name is alice. ", kind="profile") is None
    store.add("alice", "User prefers dark mode", kind="preference")
    store.add("alice", "Alice's dog is called Rex", kind="fact")
    store.add("bob", "Bob's dog is called Max", kind="fact")

    hits = store.search("alice", "what is my dog called", k=5)
    assert hits[0][0].content == "Alice's dog is called Rex"
    assert all(r.user_id == "alice" for r, _ in hits)

    recalled = store.recall("alice", "dog", k=3, profile_k=5, min_score=0.1)
    reasons = {r.record.content: r.reason for r in recalled}
    assert reasons["User's name is Alice"] == "profile"
    assert reasons["Alice's dog is called Rex"] == "semantic"

    assert store.delete(first.id)
    assert all(r.id != first.id for r, _ in store.search("alice", "name Alice", k=5))
    assert not store.delete(first.id)
