"""Typed tool abstraction: pydantic argument schemas, risk metadata and a registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from orchestrator.llm.base import ToolSpec

if TYPE_CHECKING:
    from orchestrator.config import Settings
    from orchestrator.memory.store import MemoryStore

RiskLevel = Literal["low", "medium", "high"]


class ToolError(Exception):
    """A recoverable tool failure; the message is returned to the model."""


@dataclass
class ToolContext:
    user_id: str
    run_id: str | None
    thread_id: str | None
    memory: MemoryStore
    settings: Settings
    agent: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[[Any, ToolContext], dict[str, Any]]
    risk: RiskLevel = "low"
    sensitive: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def spec(self) -> ToolSpec:
        schema = self.args_schema.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    def validate(self, args: dict[str, Any]) -> BaseModel:
        return self.args_schema.model_validate(args)

    def invoke(self, args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        return self.handler(args, ctx)


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def subset(self, names: Iterable[str]) -> list[Tool]:
        return [self._tools[n] for n in names if n in self._tools]

    def all(self) -> list[Tool]:
        return list(self._tools.values())
