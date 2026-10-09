from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Approval, Run
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


def _create(api, **extra):
    result = api.post(
        "/api/agents",
        json={
            "name": "Guarded",
            "goal": "Summarize available context",
            "model": "fake-local",
            "require_approval": True,
            "enabled": True,
            **extra,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_required_approval_parks_the_run_until_granted(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs)
        yield "Approved report."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = _create(api)
    queued = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert queued.status_code == 202, queued.text
    parked = queued.json()
    assert parked["status"] == "waiting_for_approval"
    assert parked["approval"]["resolution"] == "pending"
    assert parked["approval"]["action"] == "agent.execute"
    with session_factory()() as session:
        assert tick(session, "approval-test") is None
    still = api.get("/api/runs/" + parked["id"]).json()
    assert still["status"] == "waiting_for_approval"
    assert received == []
    granted = api.post(f"/api/runs/{parked['id']}/approval", json={"resolution": "granted"})
    assert granted.status_code == 200
    assert granted.json()["status"] == "queued"
    assert granted.json()["approval"]["resolution"] == "granted"
    with session_factory()() as session:
        tick(session, "approval-test")
    done = api.get("/api/runs/" + parked["id"]).json()
    assert done["status"] == "succeeded"
    assert received
    assert api.get("/api/agents/" + agent["id"]).json()["last_status"] == "succeeded"


def test_denied_or_canceled_approval_never_runs(monkeypatch):
    async def complete(self, **kwargs):
        yield "should not run"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = _create(api)
    first = api.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
    ).json()
    denied = api.post(f"/api/runs/{first['id']}/approval", json={"resolution": "denied"})
    assert denied.status_code == 200
    assert denied.json()["status"] == "canceled"
    assert denied.json()["approval"]["resolution"] == "denied"
    with session_factory()() as session:
        assert tick(session, "approval-test") is None
    agent = api.get("/api/agents/" + agent["id"]).json()
    assert agent["last_status"] == "canceled" and agent["failure_count"] == 0
    second = api.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
    ).json()
    canceled = api.post(f"/api/runs/{second['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["approval"]["resolution"] == "canceled"
    with session_factory()() as session:
        pending = list(session.scalars(select(Approval).where(Approval.resolution == "pending")))
        assert pending == []
        assert session.get(Run, second["id"]).status == RunStatus.CANCELED.value


def test_existing_agents_still_run_without_approval(monkeypatch):
    async def complete(self, **kwargs):
        yield "Immediate report."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = api.post(
        "/api/agents",
        json={"name": "Open", "goal": "Summarize available context", "model": "fake-local", "enabled": True},
    ).json()
    assert agent["require_approval"] is False
    queued = api.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
    ).json()
    assert queued["status"] == "queued" and queued.get("approval") is None
    with session_factory()() as session:
        tick(session, "approval-test")
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "succeeded"
