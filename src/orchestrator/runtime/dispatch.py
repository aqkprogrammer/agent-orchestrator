"""How runs get executed: Celery workers (production) or an in-process pool (local/test)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor

from orchestrator.observability import get_logger
from orchestrator.runtime.runner import RunService

log = get_logger(__name__)


def _log_crash(future: Future[None]) -> None:
    if not future.cancelled() and future.exception() is not None:
        log.error("inline_run_crashed", error=str(future.exception()))


class Dispatcher(ABC):
    name: str

    @abstractmethod
    def submit(self, run_id: str, approval_id: str | None = None) -> None: ...

    def close(self) -> None:
        return None


class InlineDispatcher(Dispatcher):
    """Runs graphs in a background thread pool inside the API process (no broker needed)."""

    name = "inline"

    def __init__(self, runner: RunService, workers: int = 4, synchronous: bool = False) -> None:
        self.runner = runner
        self.synchronous = synchronous
        self._pool = None if synchronous else ThreadPoolExecutor(workers, "run-worker")

    def submit(self, run_id: str, approval_id: str | None = None) -> None:
        if self._pool is None:
            self.runner.execute(run_id, approval_id)
            return
        future = self._pool.submit(self.runner.execute, run_id, approval_id)
        future.add_done_callback(_log_crash)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)


class CeleryDispatcher(Dispatcher):
    name = "celery"

    def submit(self, run_id: str, approval_id: str | None = None) -> None:
        from orchestrator.worker.tasks import execute_run

        execute_run.delay(run_id, approval_id)
