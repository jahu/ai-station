from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


def drain(session, worker="workflow-test", limit=30):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def create(api, **extra):
    result = api.post(
        "/api/agents",
        json={"name": "Workflow", "goal": "Summarize available context", "model": "fake-local", **extra},
    )
    assert result.status_code == 201, result.text
    return result.json()


def run_now(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def workflow_step(api, parent_id, key):
    parent = api.get("/api/runs/" + parent_id).json()
    step = next(item for item in parent["workflow"]["steps"] if item["key"] == key)
    return api.get("/api/runs/" + step["run_id"]).json()


def test_sequential_steps_persist_dependencies_and_artifacts(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs["messages"])
        yield "Sequential report"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"], workflow_mode="sequential")
    queued = run_now(api, agent)
    assert queued["capability"] == "agent.workflow"
    with session_factory()() as session:
        drain(session)
    parent = api.get("/api/runs/" + queued["id"]).json()
    search = workflow_step(api, queued["id"], "memory_search")
    report = workflow_step(api, queued["id"], "report")
    assert parent["status"] == "succeeded"
    assert parent["workflow"]["mode"] == "sequential"
    assert [step["key"] for step in parent["workflow"]["steps"]] == ["memory_search", "report"]
    assert search["status"] == "succeeded" and report["status"] == "succeeded"
    assert search["parent_run_id"] == queued["id"] and report["parent_run_id"] == queued["id"]
    assert report["parameters"]["tool_context"][0]["tool"] == "memory_search"
    assert {item["type"] for item in api.get("/api/artifacts?run_id=" + queued["id"]).json()} == {"json"}
    assert {item["type"] for item in api.get("/api/artifacts?run_id=" + search["id"]).json()} == {"json"}
    assert {item["type"] for item in api.get("/api/artifacts?run_id=" + report["id"]).json()} == {"markdown"}
    assert received and "memory_search" in str(received)


def test_gated_report_waits_for_approval_after_context(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(True)
        yield "Gated report"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"], workflow_mode="gated")
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    search = workflow_step(api, queued["id"], "memory_search")
    report = workflow_step(api, queued["id"], "report")
    assert search["status"] == "succeeded"
    assert report["status"] == "waiting_for_approval"
    assert report["approval"]["resolution"] == "pending"
    assert received == []
    granted = api.post(f"/api/runs/{report['id']}/approval", json={"resolution": "granted"})
    assert granted.status_code == 200 and granted.json()["status"] == "queued"
    with session_factory()() as session:
        drain(session)
    assert workflow_step(api, queued["id"], "report")["status"] == "succeeded"
    assert received


def test_canceling_the_parent_stops_the_active_child(monkeypatch):
    closed = []

    async def silent(self, **kwargs):
        with session_factory()() as current:
            parent = current.scalar(select(Run).where(Run.executor_type == "agent_workflow"))
            request_cancel(current, parent)
            current.commit()
        try:
            yield "never"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    assert closed
    parent = api.get("/api/runs/" + queued["id"]).json()
    report = workflow_step(api, queued["id"], "report")
    assert parent["status"] == "succeeded"
    assert report["status"] == "canceled"


def test_failed_context_step_fails_the_report_without_inference(monkeypatch):
    from app.runner_client import RunnerClient

    monkeypatch.setattr(
        LocalChatProvider, "stream", lambda self, **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    monkeypatch.setattr(
        RunnerClient, "hardware", lambda self: (_ for _ in ()).throw(RuntimeError("host down"))
    )
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    assert workflow_step(api, queued["id"], "system_snapshot")["status"] == "failed"
    assert workflow_step(api, queued["id"], "report")["status"] == "failed"
    assert "PrerequisiteFailed" in workflow_step(api, queued["id"], "report")["error_type"]


def test_invented_workflow_step_fails_closed_without_children(monkeypatch):
    monkeypatch.setattr(
        LocalChatProvider, "stream", lambda self, **kwargs: (_ for _ in ()).throw(AssertionError())
    )
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.parameters = {**run.parameters, "steps": [{"key": "shell", "gate": "none"}]}
        session.commit()
        drain(session)
    parent = api.get("/api/runs/" + queued["id"]).json()
    assert parent["status"] == "failed"
    assert parent["workflow"]["steps"] == []
    assert "invented" in parent["error_message"].lower() or "unauthorized" in parent["error_message"].lower()
    with session_factory()() as session:
        children = list(session.scalars(select(Run).where(Run.parent_run_id == queued["id"])))
        assert children == []


def test_workflow_mode_is_reviewable_and_rejected_when_unknown():
    api = TestClient(app)
    agent = create(api, workflow_mode="gated")
    assert agent["workflow_mode"] == "gated" and agent["enabled"] is False
    rejected = api.post(
        "/api/agents",
        json={"name": "Bad", "goal": "Report", "model": "fake-local", "workflow_mode": "parallel"},
    )
    assert rejected.status_code == 422
