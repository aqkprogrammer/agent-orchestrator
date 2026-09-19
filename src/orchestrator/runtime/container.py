"""Composition root: wires settings into concrete services, once per process."""

from __future__ import annotations

import threading
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from orchestrator.agents.policy import RiskPolicy
from orchestrator.config import Settings, get_settings
from orchestrator.db.repository import Repository
from orchestrator.db.session import create_db_engine, create_session_factory, init_db
from orchestrator.llm.base import LLMProvider
from orchestrator.llm.factory import create_embedder, create_llm
from orchestrator.memory.embeddings import Embedder
from orchestrator.memory.store import MemoryStore
from orchestrator.memory.vector import ChromaVectorIndex, InMemoryVectorIndex, VectorIndex
from orchestrator.observability import configure_logging, get_logger
from orchestrator.runtime.checkpoint import create_checkpointer
from orchestrator.runtime.dispatch import CeleryDispatcher, Dispatcher, InlineDispatcher
from orchestrator.runtime.events import EventBus, InMemoryEventBus, RedisEventBus
from orchestrator.runtime.runner import RunService
from orchestrator.tools.base import ToolRegistry
from orchestrator.tools.builtin import build_default_registry

log = get_logger(__name__)


def create_vector_index(settings: Settings) -> VectorIndex:
    if settings.vector_store == "memory":
        return InMemoryVectorIndex()
    return ChromaVectorIndex(
        mode=settings.chroma_mode,
        collection=settings.chroma_collection,
        path=settings.chroma_path,
        host=settings.chroma_host,
        port=settings.chroma_port,
    )


def create_event_bus(settings: Settings) -> EventBus:
    if settings.resolved_event_bus == "redis":
        if not settings.redis_url:
            raise ValueError("EVENT_BUS=redis requires REDIS_URL")
        return RedisEventBus(settings.redis_url)
    return InMemoryEventBus()


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        llm: LLMProvider | None = None,
        embedder: Embedder | None = None,
        vector_index: VectorIndex | None = None,
        bus: EventBus | None = None,
        synchronous_runs: bool = False,
    ) -> None:
        configure_logging(settings.log_level, settings.log_format)
        self.settings = settings
        self.engine = create_db_engine(settings.database_url)
        init_db(self.engine)
        self.repo = Repository(create_session_factory(self.engine))
        self.embedder = embedder or create_embedder(settings)
        self.vector_index = vector_index or create_vector_index(settings)
        self.memory = MemoryStore(self.repo, self.vector_index, self.embedder)
        self.registry: ToolRegistry = build_default_registry()
        self.policy = RiskPolicy(settings)
        self.llm = llm or create_llm(settings)
        self.bus = bus or create_event_bus(settings)
        self.checkpointer: BaseCheckpointSaver[Any]
        self.checkpointer, self._close_checkpointer = create_checkpointer(settings)
        self.runner = RunService(self)
        self.dispatcher: Dispatcher = (
            CeleryDispatcher()
            if settings.run_executor == "celery"
            else InlineDispatcher(
                self.runner, settings.inline_executor_workers, synchronous=synchronous_runs
            )
        )
        log.info(
            "container_ready",
            llm=self.llm.name,
            model=self.llm.model,
            checkpointer=settings.resolved_checkpointer,
            event_bus=self.bus.name,
            vector_store=self.vector_index.name,
            executor=self.dispatcher.name,
        )

    def close(self) -> None:
        self.dispatcher.close()
        self.bus.close()
        self._close_checkpointer()
        self.engine.dispose()


_container: Container | None = None
_lock = threading.Lock()


def get_container() -> Container:
    global _container
    with _lock:
        if _container is None:
            _container = Container(get_settings())
        return _container


def set_container(container: Container | None) -> None:
    global _container
    with _lock:
        _container = container
