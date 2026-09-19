"""Risk policy deciding when a human must approve an action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from orchestrator.config import Settings
from orchestrator.tools.base import RiskLevel, Tool

ApprovalKind = Literal["tool", "escalation", "final_review"]


@dataclass(frozen=True)
class PolicyDecision:
    requires_approval: bool
    kind: ApprovalKind = "tool"
    reason: str = ""
    risk_level: RiskLevel = "low"


class RiskPolicy:
    def __init__(self, settings: Settings) -> None:
        self.refund_threshold = settings.refund_approval_threshold
        self.email_requires_approval = settings.email_requires_approval
        self.confidence_threshold = settings.confidence_threshold

    def evaluate_tool(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        if tool.name == "escalate_to_human":
            return PolicyDecision(
                True, "escalation", f"Agent escalated: {args.get('reason', '')}".strip(), "medium"
            )
        if tool.name == "issue_refund":
            amount = float(args.get("amount", 0))
            if amount > self.refund_threshold:
                return PolicyDecision(
                    True,
                    "tool",
                    f"Refund of ${amount:,.2f} exceeds the ${self.refund_threshold:,.2f} "
                    "auto-approval limit.",
                    "high",
                )
            return PolicyDecision(False, risk_level="medium")
        if tool.name == "send_email" and self.email_requires_approval:
            return PolicyDecision(
                True,
                "tool",
                f"Outbound email to {args.get('to', 'a customer')} needs review.",
                "medium",
            )
        return PolicyDecision(False, risk_level=tool.risk)

    def evaluate_answer(self, confidence: float) -> PolicyDecision:
        if confidence < self.confidence_threshold:
            return PolicyDecision(
                True,
                "final_review",
                f"Answer confidence {confidence:.2f} is below the {self.confidence_threshold:.2f} "
                "threshold.",
                "medium",
            )
        return PolicyDecision(False)

    def describe(self) -> dict[str, Any]:
        return {
            "refund_approval_threshold": self.refund_threshold,
            "email_requires_approval": self.email_requires_approval,
            "confidence_threshold": self.confidence_threshold,
            "always_escalate": ["escalate_to_human"],
        }
