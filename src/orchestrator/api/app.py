"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from orchestrator import __version__
from orchestrator.api.routes import approvals, memories, runs, system, threads
from orchestrator.config import get_settings
from orchestrator.observability import configure_logging, get_logger
from orchestrator.runtime.container import Container, get_container, set_container

log = get_logger("orchestrator.api")


def create_app(container: Container | None = None) -> FastAPI:
    settings = container.settings if container else get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        c = container or get_container()
        if not owned:
            set_container(c)  # let Celery eager tasks resolve the same services
        app.state.container = c
        log.info("api_started", version=__version__)
        try:
            yield
        finally:
            if owned:
                c.close()
                set_container(None)

    app = FastAPI(
        title="Agent Orchestrator",
        version=__version__,
        description="Supervisor-led multi-agent system with tools, memory and human-in-the-loop.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["x-request-id"] = request_id
        if not request.url.path.startswith("/health"):
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
                request_id=request_id,
            )
        return response

    for module in (system, runs, approvals, memories, threads):
        app.include_router(module.router)
    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory orchestrator.api.app:app_factory`."""
    return create_app()
