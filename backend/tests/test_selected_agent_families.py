"""The local factory maps selected-document intent to reviewed existing families."""

import json

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, Run, Worktree
from app.selected_data_agent import SelectedProposal, allowed_families, definition, freeze
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_documents import upload_document
from test_conversation_data import drain
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment
from test_selected_data_agent import proposal, send, setup


def document_source(api, state, *, model="auto"):
    document = upload_document(
        api, b"WillowBrief: build a simple accessible calculator page.", "requirements.txt"
    )
    cid, scope = setup(api, state, scope={"model": model, "documents": {"artifact_ids": [document["id"]]}})
    return cid, scope, document


@pytest.mark.parametrize("family", ["data", "report", "code"])
def test_document_draft_maps_only_allowed_family_and_keeps_selected_scope(
    data_environment, monkeypatch, family
):
    api = TestClient(app)
    cid, scope, doc = document_source(api, data_environment)

    async def stream(self, **kwargs):
        prompt = json.loads(kwargs["messages"][1]["content"])
        assert prompt["allowed_families"] == ["data", "report", "code"]
        assert prompt["source_readers"] == ["read_documents"]
        assert "tools" not in prompt["proposal_schema"]["properties"]
        yield json.dumps({**proposal(), "family": family})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    accepted = send(api, cid, scope)
    assert accepted.status_code == 202, accepted.text
    drain()
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        assert agent, [(r.executor_type, r.status, r.error_message) for r in db.scalars(select(Run))]
        assert not agent.enabled and agent.project_id is None and agent.next_run_at is None
        assert agent.documents["artifact_ids"] == [doc["id"]]
        assert agent.tools == (
            ["python_data", "read_documents"]
            if family == "data"
            else ["coding_local", "read_documents"]
            if family == "code"
            else ["read_documents"]
        )
        assert agent.model == ("draft-local" if family == "report" else "auto")
        assert (agent.data is None) == (family != "data")
        assert agent.workspace_policy == {
            "auto_install_dependencies": family == "code",
            "auto_validate": family == "code",
        }
        draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert set(draft.effective_permissions) == {"manage_agents", "filesystem_read"}
        assert draft.metadata_json["selected_data_family"] == family
        artifact = db.get(Artifact, draft.metadata_json["definition_artifact_id"])
        assert artifact.parent_artifact_ids == [doc["id"]]
        assert not list(db.scalars(select(Worktree)))
    messages = api.get("/api/chat/conversations/" + cid).json()["messages"]
    assert next(m for m in messages if m["role"] == "assistant")["metadata"]["selected_data_family"] == family
    assert not data_environment["jobs"]


