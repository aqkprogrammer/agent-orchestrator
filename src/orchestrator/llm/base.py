"""Provider-neutral LLM interface used by every agent node."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """A single conversation item inside an agent's scratchpad."""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    # Provider-native assistant content (e.g. Anthropic thinking blocks) that must be
    # replayed verbatim on the next request of the same tool loop.
    raw: list[dict[str, Any]] | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0
    raw: list[dict[str, Any]] | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class PromptContext:
    """Structured view of what the prompt contains.

    Real providers only see the rendered prompt; the offline mock provider uses this
    structured form to script deterministic behaviour without parsing prose.
    """

    task: str
    agent: str
    instructions: str = ""
    memories: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    conversation: list[dict[str, Any]] = field(default_factory=list)
    scratch: list[Message] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    visits: dict[str, int] = field(default_factory=dict)


class LLMError(RuntimeError):
    """Raised when a provider fails in a way the graph should surface as a run failure."""


class LLMProvider(ABC):
    """Minimal surface the orchestrator needs: tool-calling chat + structured output."""

    name: str = "base"

    def __init__(self, model: str, supervisor_model: str | None = None) -> None:
        self.model = model
        self.supervisor_model = supervisor_model or model

    def model_for(self, agent: str) -> str:
        return self.supervisor_model if agent == "supervisor" else self.model

    @abstractmethod
    def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        context: PromptContext,
    ) -> LLMResponse:
        """One model turn that may return text and/or tool calls."""

    @abstractmethod
    def structured[T: BaseModel](
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[T],
        context: PromptContext,
    ) -> tuple[T, LLMResponse]:
        """One model turn constrained to `schema`. Returns the parsed object + metadata."""
