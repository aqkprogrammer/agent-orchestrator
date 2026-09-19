"""Tool execution with validation, timing, audit logging and trace events."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from orchestrator.db.repository import Repository
from orchestrator.llm.base import Message, ToolCall
from orchestrator.runtime.events import RunEmitter
from orchestrator.tools.base import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    format_validation_error,
)


def tool_message(call: ToolCall, payload: dict[str, Any], *, is_error: bool = False) -> Message:
    return Message(
        role="tool",
        tool_call_id=call.id,
        name=call.name,
        content=json.dumps(payload, default=str),
        is_error=is_error,
    )


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, repo: Repository, emitter: RunEmitter) -> None:
        self.registry = registry
        self.repo = repo
        self.emitter = emitter

    def _audit(
        self,
        ctx: ToolContext,
        action: str,
        args: dict[str, Any],
        result: dict[str, Any] | None,
        status: str,
        latency_ms: float = 0.0,
    ) -> None:
        self.repo.add_audit(
            run_id=ctx.run_id,
            user_id=ctx.user_id,
            agent=ctx.agent,
            action=action,
            args=args,
            result=result,
            status=status,
            latency_ms=latency_ms,
        )

    def _fail(self, ctx: ToolContext, call: ToolCall, error: str) -> Message:
        payload = {"error": error}
        self._audit(ctx, call.name, call.args, payload, "error")
        self.emitter.emit(
            "tool_result",
            ctx.agent,
            tool=call.name,
            call_id=call.id,
            status="error",
            output=payload,
        )
        return tool_message(call, payload, is_error=True)

    def prepare(
        self, ctx: ToolContext, call: ToolCall, allowed: tuple[str, ...]
    ) -> tuple[Tool, BaseModel] | Message:
        """Resolve and validate a tool call. Returns an error tool message on failure."""
        self.emitter.emit("tool_call", ctx.agent, tool=call.name, call_id=call.id, args=call.args)
        tool = self.registry.get(call.name) if call.name in allowed else None
        if tool is None:
            return self._fail(ctx, call, f"Tool '{call.name}' is not available to this agent.")
        try:
            return tool, tool.validate(call.args)
        except ValidationError as exc:
            return self._fail(ctx, call, f"Invalid arguments: {format_validation_error(exc)}")

    def run(
        self,
        ctx: ToolContext,
        tool: Tool,
        call: ToolCall,
        args: BaseModel,
        *,
        approved_by: str | None = None,
    ) -> Message:
        start = time.perf_counter()
        is_error = False
        try:
            payload = tool.invoke(args, ctx)
        except ToolError as exc:
            payload, is_error = {"error": str(exc)}, True
        except Exception as exc:  # tools must never crash the graph
            payload, is_error = {"error": f"{type(exc).__name__}: {exc}"}, True
        latency = round((time.perf_counter() - start) * 1000, 2)
        status = "error" if is_error else ("approved" if approved_by else "ok")
        self.emitter.tool_calls += 1
        self._audit(ctx, tool.name, args.model_dump(), payload, status, latency)
        self.emitter.emit(
            "tool_result",
            ctx.agent,
            tool=tool.name,
            call_id=call.id,
            status=status,
            output=payload,
            latency_ms=latency,
            approved_by=approved_by,
        )
        return tool_message(call, payload, is_error=is_error)

    def record_human(
        self,
        ctx: ToolContext,
        call: ToolCall,
        args: dict[str, Any],
        payload: dict[str, Any],
        status: str,
    ) -> Message:
        """Record an outcome decided by a human (rejection or escalation answer)."""
        self._audit(ctx, call.name, args, payload, status)
        self.emitter.emit(
            "tool_result", ctx.agent, tool=call.name, call_id=call.id, status=status, output=payload
        )
        return tool_message(call, payload)