def test_report_executes_from_document_without_python_or_workspace(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope, _ = document_source(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        if kwargs.get("json_output"):
            yield json.dumps({**proposal(), "family": "report", "goal": "Summarize the selected brief."})
        else:
            assert "WillowBrief" in json.dumps(kwargs["messages"])
            yield "WillowBrief asks for an accessible calculator page."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        aid = db.scalar(select(Agent)).id
    saved = api.get("/api/agents/" + aid).json()
    enabled = api.post(
        "/api/agents/" + aid + "/enabled", json={"enabled": True, "expected_updated_at": saved["updated_at"]}
    )
    assert enabled.status_code == 200, enabled.text
    queued = api.post(
        "/api/agents/" + aid + "/run", json={"expected_updated_at": enabled.json()["updated_at"]}
    )
    assert queued.status_code == 202, queued.text
    drain()
    with session_factory()() as db:
        runs = list(db.scalars(select(Run).where(Run.task_id == queued.json()["task_id"])))
        assert all(r.status == "succeeded" for r in runs), [
            (r.executor_type, r.status, r.error_message) for r in runs
        ]
        assert not any(
            r.executor_type in {"python", "project_setup", "worktree_prepare", "agent_data_generate"}
            for r in runs
        )
        report = next(r for r in runs if r.executor_type == "agent")
        artifacts = list(
            db.scalars(
                select(Artifact).where(Artifact.run_id == report.id, Artifact.artifact_type == "markdown")
            )
        )
        assert len(artifacts) == 1
        artifact_id = artifacts[0].id
        assert not list(db.scalars(select(Worktree)))
        assert all(r.project_id is None for r in runs)
    assert (
        "WillowBrief asks for an accessible calculator page."
        in api.get("/api/artifacts/" + artifact_id + "/file").text
    )
    assert len(calls) == 2 and not data_environment["jobs"]


@pytest.mark.parametrize("family", ["report", "code"])
def test_data_files_cannot_gain_an_unreviewed_different_family(data_environment, monkeypatch, family):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        assert json.loads(kwargs["messages"][1]["content"])["allowed_families"] == ["data"]
        yield json.dumps({**proposal(), **({"family": family} if len(calls) == 1 else {})})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        assert (
            agent
            and agent.tools == ["python_data"]
            and agent.data["input_artifact_ids"] == scope["input_artifact_ids"]
        )
    assert len(calls) == 2


def test_family_does_not_change_source_snapshots_and_explicit_models(data_environment):
    api = TestClient(app)
    _, scope, doc = document_source(api, data_environment, model=data_environment["model"])
    with session_factory()() as db:
        source = freeze(db, scope, "Prepare the selected task.")
        before = json.dumps(source, sort_keys=True)
        for family in ["report", "code", "data"]:
            settings = definition(
                source,
                SelectedProposal(**proposal(), family=family),
                "Europe/Warsaw",
                report_model="different-chat-model",
            )
            assert settings.model == data_environment["model"]
            assert settings.documents.artifact_ids[0].hex == doc["id"].replace("-", "")
            assert settings.maximum_runtime == source["definition"]["maximum_runtime"]
            assert (
                settings.permission_profile == "agent_local"
                and not settings.enabled
                and settings.project_id is None
            )
        assert json.dumps(source, sort_keys=True) == before
        assert definition(source, SelectedProposal(**proposal()), "UTC").tools == [
            "python_data",
            "read_documents",
        ]


@pytest.mark.parametrize("family", ["cursor", "codex", "shell", "external"])
def test_unavailable_or_external_family_is_not_a_proposal(family):
    with pytest.raises(ValueError):
        SelectedProposal(**proposal(), family=family)


def test_instruction_only_creation_retains_data_family(data_environment):
    with session_factory()() as db:
        source = freeze(
            db, {"operation": "create", "model": "auto"}, "Create a daily CSV from these numbers."
        )
        assert allowed_families(source) == ["data"]
        with pytest.raises(ValueError):
            definition(source, SelectedProposal(**proposal(), family="code"), "UTC")


def test_code_family_uses_owned_setup_then_source_bound_existing_coding_chain(data_environment, monkeypatch):
    from app.engine import tick
    from app.runs import request_cancel
    from test_agent_workspace import native_finish

    api = TestClient(app)
    cid, scope, _ = document_source(api, data_environment, model=data_environment["model"])

    async def stream(self, **kwargs):
        yield json.dumps(
            {**proposal(), "family": "code", "goal": "Build the calculator website from the selected brief."}
        )

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        aid = db.scalar(select(Agent)).id
    saved = api.get("/api/agents/" + aid).json()
    enabled = api.post(
        "/api/agents/" + aid + "/enabled", json={"enabled": True, "expected_updated_at": saved["updated_at"]}
    )
    assert enabled.status_code == 200, enabled.text
    queued = api.post(
        "/api/agents/" + aid + "/run", json={"expected_updated_at": enabled.json()["updated_at"]}
    )
    assert queued.status_code == 202, queued.text
    with session_factory()() as db:
        assert tick(db, "family-code-root") == queued.json()["id"]
        setup_run = db.scalar(
            select(Run).where(Run.task_id == queued.json()["task_id"], Run.executor_type == "project_setup")
        )
        assert setup_run and all(
            setup_run.parameters["settings"][key] for key in ["auto_install_dependencies", "auto_validate"]
        )
        native_finish(db, setup_run)
        preparation = None
        for _ in range(8):
            preparation = db.scalar(
                select(Run).where(
                    Run.task_id == queued.json()["task_id"], Run.executor_type == "worktree_prepare"
                )
            )
            if preparation:
                break
            tick(db, "family-code-context")
        assert preparation, [
            (r.executor_type, r.status, r.error_message)
            for r in db.scalars(select(Run).where(Run.task_id == queued.json()["task_id"]))
        ]
        request = preparation.parameters["local_coding"]
        assert "WillowBrief" in request["guidance"]
        assert request["model"] == data_environment["model"] and request["context_sources"]
        assert preparation.project_id and preparation.agent_id == aid
        assert "external_ai" not in preparation.effective_permissions
        assert not any(
            r.executor_type == "python"
            for r in db.scalars(select(Run).where(Run.task_id == queued.json()["task_id"]))
        )
        request_cancel(db, db.get(Run, queued.json()["id"]))
        db.commit()
        assert db.get(Run, preparation.id).status == "canceled"
