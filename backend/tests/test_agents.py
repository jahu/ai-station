import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.memory import upsert_memory
from app.models import Agent, Run
from app.providers import ProviderError
from app.runs import request_cancel
from app.schedule import scheduler_tick
from fastapi.testclient import TestClient
from sqlalchemy import select


def create(api, **extra):
    result = api.post(
        "/api/agents",
        json={"name": "Status report", "goal": "Summarize available context", "model": "fake-local", **extra},
    )
    assert result.status_code == 201, result.text
    return result.json()


def run_now(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def test_factory_disabled_activation_and_unsupported_tools():
    api = TestClient(app)
    draft = api.post(
        "/api/agents/draft",
        json={"instruction": "Every morning check GPU workstation status", "model": "fake-local"},
    ).json()
    assert draft["enabled"] is False and draft["next_run_at"] is None
    assert draft["trigger"] == "cron" and draft["cron_expr"] == "0 8 * * *"
    assert draft["tools"] == ["system_snapshot"]
    assert (
        api.post(
            f"/api/agents/{draft['id']}/run", json={"expected_updated_at": draft["updated_at"]}
        ).status_code
        == 409
    )
    enabled = api.post(
        f"/api/agents/{draft['id']}/enabled",
        json={"enabled": True, "expected_updated_at": draft["updated_at"]},
    )
    assert enabled.status_code == 200 and enabled.json()["next_run_at"]
    web = api.post(
        "/api/agents/draft", json={"instruction": "Every day search the web for news", "model": "fake-local"}
    ).json()
    result = api.post(
        f"/api/agents/{web['id']}/enabled", json={"enabled": True, "expected_updated_at": web["updated_at"]}
    )
    assert result.status_code == 422 and "web_search" in result.text
    assert api.get(f"/api/agents/{web['id']}").json()["enabled"] is False


def test_local_agent_context_artifact_status_and_restart(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs)
        yield "A factual "
        yield "**local report**."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"])
    other = create(api, name="Another agent")
    with session_factory()() as session:
        upsert_memory(session, scope="agent", scope_id=agent["id"], content="Relevant observation")
        upsert_memory(session, scope="agent", scope_id=other["id"], content="PRIVATE OTHER AGENT")
        session.commit()
    queued = run_now(api, agent)
    with session_factory()() as session:
        tick(session, "agent-test")
    run = api.get("/api/runs/" + queued["id"]).json()
    assert run["status"] == "succeeded"
    assert "Relevant observation" in str(received[0]["messages"])
    assert "PRIVATE OTHER AGENT" not in str(received[0]["messages"])
    assert run["effective_permissions"] == []
    assert run["parameters"]["tool_context"][0]["tool"] == "memory_search"
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert artifact["type"] == "markdown" and artifact["metadata"]["partial"] is False
    reset_engine()
    saved = api.get("/api/agents/" + agent["id"]).json()
    assert saved["last_status"] == "succeeded" and saved["failure_count"] == 0
    assert saved["runs"][0]["id"] == queued["id"]


def test_failure_is_not_reported_as_success(monkeypatch):
    async def fail(self, **kwargs):
        yield "Partial observation"
        raise ProviderError("Unavailable provider")

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        tick(session, "agent-test")
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"
    assert api.get("/api/agents/" + agent["id"]).json()["failure_count"] == 1
    assert api.get("/api/artifacts?run_id=" + queued["id"]).json()[0]["metadata"]["partial"] is True


def test_silent_generation_cancels_and_closes_stream(monkeypatch):
    closed = []

    async def silent(self, **kwargs):
        with session_factory()() as current:
            run = current.scalar(select(Run).where(Run.executor_type == "agent"))
            request_cancel(current, run)
            current.commit()
        try:
            await asyncio.sleep(30)
            yield "never"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        tick(session, "agent-test")
    assert closed
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
    assert api.get("/api/agents/" + agent["id"]).json()["last_status"] == "canceled"


def test_schedule_claims_are_atomic_and_non_overlapping():
    api = TestClient(app)
    agent = create(api, enabled=True, trigger="interval", interval_seconds=60)
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.next_run_at = utcnow() - timedelta(hours=1)
        session.commit()
    barrier = Barrier(2)

    def schedule():
        barrier.wait()
        with session_factory()() as session:
            result = scheduler_tick(session)
            session.commit()
            return result

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: schedule(), range(2)))
    assert sum(len(result) for result in results) == 1
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert scheduler_tick(session) == []
        assert row.next_run_at > utcnow()
        session.commit()
    assert (
        api.post(
            f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
        ).status_code
        == 409
    )
    paused = api.post(
        f"/api/agents/{agent['id']}/enabled",
        json={"expected_updated_at": agent["updated_at"], "enabled": False},
    )
    assert paused.status_code == 200 and paused.json()["next_run_at"] is None
    assert api.get("/api/agents/" + agent["id"]).json()["runs"][0]["status"] == "queued"


def test_one_shot_and_duplicate_never_auto_reactivate():
    api = TestClient(app)
    future = utcnow() + timedelta(minutes=5)
    agent = create(api, enabled=True, trigger="datetime", run_at=future.isoformat())
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.run_at = row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert len(scheduler_tick(session)) == 1
        session.commit()
        assert scheduler_tick(session) == []
    row = api.get("/api/agents/" + agent["id"]).json()
    assert row["enabled"] is False and row["next_run_at"] is None
    copy = api.post(
        f"/api/agents/{agent['id']}/duplicate", json={"expected_updated_at": row["updated_at"]}
    ).json()
    assert copy["enabled"] is False and copy["last_run_at"] is None and copy["next_run_at"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"provider": "external"},
        {"tools": ["shell"]},
        {"skills": ["unimplemented"]},
        {"trigger": "interval"},
        {"cron_expr": "* * * * *"},
        {"trigger": "cron", "cron_expr": "* * * * * *"},
        {"trigger": "datetime", "run_at": "2026-01-01T00:00:00"},
        {"permission_profile": "coding_external"},
        {"enabled": True, "model": ""},
        {"execution_target": "host"},
    ],
)
def test_agent_definition_rejects_unimplemented_or_unsafe_fields(extra):
    response = TestClient(app).post("/api/agents", json={"name": "Test", "goal": "Report", **extra})
    assert response.status_code == 422


def test_long_factory_draft_is_valid_and_stale_edits_are_rejected():
    from app.agent_schema import AgentSettings

    api = TestClient(app)
    draft = api.post("/api/agents/draft", json={"instruction": "A" * 16000, "model": "fake"}).json()
    settings = {key: draft[key] for key in AgentSettings.model_fields}
    AgentSettings.model_validate(settings)
    saved = api.put(
        f"/api/agents/{draft['id']}",
        json={**settings, "name": "Changed", "expected_updated_at": draft["updated_at"]},
    )
    assert saved.status_code == 200
    stale = api.put(
        f"/api/agents/{draft['id']}",
        json={**settings, "name": "Stale", "expected_updated_at": draft["updated_at"]},
    )
    assert stale.status_code == 409
    assert api.get(f"/api/agents/{draft['id']}").json()["name"] == "Changed"


def test_tool_permissions_enforced_before_host_access(monkeypatch):
    from app.runner_client import RunnerClient

    called = []
    monkeypatch.setattr(RunnerClient, "hardware", lambda self: called.append(True))
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot"])
    queued = run_now(api, agent)
    assert queued["effective_permissions"] == ["filesystem_read"]
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.effective_permissions = []
        session.commit()
        tick(session, "agent-test")
    assert not called
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"
