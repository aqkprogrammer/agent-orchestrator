"""Select an LLM provider / embedder from settings."""

from __future__ import annotations

from orchestrator.config import Settings
from orchestrator.llm.base import LLMProvider
from orchestrator.memory.embeddings import Embedder, HashingEmbedder, OpenAIEmbedder


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    return getter() if getter else None


def create_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from orchestrator.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=_secret(settings.anthropic_api_key),
            model=settings.anthropic_model,
            supervisor_model=settings.supervisor_model,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "openai":
        from orchestrator.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=_secret(settings.openai_api_key),
            model=settings.openai_model,
            supervisor_model=settings.supervisor_model,
            base_url=settings.openai_base_url,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
    from orchestrator.llm.mock import MockProvider

    return MockProvider()


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(
            api_key=_secret(settings.openai_api_key),
            model=settings.embedding_model,
            base_url=settings.openai_base_url,
        )
    return HashingEmbedder(settings.embedding_dim)
