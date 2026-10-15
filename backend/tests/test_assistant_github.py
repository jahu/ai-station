from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select


def setup(client, mode="work"):
    cid = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": mode}).json()["id"]
    row = client.post(
        "/api/connectors",
        json={
            "kind": "github",
            "key": "our-repository",
            "name": "Our repository",
            "repository": "owner/repo",
        },
    ).json()
    return cid, row, {"connector_id": row["id"], "expected_updated_at": row["updated_at"]}


def work():
    with session_factory()() as session:
        tick(session, "assistant-gh-test")


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_selected_github_scope_uses_same_task_without_contacting_ai(monkeypatch, mode):
    async def never(*args, **kwargs):
        raise AssertionError("GitHub account data must not reach any AI provider")
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", never)
    with TestClient(app) as client:
        cid, row, scope = setup(client, mode)
        body = {
            "client_request_id": str(uuid4()),
            "conversation_id": cid,
            "expected_settings_version": 1,
            "content": "Show open issues and pull requests",
            "github": scope,
        }
        receipt = client.post("/api/chat/turns", json=body)
        assert receipt.status_code == 202, receipt.text
        parent = receipt.json()["run"]
        work()
        with session_factory()() as session:
            child = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
            assert child and child.executor_type == "github_read"
            assert child.task_id == parent["task_id"] and child.conversation_id == cid
            assert child.parameters["repository"] == "owner/repo"
            assert set(child.effective_permissions) == {"github_read", "network_read"}
            assert "external_ai" not in child.effective_permissions
        assert client.post("/api/chat/turns", json=body).json()["run"]["id"] == parent["id"]


@pytest.mark.parametrize(
    "extra",
    [
        {"action": "github.inspect", "github": None},
        {"action": "image.generate"},
        {"image_artifact_ids": [str(uuid4())]},
        {"web_search": {"enabled": True, "query": "private repo"}},
        {"attachments": [{"name": "secret.txt", "content": "private"}]},
    ],
)
def test_mixed_or_missing_github_scope_never_dispatches(extra):
    with TestClient(app) as client:
        cid, _, scope = setup(client)
        r = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Read repo", "github": scope, **extra}
        )
        assert r.status_code == 422, r.text
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []
        with session_factory()() as session:
            assert list(session.scalars(select(Run))) == []


def test_stale_and_disabled_scope_rejected_before_persistence():
    with TestClient(app) as client:
        cid, row, scope = setup(client)
        client.patch("/api/connectors/" + row["id"], json={"name": "Changed"})
        r = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Read repo", "github": scope}
        )
        assert r.status_code == 409, r.text
        fresh = client.get("/api/connectors/" + row["id"]).json()
        scope["expected_updated_at"] = fresh["updated_at"]
        client.patch("/api/connectors/" + row["id"], json={"enabled": False})
        r = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Read repo", "github": scope}
        )
        assert r.status_code == 422, r.text
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


def test_connector_change_while_queued_never_dispatches_to_new_repository():
    with TestClient(app) as client:
        cid, row, scope = setup(client)
        parent = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Read repo", "github": scope}
        ).json()
        client.patch("/api/connectors/" + row["id"], json={"repository": "other/repo"})
        work()
        detail = client.get(f"/api/chat/conversations/{cid}").json()
        assert "changed" in detail["messages"][-1]["content"]
        with session_factory()() as session:
            assert session.scalar(select(Run).where(Run.parent_run_id == parent["id"])) is None


def test_selected_github_scope_is_not_replaced_by_an_image_reference():
    with TestClient(app) as client:
        cid, _, scope = setup(client)
        response = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Upscale it", "github": scope}
        )
        assert response.status_code == 202, response.text
        assert response.json()["parameters"]["image_artifact_ids"] == []
        work()
        with session_factory()() as session:
            child = session.scalar(select(Run).where(Run.parent_run_id == response.json()["id"]))
            assert child.executor_type == "github_read"


def test_model_plan_cannot_grant_github_access(monkeypatch):
    async def stream(self, **params):
        yield '{"action":"github.inspect","reason":"Read account"}'

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        cid, _, _ = setup(client)
        response = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "What is new?"})
        assert response.status_code == 202
        work()
        view = client.get(f"/api/chat/conversations/{cid}").json()
        assert "Choose a GitHub repository" in view["messages"][-1]["content"]
        with session_factory()() as session:
            runs = list(session.scalars(select(Run)))
            assert len(runs) == 1 and "github_read" not in runs[0].effective_permissions


def test_task_stop_cancels_queued_read_without_gh_dispatch():
    with TestClient(app) as client:
        cid, _, scope = setup(client)
        parent = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Read repo", "github": scope}
        ).json()
        work()
        response = client.post(f"/api/chat/conversations/{cid}/tasks/{parent['task_id']}/cancel")
        assert response.status_code == 200, response.text
        with session_factory()() as session:
            child = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
            assert child.status == "canceled" and not child.metadata_json.get("dispatch_attempted")
