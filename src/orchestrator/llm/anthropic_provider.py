"""Anthropic (Claude) provider built on the official `anthropic` SDK."""

from __future__ import annotations

import time
from typing import Any

import anthropic
from pydantic import BaseModel

from orchestrator.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponse,
    Message,
    PromptContext,
    ToolCall,
    ToolSpec,
    Usage,
)

_REPLAYABLE_BLOCKS = {"text", "thinking", "redacted_thinking", "tool_use"}


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert neutral messages to Anthropic's format.

    Consecutive tool results are merged into a single user turn, as the API expects all
    results for one assistant turn to arrive together.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "user":
            out.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.raw:
                content: list[dict[str, Any]] = list(msg.raw)
            else:
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for call in msg.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
                    )
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
        else:
            block = {
                "type": "tool_result",
                "tool_use_id": msg.tool_call_id,
                "content": msg.content,
                "is_error": msg.is_error,
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        supervisor_model: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        client: Any | None = None,
    ) -> None:
        super().__init__(model, supervisor_model)
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def _call(self, fn: Any, **kwargs: Any) -> tuple[Any, float]:
        start = time.perf_counter()
        try:
            response = fn(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit exceeded: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API") from exc
        latency = (time.perf_counter() - start) * 1000
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to answer this request (stop_reason=refusal).")
        return response, latency

    @staticmethod
    def _usage(response: Any) -> Usage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )

    def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        context: PromptContext,
    ) -> LLMResponse:
        model = self.model_for(context.agent)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        response, latency = self._call(self.client.messages.create, **kwargs)

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []
        for block in response.content:
            if block.type in _REPLAYABLE_BLOCKS:
                raw.append(block.model_dump(exclude_none=True))
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input or {})))
        return LLMResponse(
            content="".join(text_parts).strip(),
            tool_calls=calls,
            usage=self._usage(response),
            model=model,
            latency_ms=latency,
            raw=raw,
        )

    def structured[T: BaseModel](
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[T],
        context: PromptContext,
    ) -> tuple[T, LLMResponse]:
        model = self.model_for(context.agent)
        response, latency = self._call(
            self.client.messages.parse,
            model=model,
            max_tokens=self.max_tokens,
            system=system,
            messages=to_anthropic_messages(messages),
            output_format=schema,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"Model did not return a valid {schema.__name__}")
        meta = LLMResponse(
            content=parsed.model_dump_json(),
            usage=self._usage(response),
            model=model,
            latency_ms=latency,
        )
        return parsed, meta
