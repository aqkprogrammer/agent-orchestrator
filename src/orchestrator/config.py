"""Application configuration loaded from environment variables (and `.env`)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Every field maps to an upper-case environment variable."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- application ---------------------------------------------------------------
    app_name: str = "agent-orchestrator"
    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # --- persistence ---------------------------------------------------------------
    database_url: str = "sqlite:///./data/orchestrator.db"
    checkpointer: Literal["auto", "postgres", "sqlite", "memory"] = "auto"
    checkpoint_sqlite_path: str = "./data/checkpoints.db"

    # --- queue / events ------------------------------------------------------------
    redis_url: str | None = None
    event_bus: Literal["auto", "redis", "memory"] = "auto"
    run_executor: Literal["inline", "celery"] = "inline"
    celery_broker_url: str | None = None
    celery_task_always_eager: bool = False
    inline_executor_workers: int = 4

    # --- vector memory -------------------------------------------------------------
    vector_store: Literal["chroma", "memory"] = "chroma"
    chroma_mode: Literal["ephemeral", "persistent", "http"] = "persistent"
    chroma_path: str = "./data/chroma"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "agent_memories"

    # --- models --------------------------------------------------------------------
    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-5-mini"
    supervisor_model: str | None = Field(
        default=None, description="Optional model override for the supervisor/router."
    )
    llm_max_tokens: int = 4096
    llm_timeout_seconds: float = 120.0

    embedding_provider: Literal["hashing", "openai"] = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384

    # --- orchestration policy ------------------------------------------------------
    max_supervisor_steps: int = Field(default=6, ge=1, le=20)
    max_agent_visits: int = Field(default=2, ge=1, le=10)
    max_tool_rounds: int = Field(default=4, ge=1, le=10)
    recursion_limit: int = 60
    refund_approval_threshold: float = 100.0
    email_requires_approval: bool = True
    confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    memory_recall_k: int = 5
    memory_profile_k: int = 5
    memory_min_score: float = 0.12
    max_task_chars: int = 4000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # --- derived helpers -------------------------------------------------------------
    @property
    def uses_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def resolved_checkpointer(self) -> Literal["postgres", "sqlite", "memory"]:
        if self.checkpointer != "auto":
            return self.checkpointer
        return "postgres" if self.uses_postgres else "sqlite"

    @property
    def resolved_event_bus(self) -> Literal["redis", "memory"]:
        if self.event_bus != "auto":
            return self.event_bus
        return "redis" if self.redis_url else "memory"

    @property
    def postgres_conninfo(self) -> str:
        """Plain libpq connection string (strips the SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url or "memory://"

    @property
    def active_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        if self.llm_provider == "openai":
            return self.openai_model
        return "mock-scripted-v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
