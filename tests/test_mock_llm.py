from __future__ import annotations

from orchestrator.agents.contracts import MemoryExtraction, RouteDecision
from orchestrator.llm.base import Message, PromptContext
from orchestrator.llm.mock import MockProvider, extract_expressions, plan_agents


def test_plan_agents_orders_specialists() -> None:
    assert plan_agents("Refund $250 for ORD-1042") == ["researcher", "ops"]
    assert plan_agents("Calculate 15% of 2,340") == ["analyst"]
    assert plan_agents("Research the refund policy and write a summary") == [
        "researcher",
        "ops",
        "writer",
    ]
    assert plan_agents("hello there") == ["researcher", "writer"]


def test_extract_expressions() -> None:
    assert extract_expressions("Calculate 15% of 2,340 and add 12 * 49") == [
        "(15/100)*2340",
        "12 * 49",
    ]
    assert extract_expressions("Order ORD-1042 arrived") == []


def test_route_skips_completed_agents() -> None:
    llm = MockProvider()
    ctx = PromptContext(
        task="Refund $250 for ORD-1042",
        agent="supervisor",
        steps=[{"agent": "researcher", "output": "ok"}],
        agents=["researcher", "analyst", "ops", "writer"],
    )
    decision, meta = llm.structured(
        system="s", messages=[Message(role="user", content="x")], schema=RouteDecision, context=ctx
    )
    assert decision.next == "ops"
    assert meta.usage.output_tokens > 0


def test_memory_extraction() -> None:
    llm = MockProvider()
    ctx = PromptContext(
        task="My name is Dana, I work at Acme Corp. I prefer concise answers. "
        "Remember that my favorite color is teal.",
        agent="memory",
    )
    result, _ = llm.structured(system="s", messages=[], schema=MemoryExtraction, context=ctx)
    contents = {m.content for m in result.memories}
    assert "User's name is Dana" in contents
    assert "User works at Acme Corp" in contents
    assert "User prefers concise answers" in contents
    assert {m.kind for m in result.memories} >= {"profile", "preference"}
