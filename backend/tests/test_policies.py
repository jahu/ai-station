from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Notice
from fastapi.testclient import TestClient
from sqlalchemy import select


def drain(session, worker="policy-test", limit=30):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def create(api, **extra):
    result = api.post(
        "/api/agents",
        json={"name": "Policy", "goal": "Summarize available context", "model": "fake-local", **extra},
    )
    assert result.status_code == 201, result.text
    return result.json()


def run_now(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def test_legacy_agents_keep_silent_policies_and_reject_auto_retry():
    api = TestClient(app)
    agent = create(api)
    assert agent["retry_policy"] == {"mode": "none"}
    assert agent["notification_policy"] == {
        "on_success": False,
        "on_failure": False,
        "on_approval": False,
    }
    rejected = api.post(
        "/api/agents",
        json={
            "name": "Bad",
            "goal": "Report",
            "model": "fake-local",
            "retry_policy": {"mode": "auto"},
        },
    )
    assert rejected.status_code == 422


def test_manual_retry_creates_a_new_workflow_without_replaying_the_failed_run(monkeypatch):
    async def fail(self, **kwargs):
        raise RuntimeError("provider down")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    agent = create(api, enabled=True, retry_policy={"mode": "manual"})
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    parent = api.get("/api/runs/" + queued["id"]).json()
    assert parent["retry"]["allowed"] is True
    report = next(step for step in parent["workflow"]["steps"] if step["key"] == "report")
    assert api.get("/api/runs/" + report["run_id"]).json()["status"] == "failed"
    denied = api.post(f"/api/runs/{report['run_id']}/retry-workflow")
    assert denied.status_code == 409
    none_agent = create(api, name="Silent", enabled=True)
    silent = run_now(api, none_agent)
    with session_factory()() as session:
        drain(session)
    assert api.post(f"/api/runs/{silent['id']}/retry-workflow").status_code == 409
    created = api.post(f"/api/runs/{queued['id']}/retry-workflow")
    assert created.status_code == 202
    body = created.json()
    assert body["id"] != queued["id"]
    assert body["parent_run_id"] is None
    assert body["triggered_by"] == "retry"
    assert body["retry"]["retry_of"] == queued["id"]
    assert body["parameters"]["definition"]["retry_policy"] == {"mode": "manual"}
    original = api.get("/api/runs/" + queued["id"]).json()
    assert original["retry"]["retry_run_id"] == body["id"]
    assert original["retry"]["allowed"] is False
    assert all(step["run_id"] != body["id"] for step in original["workflow"]["steps"])
    assert api.post(f"/api/runs/{queued['id']}/retry-workflow").status_code == 409


def test_failure_notice_is_opt_in_and_can_be_marked_read(monkeypatch):
    async def fail(self, **kwargs):
        raise RuntimeError("provider down")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    silent = create(api, name="Quiet", enabled=True, notification_policy={"on_failure": False})
    loud = create(
        api,
        name="Loud",
        enabled=True,
        notification_policy={"on_failure": True, "on_success": False, "on_approval": False},
    )
    run_now(api, silent)
    run_now(api, loud)
    with session_factory()() as session:
        drain(session)
        notices = list(session.scalars(select(Notice)))
        assert len(notices) == 1
        assert notices[0].agent_id == loud["id"]
        assert notices[0].kind == "failed"
    listed = api.get("/api/notices?unread=true").json()
    assert len(listed) == 1
    read = api.post(f"/api/notices/{listed[0]['id']}/read", json={"read": True})
    assert read.status_code == 200 and read.json()["read_at"]
    dashboard = api.get("/api/dashboard").json()
    assert dashboard["unread_notice_count"] == 0
    assert dashboard["notices"] == []


def test_failure_notice_exposes_manual_retry_of_the_parent_workflow(monkeypatch):
    async def fail(self, **kwargs):
        raise RuntimeError("provider down")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    agent = create(
        api,
        enabled=True,
        retry_policy={"mode": "manual"},
        notification_policy={"on_failure": True, "on_success": False, "on_approval": False},
    )
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    dashboard = api.get("/api/dashboard").json()
    assert dashboard["unread_notice_count"] == 1
    notice = dashboard["notices"][0]
    assert notice["kind"] == "failed"
    assert "project_id" in notice
    assert notice["run_id"] != queued["id"]
    assert notice["retry"] == {"allowed": True, "run_id": queued["id"]}
    created = api.post(f"/api/runs/{notice['retry']['run_id']}/retry-workflow")
    assert created.status_code == 202, created.text
    assert created.json()["retry"]["retry_of"] == queued["id"]
    listed = api.get("/api/notices?unread=true").json()
    assert listed[0]["retry"]["allowed"] is False
    assert listed[0]["retry"]["run_id"] == queued["id"]


def test_success_notice_is_opt_in_and_skips_the_parent_publish(monkeypatch):
    async def complete(self, **kwargs):
        yield "Policy report"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    silent = create(api, name="QuietSuccess", enabled=True)
    loud = create(
        api,
        name="LoudSuccess",
        enabled=True,
        notification_policy={"on_success": True, "on_failure": False, "on_approval": False},
    )
    run_now(api, silent)
    queued = run_now(api, loud)
    with session_factory()() as session:
        drain(session)
        notices = list(session.scalars(select(Notice)))
        assert len(notices) == 1
        assert notices[0].agent_id == loud["id"]
        assert notices[0].kind == "succeeded"
    parent = api.get("/api/runs/" + queued["id"]).json()
    report = next(step for step in parent["workflow"]["steps"] if step["key"] == "report")
    assert api.get("/api/notices?unread=true").json()[0]["run_id"] == report["run_id"]
