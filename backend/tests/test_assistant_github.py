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
