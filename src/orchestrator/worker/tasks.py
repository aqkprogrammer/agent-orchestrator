"""Celery tasks: the worker side of the run queue."""

from __future__ import annotations

from orchestrator.runtime.container import get_container
from orchestrator.worker.celery_app import celery_app


@celery_app.task(name="orchestrator.execute_run")
def execute_run(run_id: str, approval_id: str | None = None) -> None:
    """Start a queued run, or resume a paused one after a human decision."""
    get_container().runner.execute(run_id, approval_id)
