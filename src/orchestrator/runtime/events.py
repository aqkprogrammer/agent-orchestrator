"""Run event persistence + fan-out (Redis pub/sub across processes, or in-process)."""

from __future__ import annotations

import asyncio
import json
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from orchestrator.db.models import RunEventRecord
from orchestrator.db.repository import Repository, iso
from orchestrator.llm.base import LLMResponse
from orchestrator.observability import get_logger

log = get_logger(__name__)

TERMINAL_EVENTS = frozenset({"run_completed", "run_failed"})


def event_to_dict(record: RunEventRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "run_id": record.run_id,
        "type": record.type,
        "agent": record.agent,
        "data": record.data,
        "created_at": iso(record.created_at),
    }


def channel_for(run_id: str) -> str:
    return f"orchestrator:run:{run_id}"


class Subscription(ABC):
    @abstractmethod
    async def get(self, timeout: float) -> dict[str, Any] | None:
        """Next event, or None after `timeout` seconds of silence."""

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


class EventBus(ABC):
    name: str

    @abstractmethod
    def publish(self, run_id: str, event: dict[str, Any]) -> None: ...

    @abstractmethod
    async def subscribe(self, run_id: str) -> Subscription: ...

    def ping(self) -> None:
        return None

    def close(self) -> None:
        return None


# ------------------------------------------------------------------ in-process bus
class _QueueSubscription(Subscription):
    def __init__(self, bus: InMemoryEventBus, run_id: str) -> None:
        self.bus, self.run_id = bus, run_id
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def get(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    async def close(self) -> None:
        self.bus._remove(self)


class InMemoryEventBus(EventBus):
    """Thread-safe bus bridging worker threads to asyncio subscribers in the same process."""

    name = "memory"

    def __init__(self) -> None:
        self._subs: dict[str, set[_QueueSubscription]] = defaultdict(set)
        self._lock = threading.Lock()

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs.get(run_id, ()))
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
            except RuntimeError:  # loop closed
                self._remove(sub)

    async def subscribe(self, run_id: str) -> Subscription:
        sub = _QueueSubscription(self, run_id)
        with self._lock:
            self._subs[run_id].add(sub)
        return sub

    def _remove(self, sub: _QueueSubscription) -> None:
        with self._lock:
            subs = self._subs.get(sub.run_id)
            if subs is not None:
                subs.discard(sub)
                if not subs:
                    self._subs.pop(sub.run_id, None)


# ------------------------------------------------------------------ redis bus
class _RedisSubscription(Subscription):
    def __init__(self, pubsub: Any, client: Any) -> None:
        self.pubsub, self.client = pubsub, client

    async def get(self, timeout: float) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            message = await self.pubsub.get_message(
                ignore_subscribe_messages=True, timeout=min(remaining, 1.0)
            )
            if message and message.get("type") == "message":
                data = message["data"]
                parsed: dict[str, Any] = json.loads(
                    data if isinstance(data, str) else data.decode()
                )
                return parsed

    async def close(self) -> None:
        try:
            await self.pubsub.aclose()
        finally:
            await self.client.aclose()


class RedisEventBus(EventBus):
    name = "redis"

    def __init__(self, url: str) -> None:
        import redis

        self.url = url
        self._client = redis.Redis.from_url(url)

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self._client.publish(channel_for(run_id), json.dumps(event, default=str))

    async def subscribe(self, run_id: str) -> Subscription:
        import redis.asyncio as aredis

        client = aredis.Redis.from_url(self.url)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel_for(run_id))
        return _RedisSubscription(pubsub, client)

    def ping(self) -> None:
        self._client.ping()

    def close(self) -> None:
        self._client.close()


# ------------------------------------------------------------------ emitter
class RunEmitter:
    """Persists an event, then publishes it. Also accumulates usage for the run."""

    def __init__(self, repo: Repository, bus: EventBus, run_id: str) -> None:
        self.repo, self.bus, self.run_id = repo, bus, run_id
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self.llm_latency_ms = 0.0

    def emit(self, type_: str, agent: str | None = None, **data: Any) -> dict[str, Any]:
        record = self.repo.add_event(self.run_id, type_, agent, _jsonable(data))
        event = event_to_dict(record)
        try:
            self.bus.publish(self.run_id, event)
        except Exception as exc:  # the DB copy is authoritative; streaming is best-effort
            log.warning("event_publish_failed", run_id=self.run_id, error=str(exc))
        return event

    def llm_call(self, agent: str, response: LLMResponse, purpose: str) -> None:
        self.llm_calls += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        self.llm_latency_ms += response.latency_ms
        self.emit(
            "llm_call",
            agent,
            purpose=purpose,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=round(response.latency_ms, 2),
            tool_calls=[c.name for c in response.tool_calls],
        )

    def flush_usage(self, wall_ms: float) -> None:
        self.repo.add_run_usage(
            self.run_id,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            llm_calls=self.llm_calls,
            tool_calls=self.tool_calls,
            latency_ms=wall_ms,
        )
        self.input_tokens = self.output_tokens = self.llm_calls = self.tool_calls = 0
        self.llm_latency_ms = 0.0


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so every stored payload is serializable."""
    return json.loads(json.dumps(value, default=str))
