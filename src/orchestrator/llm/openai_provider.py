"""OpenAI provider built on the official `openai` SDK (Chat Completions + tools)."""

from __future__ import annotations

import json
import time
from typing import Any

import openai
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


def to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.role == "user":
            out.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.args)},
                    }
                    for c in msg.tool_calls
                ]
            out.append(item)
        else:
            out.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
    return out


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        supervisor_model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        client: Any | None = None,
    ) -> None:
        super().__init__(model, supervisor_model)
        self.max_tokens = max_tokens
        self.client = client or openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    def _call(self, fn: Any, **kwargs: Any) -> tuple[Any, float]:
        start = time.perf_counter()
        try:
            response = fn(**kwargs)
        except openai.RateLimitError as exc:
            raise LLMError(f"OpenAI rate limit exceeded: {exc.message}") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"OpenAI API error {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the OpenAI API") from exc
        return response, (time.perf_counter() - start) * 1000

    @staticmethod
    def _usage(response: Any) -> Usage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
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
            "messages": to_openai_messages(system, messages),
            "max_completion_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        response, latency = self._call(self.client.chat.completions.create, **kwargs)
        choice = response.choices[0].message
        calls: list[ToolCall] = []
        for call in choice.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": call.function.arguments}
            calls.append(ToolCall(id=call.id, name=call.function.name, args=args))
        return LLMResponse(
            content=(choice.content or "").strip(),
            tool_calls=calls,
            usage=self._usage(response),
            model=model,
            latency_ms=latency,
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
            self.client.chat.completions.parse,
            model=model,
            messages=to_openai_messages(system, messages),
            response_format=schema,
            max_completion_tokens=self.max_tokens,
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMError(f"The model refused: {message.refusal}")
        parsed = message.parsed
        if parsed is None:
            raise LLMError(f"Model did not return a valid {schema.__name__}")
        meta = LLMResponse(
            content=parsed.model_dump_json(),
            usage=self._usage(response),
            model=model,
            latency_ms=latency,
        )
        return parsed, meta
