"""Structured-output contracts exchanged between the graph and the LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    """Supervisor routing decision."""

    next: str = Field(description="Name of the worker agent to call next, or FINISH when done.")
    instructions: str = Field(
        default="", description="Concrete instructions for the selected worker agent."
    )
    reasoning: str = Field(default="", description="One or two sentences explaining the choice.")


class FinalAnswer(BaseModel):
    """Final synthesized answer for the user."""

    answer: str = Field(description="The complete answer to return to the user.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Calibrated confidence (0-1) that the answer is correct."
    )


class MemoryItem(BaseModel):
    content: str = Field(description="A short, self-contained statement about the user.")
    kind: Literal["profile", "preference", "fact"] = "fact"


class MemoryExtraction(BaseModel):
    """Durable facts worth remembering about the user across conversations."""

    memories: list[MemoryItem] = Field(default_factory=list)
