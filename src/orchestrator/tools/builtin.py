"""Built-in tools. Business actions (orders, refunds, email, tickets) are simulated."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from orchestrator.tools.base import Tool, ToolContext, ToolError, ToolRegistry
from orchestrator.tools.calculator import CalculatorError, evaluate
from orchestrator.tools.knowledge import default_knowledge_base

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")

# Simulated order system -------------------------------------------------------------
ORDERS: dict[str, dict[str, Any]] = {
    "ORD-1001": {"item": "Nimbus Pro annual plan", "total": 470.40, "status": "active"},
    "ORD-1002": {"item": "Wireless keyboard", "total": 89.00, "status": "delivered"},
    "ORD-1003": {"item": "Standing desk", "total": 649.00, "status": "cancelled"},
    "ORD-1042": {"item": "Noise-cancelling headphones", "total": 299.00, "status": "delivered"},
    "ORD-2001": {"item": "USB-C dock", "total": 159.99, "status": "in_transit"},
}


def _short_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8]
    return f"{prefix}_{digest}"


# Argument schemas ---------------------------------------------------------------------
class KnowledgeSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500, description="Natural-language search query.")
    top_k: int = Field(default=3, ge=1, le=8, description="Number of passages to return.")


class CalculatorArgs(BaseModel):
    expression: str = Field(
        min_length=1,
        max_length=300,
        description="Arithmetic expression, e.g. '(15/100)*2340 + 12*49'. Supports + - * / // % ** "
        "and sqrt, log, exp, sin, cos, tan, abs, round, min, max, floor, ceil, pi, e.",
    )


class CurrentTimeArgs(BaseModel):
    timezone: str = Field(default="UTC", description="IANA timezone name, e.g. 'Europe/Berlin'.")


class SaveMemoryArgs(BaseModel):
    content: str = Field(
        min_length=3, max_length=500, description="Fact to remember about the user."
    )
    kind: Literal["profile", "preference", "fact"] = "fact"


class RecallMemoryArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=10)


class LookupOrderArgs(BaseModel):
    order_id: str = Field(pattern=r"^ORD-\d{3,}$", description="Order id such as ORD-1042.")


class CreateTicketArgs(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3, max_length=4000)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class IssueRefundArgs(BaseModel):
    order_id: str = Field(pattern=r"^ORD-\d{3,}$")
    amount: float = Field(gt=0, le=100_000, description="Refund amount in USD.")
    reason: str = Field(min_length=3, max_length=500)


class SendEmailArgs(BaseModel):
    to: str = Field(description="Recipient email address.")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)

    @field_validator("to")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("must be a valid email address")
        return value


class EscalateArgs(BaseModel):
    reason: str = Field(min_length=3, max_length=500, description="Why a human is needed.")
    question: str = Field(
        min_length=3, max_length=1000, description="What the human should decide."
    )


# Handlers -----------------------------------------------------------------------------
def knowledge_search(args: KnowledgeSearchArgs, ctx: ToolContext) -> dict[str, Any]:
    hits = default_knowledge_base().search(args.query, args.top_k)
    return {
        "query": args.query,
        "results": [
            {"doc": c.doc, "title": c.title, "section": c.section, "snippet": c.text, "score": s}
            for c, s in hits
        ],
    }


def calculator(args: CalculatorArgs, ctx: ToolContext) -> dict[str, Any]:
    try:
        return {"expression": args.expression, "result": evaluate(args.expression)}
    except CalculatorError as exc:
        raise ToolError(str(exc)) from exc


def current_time(args: CurrentTimeArgs, ctx: ToolContext) -> dict[str, Any]:
    try:
        tz = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(f"Unknown timezone: {args.timezone}") from exc
    now = datetime.now(UTC).astimezone(tz)
    return {
        "timezone": args.timezone,
        "iso": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
    }


def save_memory(args: SaveMemoryArgs, ctx: ToolContext) -> dict[str, Any]:
    record = ctx.memory.add(ctx.user_id, args.content, kind=args.kind, source_run_id=ctx.run_id)
    if record is None:
        return {"status": "duplicate", "content": args.content}
    return {"status": "saved", "memory_id": record.id, "content": record.content}


def recall_memory(args: RecallMemoryArgs, ctx: ToolContext) -> dict[str, Any]:
    hits = ctx.memory.search(
        ctx.user_id, args.query, k=args.k, min_score=ctx.settings.memory_min_score
    )
    return {
        "memories": [
            {"id": r.id, "content": r.content, "kind": r.kind, "score": score} for r, score in hits
        ]
    }


def lookup_order(args: LookupOrderArgs, ctx: ToolContext) -> dict[str, Any]:
    order = ORDERS.get(args.order_id)
    if order is None:
        raise ToolError(f"Order {args.order_id} was not found")
    return {"order": {"order_id": args.order_id, **order}}


def create_ticket(args: CreateTicketArgs, ctx: ToolContext) -> dict[str, Any]:
    return {
        "status": "created",
        "ticket_id": _short_id("tkt", ctx.run_id, args.subject),
        "priority": args.priority,
        "subject": args.subject,
    }


def issue_refund(args: IssueRefundArgs, ctx: ToolContext) -> dict[str, Any]:
    order = ORDERS.get(args.order_id)
    if order is None:
        raise ToolError(f"Order {args.order_id} was not found")
    if args.amount > order["total"]:
        raise ToolError(f"Refund ${args.amount:.2f} exceeds the order total ${order['total']:.2f}")
    return {
        "status": "issued",
        "refund_id": _short_id("rf", ctx.run_id, args.order_id, args.amount),
        "order_id": args.order_id,
        "amount": round(args.amount, 2),
        "simulated": True,
    }


def send_email(args: SendEmailArgs, ctx: ToolContext) -> dict[str, Any]:
    return {
        "status": "sent",
        "message_id": _short_id("msg", ctx.run_id, args.to, args.subject),
        "to": args.to,
        "subject": args.subject,
        "simulated": True,
    }


def escalate_to_human(args: EscalateArgs, ctx: ToolContext) -> dict[str, Any]:
    # The human's answer is injected by the human_review node; this handler only runs if
    # a policy change ever lets escalations through without review.
    return {"status": "escalated", "reason": args.reason}


def build_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "knowledge_search",
                "Search the company knowledge base (policies, pricing, shipping, product FAQ). "
                "Returns the most relevant passages.",
                KnowledgeSearchArgs,
                knowledge_search,
                tags=("research",),
            ),
            Tool(
                "calculator",
                "Evaluate an arithmetic expression exactly. "
                "Use for any math instead of mental arithmetic.",
                CalculatorArgs,
                calculator,
                tags=("analysis",),
            ),
            Tool(
                "current_time",
                "Get the current date and time in a given IANA timezone.",
                CurrentTimeArgs,
                current_time,
                tags=("analysis",),
            ),
            Tool(
                "save_memory",
                "Save a durable fact about the user to long-term memory.",
                SaveMemoryArgs,
                save_memory,
                tags=("memory",),
            ),
            Tool(
                "recall_memory",
                "Semantically search the user's long-term memories.",
                RecallMemoryArgs,
                recall_memory,
                tags=("memory",),
            ),
            Tool(
                "lookup_order",
                "Look up an order's item, total and status by order id.",
                LookupOrderArgs,
                lookup_order,
                tags=("ops",),
            ),
            Tool(
                "create_ticket",
                "Create a support ticket for follow-up by the support team.",
                CreateTicketArgs,
                create_ticket,
                risk="low",
                tags=("ops",),
            ),
            Tool(
                "issue_refund",
                "Issue a refund to the customer's original payment method. Refunds above the "
                "approval threshold are paused for human approval.",
                IssueRefundArgs,
                issue_refund,
                risk="high",
                sensitive=True,
                tags=("ops",),
            ),
            Tool(
                "send_email",
                "Send an outbound email to a customer. Outbound email requires human approval.",
                SendEmailArgs,
                send_email,
                risk="medium",
                sensitive=True,
                tags=("ops",),
            ),
            Tool(
                "escalate_to_human",
                "Pause and ask a human support lead for a decision or guidance. Use when the "
                "customer asks for a manager, or you are unsure how to proceed.",
                EscalateArgs,
                escalate_to_human,
                risk="medium",
                sensitive=True,
                tags=("ops",),
            ),
        ]
    )
