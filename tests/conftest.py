from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.api.app import create_app
from orchestrator.config import Settings
from orchestrator.runtime.container import Container, set_container


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        log_level="WARNING",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        checkpointer="sqlite",
        checkpoint_sqlite_path=str(tmp_path / "checkpoints.db"),
        event_bus="memory",
        run_executor="inline",
        vector_store="chroma",
        chroma_mode="ephemeral",
        chroma_collection=f"test_{uuid.uuid4().hex[:12]}",
        llm_provider="mock",
        redis_url=None,
    )


@pytest.fixture
def container(settings: Settings) -> Iterator[Container]:
    c = Container(settings, synchronous_runs=True)
    yield c
    set_container(None)
    c.close()


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client
