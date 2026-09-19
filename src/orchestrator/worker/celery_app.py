"""Celery application. Start a worker with:

celery -A orchestrator.worker.celery_app worker --loglevel=INFO
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from orchestrator.config import get_settings

settings = get_settings()

celery_app = Celery(
    "orchestrator", broker=settings.broker_url, include=["orchestrator.worker.tasks"]
)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_default_queue="runs",
    worker_prefetch_multiplier=1,
    task_acks_late=False,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    task_time_limit=900,
    task_soft_time_limit=840,
)


@worker_process_init.connect
def _init_worker(**_: Any) -> None:
    # Connection pools are not fork-safe: build services lazily inside each child process.
    from orchestrator.runtime.container import set_container

    set_container(None)


@worker_process_shutdown.connect
def _shutdown_worker(**_: Any) -> None:
    from orchestrator.runtime import container as container_module

    if container_module._container is not None:
        container_module._container.close()
