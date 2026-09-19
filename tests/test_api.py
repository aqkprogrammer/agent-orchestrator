"""HTTP-level tests, including the full HITL interrupt -> approve -> resume flow."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator.runtime.container import Container

REFUND_TASK = (
    "My name is Dana and I prefer concise answers. Order ORD-1042 arrived damaged, "
    "please refund $250 and email me at dana@example.com to confirm."
)


def create_run(client: TestClient, task: str, **extra: Any) -> dict[str, Any]:
    response = client.post("/api/runs", json={"task": task, "user_id": "dana", **extra})
    assert response.status_code == 202, response.text
    return response.json()


def test_health_and_readiness(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert set(ready.json()["checks"]) == {"database", "event_bus", "vector_store", "checkpointer"}


def test_config_and_graph(client: TestClient) -> None:
    config = client.get("/api/config").json()
    assert config["llm"]["provider"] == "mock"
    assert {a["name"] for a in config["agents"]} == {"researcher", "analyst", "ops", "writer"}
    assert any(t["name"] == "issue_refund" and t["sensitive"] for t in config["tools"])
    assert "human_review" in client.get("/api/graph").json()["mermaid"]


def test_full_hitl_flow_and_memory_recall(client: TestClient) -> None:
    run = create_run(client, REFUND_TASK)
    assert run["status"] == "awaiting_approval"

    detail = client.get(f"/api/runs/{run['id']}").json()
    refund = detail["pending_approval"]
    assert refund["tool_name"] == "issue_refund"
    assert refund["args"]["amount"] == 250.0

    inbox = client.get("/api/approvals", params={"status": "pending"}).json()
    assert [a["id"] for a in inbox] == [refund["id"]]

    # Approve the refund -> run resumes and pauses again on the outbound email.
    decided = client.post(
        f"/api/approvals/{refund['id']}/decision",
        json={"decision": "approve", "reviewer": "lead@example.com"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    again = client.post(f"/api/approvals/{refund['id']}/decision", json={"decision": "approve"})
    assert again.status_code == 409

    email = client.get(f"/api/runs/{run['id']}").json()["pending_approval"]
    assert email["tool_name"] == "send_email"
    bad_edit = client.post(
        f"/api/approvals/{email['id']}/decision",
        json={"decision": "edit", "args": {"to": "not-an-email", "subject": "x", "body": "y"}},
    )
    assert bad_edit.status_code == 422
    client.post(
        f"/api/approvals/{email['id']}/decision",
        json={
            "decision": "edit",
            "args": {"to": "dana@example.com", "subject": "Refund issued", "body": "Done!"},
        },
    )

    final = client.get(f"/api/runs/{run['id']}").json()
    assert final["status"] == "completed"
    assert final["pending_approval"] is None
    assert "Refund rf_" in final["final_answer"]
    assert "Email msg_" in final["final_answer"]

    audit = client.get(f"/api/runs/{run['id']}/audit").json()
    assert [a["action"] for a in audit] == [
        "knowledge_search",
        "recall_memory",
        "lookup_order",
        "issue_refund",
        "send_email",
    ]
    assert audit[-1]["args"]["subject"] == "Refund issued"

    events = client.get(f"/api/runs/{run['id']}/events").json()
    types = [e["type"] for e in events]
    assert types.count("approval_requested") == 2
    assert types.count("approval_resolved") == 2
    assert types[-1] == "run_completed"
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)

    memories = client.get("/api/memories", params={"user_id": "dana"}).json()
    assert {"User's name is Dana", "User prefers concise answers"} <= {
        m["content"] for m in memories
    }

    # Second run on a brand-new thread recalls long-term memory.
    second = create_run(client, "Write a short welcome note for me")
    assert second["status"] == "completed"
    assert second["thread_id"] != run["thread_id"]
    assert second["final_answer"].startswith("Hi Dana,")


def test_sse_stream_replays_events(client: TestClient) -> None:
    run = create_run(client, "What does the Pro plan include?")
    with client.stream("GET", f"/api/runs/{run['id']}/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        payloads = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]
    assert payloads[0]["type"] == "run_queued"
    assert payloads[-1]["type"] == "run_completed"

    # Resuming from an event id only returns later events.
    cursor = payloads[-3]["id"]
    with client.stream(
        "GET", f"/api/runs/{run['id']}/stream", headers={"Last-Event-ID": str(cursor)}
    ) as response:
        later = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert len(later) == 2


def test_thread_continuation_and_conflicts(client: TestClient) -> None:
    first = create_run(client, "What does the Pro plan include?")
    second = create_run(client, "How much is Starter?", thread_id=first["thread_id"])
    thread = client.get(f"/api/threads/{first['thread_id']}").json()
    assert [r["id"] for r in thread["runs"]] == [first["id"], second["id"]]
    assert len(thread["conversation"]) == 4
    assert (
        client.get("/api/threads", params={"user_id": "dana"}).json()[0]["id"] == first["thread_id"]
    )

    paused = create_run(client, "Refund $250 on ORD-1042")
    conflict = client.post(
        "/api/runs",
        json={"task": "anything", "user_id": "dana", "thread_id": paused["thread_id"]},
    )
    assert conflict.status_code == 409
    other_user = client.post(
        "/api/runs", json={"task": "x", "user_id": "mallory", "thread_id": first["thread_id"]}
    )
    assert other_user.status_code == 404


def test_run_listing_and_errors(client: TestClient) -> None:
    create_run(client, "Calculate 2 + 2")
    runs = client.get("/api/runs", params={"user_id": "dana", "status": "completed"}).json()
    assert len(runs) == 1 and runs[0]["tool_calls"] == 1
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/stream").status_code == 404
    assert client.post("/api/runs", json={"task": "", "user_id": "dana"}).status_code == 422
    assert client.post("/api/runs", json={"task": "   ", "user_id": "dana"}).status_code == 422
    assert client.post("/api/runs", json={"task": "x", "user_id": "bad id!"}).status_code == 422
    assert (
        client.post("/api/approvals/nope/decision", json={"decision": "approve"}).status_code == 404
    )


def test_memory_crud(client: TestClient) -> None:
    created = client.post(
        "/api/memories", json={"user_id": "kim", "content": "Kim manages the Berlin office"}
    )
    assert created.status_code == 201
    dup = client.post(
        "/api/memories", json={"user_id": "kim", "content": "kim manages the berlin office."}
    )
    assert dup.status_code == 409
    hits = client.get("/api/memories", params={"user_id": "kim", "q": "Berlin office"}).json()
    assert hits[0]["score"] > 0.3
    mem_id = created.json()["id"]
    assert client.delete(f"/api/memories/{mem_id}", params={"user_id": "other"}).status_code == 404
    assert client.delete(f"/api/memories/{mem_id}", params={"user_id": "kim"}).status_code == 204
    assert client.get("/api/memories", params={"user_id": "kim"}).json() == []


def test_final_review_reject(client: TestClient) -> None:
    run = create_run(client, "Forecast our churn for next year")
    approval = client.get(f"/api/runs/{run['id']}").json()["pending_approval"]
    assert approval["kind"] == "final_review"
    missing = client.post(f"/api/approvals/{approval['id']}/decision", json={"decision": "edit"})
    assert missing.status_code == 422
    client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "reject", "comment": "Too speculative"},
    )
    final = client.get(f"/api/runs/{run['id']}").json()
    assert final["status"] == "completed"
    assert "Too speculative" in final["final_answer"]


@pytest.fixture
def celery_client(container: Container) -> Any:
    """Same app, but runs dispatched through Celery in eager mode."""
    from orchestrator.api.app import create_app
    from orchestrator.runtime.dispatch import CeleryDispatcher
    from orchestrator.worker.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    container.dispatcher = CeleryDispatcher()
    try:
        with TestClient(create_app(container)) as test_client:
            yield test_client
    finally:
        celery_app.conf.task_always_eager = False


def test_runs_through_celery_eager(celery_client: TestClient) -> None:
    run = create_run(celery_client, "Refund $250 on ORD-1042")
    assert run["status"] == "awaiting_approval"
    approval = celery_client.get(f"/api/runs/{run['id']}").json()["pending_approval"]
    celery_client.post(f"/api/approvals/{approval['id']}/decision", json={"decision": "approve"})
    assert celery_client.get(f"/api/runs/{run['id']}").json()["status"] == "completed"
