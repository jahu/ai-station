"""Main-conversation selected documents reuse the deployed offline data workflow."""

import json

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.models import Agent, Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_documents import upload_document
from test_conversation_data import drain
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_selected_document_analysis_is_one_conversation_task_without_a_persistent_agent(
    data_environment, mode
):
    api = TestClient(app)
    artifact = upload_document(api, b"Observed values: 12 and 15.", "observations.md")
    cid = api.post(
        "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": mode}
    ).json()["id"]
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Calculate the total from the selected document.",
            "data": {"documents": {"artifact_ids": [artifact["id"]]}, "model": data_environment["model"]},
            "web_search": {"enabled": True},
        },
    )
    assert response.status_code == 202, response.text
    root = response.json()
    drain()
    messages = api.get(f"/api/chat/conversations/{cid}").json()["messages"]
    assert messages[-1]["task_status"] == "succeeded", messages[-1]
    with session_factory()() as s:
        assert not list(s.scalars(select(Agent)))
        rows = list(s.scalars(select(Run).where(Run.task_id == root["task_id"])))
        assert all(r.agent_id is None and r.conversation_id == cid for r in rows)
        source = next(r for r in rows if r.parameters.get("tool") == "read_documents")
        assert source.effective_permissions == ["filesystem_read"]
        python = next(r for r in rows if r.executor_type == "python")
        captured = s.get(Artifact, python.parameters["inputs"][0]["artifact_id"])
        data = json.loads((get_settings().data_dir / captured.relative_path).read_bytes())
        assert data["observations"][0]["result"]["documents"][0]["text"] == "Observed values: 12 and 15."
        assert (
            s.get(Run, root["id"]).parameters["data"]["documents"]["snapshots"][0]["artifact_id"]
            == artifact["id"]
        )
        assert "external_ai" not in python.effective_permissions
    assert data_environment["calls"] == 1


def document_turn(api, state):
    artifact = upload_document(api, b"Observed values: 12 and 15.", "observations.md")
    cid = api.post(
        "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": "chat"}
    ).json()["id"]
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Calculate the total from the selected document.",
            "data": {"documents": {"artifact_ids": [artifact["id"]]}, "model": state["model"]},
        },
    )
    assert response.status_code == 202, response.text
    return artifact, cid, response.json()


def test_document_followup_reuses_captured_data_without_renewing_document_access(data_environment):
    from app.db import utcnow
    from test_conversation_data_reference import follow

    api = TestClient(app)
    artifact, cid, first = document_turn(api, data_environment)
    drain()
    with session_factory()() as s:
        s.get(Artifact, artifact["id"]).trashed_at = utcnow()
        s.commit()
    response = follow(api, cid)
    assert response.status_code == 202, response.text
    second = response.json()
    assert "documents" not in second["parameters"]["data"]
    assert "research" not in second["parameters"]["data"]
    assert len(second["parameters"]["data"]["input_artifact_ids"]) == 1
    assert second["parameters"]["data_reference"]["run_id"] == first["id"]
    drain()
    assert api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["task_status"] == "succeeded"
    assert len(data_environment["jobs"]) == 2


@pytest.mark.parametrize("change", ["bytes", "message", "stop"])
def test_document_turn_rejects_changed_scope_and_stop_before_any_workspace(data_environment, change):
    from app.models import Message, Project

    api = TestClient(app)
    artifact, _, root = document_turn(api, data_environment)
    with session_factory()() as s:
        if change == "bytes":
            (get_settings().data_dir / artifact["relative_path"]).write_bytes(b"changed source")
        elif change == "message":
            saved = s.get(Run, root["id"])
            user = s.get(Message, saved.parameters["user_message_id"])
            user.metadata_json = {**user.metadata_json, "data_scope": {}}
            s.commit()
        else:
            response = api.post("/api/runs/" + root["id"] + "/cancel")
            assert response.status_code == 200
        before = list(s.scalars(select(Project.id)))
    drain()
    with session_factory()() as s:
        saved = s.get(Run, root["id"])
        assert saved.status in {"failed", "canceled"}, (saved.status, saved.error_message)
        assert list(s.scalars(select(Project.id))) == before
    assert not data_environment["jobs"] and data_environment["calls"] == 0


def test_legacy_data_scope_identity_and_document_creation_exclusion():
    from uuid import uuid4

    from app.conversation_data_schema import DataScope
    from pydantic import ValidationError

    legacy = DataScope(input_artifact_ids=[uuid4()]).model_dump(mode="json")
    assert "documents" not in legacy and "research" not in legacy and "operation" not in legacy
    with pytest.raises(ValidationError, match="choose analysis"):
        DataScope(operation="create", documents={"artifact_ids": [uuid4()]})
    with pytest.raises(ValidationError):
        DataScope(input_artifact_ids=[uuid4() for _ in range(8)], documents={"artifact_ids": [uuid4()]})


def test_documents_and_reviewed_public_pages_keep_separate_source_permissions(data_environment, monkeypatch):
    fetched = []

    async def page(url, **kwargs):
        fetched.append(url)
        return {
            "url": url,
            "status": 200,
            "text": "Reviewed public value 4",
            "links": [],
            "truncated": False,
            "untrusted": True,
            "content_type": "text/html",
        }

    monkeypatch.setattr("app.http_fetch.fetch_public", page)
    api = TestClient(app)
    artifact = upload_document(api)
    cid = api.post(
        "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": "chat"}
    ).json()["id"]
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Compare the reviewed sources.",
            "data": {
                "model": data_environment["model"],
                "documents": {"artifact_ids": [artifact["id"]]},
                "research": {"fetch_urls": ["https://example.com/"]},
            },
        },
    )
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as s:
        rows = list(s.scalars(select(Run).where(Run.task_id == response.json()["task_id"])))
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert next(
            r for r in rows if r.parameters.get("tool") == "read_documents"
        ).effective_permissions == ["filesystem_read"]
        assert next(r for r in rows if r.parameters.get("tool") == "http_fetch").effective_permissions == [
            "network_read"
        ]
    assert fetched == ["https://example.com/"]
