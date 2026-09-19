"""Health, configuration, graph topology and audit endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from orchestrator import __version__
from orchestrator.agents.specs import AGENTS
from orchestrator.api.deps import ContainerDep
from orchestrator.api.schemas import AuditOut

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe: the process is up."""
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
def ready(c: ContainerDep) -> JSONResponse:
    """Readiness probe: dependencies are reachable."""
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, fn: Callable[[], Any], detail: str) -> None:
        try:
            fn()
            checks[name] = {"ok": True, "backend": detail}
        except Exception as exc:
            checks[name] = {"ok": False, "backend": detail, "error": str(exc)[:300]}

    check("database", c.repo.ping, "postgres" if c.settings.uses_postgres else "sqlite")
    check("event_bus", c.bus.ping, c.bus.name)
    check("vector_store", c.vector_index.ping, c.vector_index.name)
    check("checkpointer", lambda: None, c.settings.resolved_checkpointer)
    healthy = all(v["ok"] for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


@router.get("/api/config")
def config(c: ContainerDep) -> dict[str, Any]:
    s = c.settings
    return {
        "version": __version__,
        "llm": {"provider": c.llm.name, "model": c.llm.model},
        "embedding": {"provider": c.embedder.name, "dim": c.embedder.dim},
        "infrastructure": {
            "executor": c.dispatcher.name,
            "checkpointer": s.resolved_checkpointer,
            "event_bus": c.bus.name,
            "vector_store": c.vector_index.name,
            "database": "postgres" if s.uses_postgres else "sqlite",
        },
        "limits": {
            "max_supervisor_steps": s.max_supervisor_steps,
            "max_agent_visits": s.max_agent_visits,
            "max_tool_rounds": s.max_tool_rounds,
            "max_task_chars": s.max_task_chars,
        },
        "policy": c.policy.describe(),
        "agents": [
            {"name": a.name, "title": a.title, "description": a.description, "tools": list(a.tools)}
            for a in AGENTS.values()
        ],
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "risk": t.risk,
                "sensitive": t.sensitive,
                "parameters": t.spec().parameters,
            }
            for t in c.registry.all()
        ],
    }


@router.get("/api/graph")
def graph(c: ContainerDep) -> dict[str, str]:
    """Mermaid source for the compiled LangGraph."""
    return {"mermaid": c.runner.mermaid()}


@router.get("/api/audit", response_model=list[AuditOut])
def audit(
    c: ContainerDep,
    user_id: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AuditOut]:
    return [AuditOut.of(a) for a in c.repo.list_audit(user_id=user_id, run_id=run_id, limit=limit)]
