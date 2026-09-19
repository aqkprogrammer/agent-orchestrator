from __future__ import annotations

from typing import Any

import pytest

from orchestrator.agents.policy import RiskPolicy
from orchestrator.config import Settings
from orchestrator.runtime.container import Container
from orchestrator.tools.base import ToolContext, ToolError
from orchestrator.tools.builtin import build_default_registry
from orchestrator.tools.knowledge import default_knowledge_base


@pytest.fixture
def ctx(container: Container) -> ToolContext:
    return ToolContext(
        user_id="u1",
        run_id="r1",
        thread_id="t1",
        memory=container.memory,
        settings=container.settings,
        agent="ops",
    )


def run_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    tool = build_default_registry().get(name)
    assert tool is not None
    return tool.invoke(tool.validate(args), ctx)


def test_registry_exposes_json_schemas() -> None:
    registry = build_default_registry()
    names = {t.name for t in registry.all()}
    assert {"knowledge_search", "calculator", "issue_refund", "send_email"} <= names
    spec = registry.get("issue_refund").spec()  # type: ignore[union-attr]
    assert spec.parameters["type"] == "object"
    assert set(spec.parameters["required"]) == {"order_id", "amount", "reason"}
    assert "title" not in spec.parameters


def test_knowledge_search_ranks_relevant_section() -> None:
    hits = default_knowledge_base().search("refund approval limit above $100", 2)
    assert hits
    assert hits[0][0].doc == "refund_policy"


def test_calculator_tool(ctx: ToolContext) -> None:
    assert run_tool("calculator", {"expression": "12*49"}, ctx)["result"] == 588
    with pytest.raises(ToolError):
        run_tool("calculator", {"expression": "import os"}, ctx)


def test_refund_cannot_exceed_order_total(ctx: ToolContext) -> None:
    ok = run_tool("issue_refund", {"order_id": "ORD-1002", "amount": 20, "reason": "late"}, ctx)
    assert ok["status"] == "issued"
    with pytest.raises(ToolError, match="exceeds"):
        run_tool("issue_refund", {"order_id": "ORD-1002", "amount": 500, "reason": "late"}, ctx)


def test_argument_validation() -> None:
    registry = build_default_registry()
    with pytest.raises(ValueError, match="valid email"):
        registry.get("send_email").validate({"to": "nope", "subject": "s", "body": "b"})  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="greater than 0"):
        registry.get("issue_refund").validate(  # type: ignore[union-attr]
            {"order_id": "ORD-1", "amount": -5, "reason": "x"}
        )


def test_memory_tools_round_trip(ctx: ToolContext) -> None:
    saved = run_tool("save_memory", {"content": "User's favourite colour is teal"}, ctx)
    assert saved["status"] == "saved"
    assert (
        run_tool("save_memory", {"content": "User's favourite colour is teal"}, ctx)["status"]
        == "duplicate"
    )
    recalled = run_tool("recall_memory", {"query": "favourite colour"}, ctx)
    assert recalled["memories"][0]["content"] == "User's favourite colour is teal"


def test_current_time_rejects_bad_timezone(ctx: ToolContext) -> None:
    assert "iso" in run_tool("current_time", {"timezone": "Europe/Berlin"}, ctx)
    with pytest.raises(ToolError):
        run_tool("current_time", {"timezone": "Mars/Olympus"}, ctx)


def test_risk_policy(settings: Settings) -> None:
    policy = RiskPolicy(settings)
    registry = build_default_registry()
    refund = registry.get("issue_refund")
    email = registry.get("send_email")
    escalate = registry.get("escalate_to_human")
    calc = registry.get("calculator")
    assert refund and email and escalate and calc
    assert not policy.evaluate_tool(refund, {"amount": 50}).requires_approval
    high = policy.evaluate_tool(refund, {"amount": 250})
    assert high.requires_approval and high.risk_level == "high"
    assert policy.evaluate_tool(email, {"to": "a@b.co"}).requires_approval
    assert policy.evaluate_tool(escalate, {"reason": "x"}).kind == "escalation"
    assert not policy.evaluate_tool(calc, {"expression": "1"}).requires_approval
    assert policy.evaluate_answer(0.2).kind == "final_review"
    assert not policy.evaluate_answer(0.9).requires_approval
