import json
from datetime import timedelta

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select


def target(client):
    result = client.post(
        "/api/connectors",
        json={"kind": "github", "name": "Our repository", "key": "our-repo", "repository": "owner/repo"},
    )
    assert result.status_code == 201, result.text
    return {"connector_id": result.json()["id"], "repository": "owner/repo"}


def create(client, scope, **extra):
    result = client.post(
        "/api/agents",
        json={
            "name": "Repository report",
            "goal": "Summarize open issues",
            "model": "fake-local",
            "tools": ["github_read", "remember_report"],
            "github": scope,
            **extra,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def fake(monkeypatch):
    sent = []
    reports = {}
    received = []

    def request(self, method, path, payload=None):
        if path == "/v1/runs/github-read":
            assert set(payload["permissions"]) == {"github_read", "network_read"}
            sent.append(payload)
            reports[payload["run_id"]] = {
                "run_id": payload["run_id"],
                "repository": payload["repository"],
                "captured_at": utcnow().isoformat(),
                "project": {
                    "name": payload["repository"],
                    "url": "https://github.com/" + payload["repository"],
                },
                "issues": [
                    {
                        "number": i + 1,
                        "title": "Add search " + ("x" * 200),
                        "url": f"https://github.com/{payload['repository']}/issues/{i + 1}",
                    }
                    for i in range(30)
                ],
                "pull_requests": [],
            }
            return {
                "pid": 12,
                "process_group_id": 12,
                "stdout_log": "runs/a/out",
                "stderr_log": "runs/a/err",
                "runner_id": "fake",
            }
        if method == "GET" and path.startswith("/v1/process/"):
            return {
                "alive": False,
                "status": "exited",
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
        if path.endswith("/report"):
            return reports[path.split("/")[-2]]
        raise AssertionError((method, path))

    async def complete(self, **kwargs):
        received.append(kwargs["messages"])
        yield "Repository owner/repo needs search improvements."

    monkeypatch.setattr(RunnerClient, "request", request)
    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    return sent, received


def drain():
    with session_factory()() as session:
        for _ in range(20):
            if tick(session, "agent-github-test") is None:
                return
    raise AssertionError("Queue did not drain")


def launch(client, agent):
    r = client.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert r.status_code == 202, r.text
    return r.json()


def test_reviewed_scope_persists_and_workflow_reports_bounded_local_context(monkeypatch):
    sent, received = fake(monkeypatch)
    with TestClient(app) as client:
        scope = target(client)
        agent = create(client, scope, enabled=True)
        reset_engine()
        assert client.get("/api/agents/" + agent["id"]).json()["github"] == scope
        parent = launch(client, agent)
        drain()
        view = client.get("/api/runs/" + parent["id"]).json()
        steps = view["workflow"]["steps"]
        assert [x["key"] for x in steps] == ["github_read", "report"]
        assert all(x["status"] == "succeeded" for x in steps), steps
        child = client.get("/api/runs/" + steps[0]["run_id"]).json()
        assert child["execution_target"] == "host" and set(child["effective_permissions"]) == {
            "github_read",
            "network_read",
        }
        assert len(child["metadata"]["github_snapshot"]["issues"]) == 30
        report = client.get("/api/runs/" + steps[1]["run_id"]).json()
        context = report["parameters"]["tool_context"][0]["result"]
        assert (
            len(context["issues"]) == 10
            and context["listed_counts"]["issues"] == 30
            and context["context_excerpted"]
        )
        assert max(map(lambda x: len(x["title"]), context["issues"])) == 180
        assert sent and received and "owner/repo" in json.dumps(received)
        connector = client.get("/api/connectors/" + scope["connector_id"]).json()
        assert connector["last_run_id"] == child["id"] and connector["status"] == "ready"


def test_activation_requires_reviewed_target_and_runtime_budget():
    with TestClient(app) as client:
        scope = target(client)
        for extra in (
            {"github": None},
            {"maximum_runtime": 69},
            {"github": {**scope, "repository": "other/repo"}},
        ):
            body = {
                "name": "Report",
                "goal": "Read repo",
                "model": "fake-local",
                "tools": ["github_read"],
                "github": scope,
                "enabled": True,
                **extra,
            }
            assert client.post("/api/agents", json=body).status_code == 422
        with session_factory()() as session:
            assert list(session.scalars(select(Run))) == []


@pytest.mark.parametrize("change", ["retarget", "disconnect", "disable"])
def test_changed_connector_never_redirects_scheduled_work(monkeypatch, change):
    sent, received = fake(monkeypatch)
    with TestClient(app) as client:
        scope = target(client)
        agent = create(client, scope, enabled=True)
        parent = launch(client, agent)
        if change == "retarget":
            assert (
                client.patch(
                    "/api/connectors/" + scope["connector_id"], json={"repository": "other/repo"}
                ).status_code
                == 200
            )
        elif change == "disable":
            assert (
                client.patch("/api/connectors/" + scope["connector_id"], json={"enabled": False}).status_code
                == 200
            )
        else:
            assert client.delete("/api/connectors/" + scope["connector_id"]).status_code == 204
        drain()
        assert client.get("/api/runs/" + parent["id"]).json()["status"] == "failed"
        assert sent == [] and received == []


def test_expired_agent_budget_does_not_start_native_read(monkeypatch):
    sent, received = fake(monkeypatch)
    with TestClient(app) as client:
        scope = target(client)
        agent = create(client, scope, enabled=True)
        parent = launch(client, agent)
        with session_factory()() as session:
            tick(session, "agent-github-test")
            child = session.scalar(
                select(Run).where(Run.parent_run_id == parent["id"], Run.executor_type == "github_read")
            )
            child.parameters = {
                **child.parameters,
                "deadline_at": (utcnow() + timedelta(seconds=20)).isoformat(),
            }
            session.commit()
        drain()
        assert sent == [] and received == []


def test_factory_requires_target_review_before_enable():
    with TestClient(app) as client:
        r = client.post(
            "/api/agents/draft",
            json={
                "instruction": "Every morning check GitHub open issues and pull requests",
                "model": "fake-local",
            },
        )
        assert r.status_code == 201, r.text
        draft = r.json()
        assert not draft["enabled"] and draft["tools"] == ["github_read"] and draft["github"] is None
        r = client.post(
            f"/api/agents/{draft['id']}/enabled",
            json={"enabled": True, "expected_updated_at": draft["updated_at"]},
        )
        assert r.status_code == 422


def test_scope_migration_preserves_existing_agent_definitions():
    from alembic import command
    from app.db import alembic_config
    from sqlalchemy import text

    with TestClient(app) as client:
        row = client.post(
            "/api/agents",
            json={"name": "Existing definition", "goal": "Keep original intent", "model": "fake-local"},
        ).json()
    reset_engine()
    command.downgrade(alembic_config(), "0022")
    command.upgrade(alembic_config(), "head")
    with session_factory()() as session:
        old = session.execute(
            text("select name,goal,github from agents where id=:id"), {"id": row["id"]}
        ).one()
        assert old == ("Existing definition", "Keep original intent", None)
