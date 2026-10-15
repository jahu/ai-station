import pytest
from app.agent_coding import publish_coding
from app.agent_schema import AgentSettings
from app.api import app
from app.coding_tasks import queue_proposal
from app.db import session_factory
from app.engine import tick
from app.models import Approval, Run, Worktree
from app.permissions import PermissionDenied
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_coding import finish, project, start


@pytest.mark.parametrize("provider", ["cursor", "codex"])
def test_external_coding_requires_its_explicit_profile(provider):
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
    body = {
        "name": "External builder",
        "goal": "Build a tested calculator",
        "tools": ["coding_" + provider],
        "project_id": row.id,
        "enabled": True,
    }
    response = client.post("/api/agents", json=body)
    assert response.status_code == 422 and "explicit external-coding" in response.text
    response = client.post("/api/agents", json={**body, "permission_profile": "agent_external_coding"})
    assert response.status_code == 201, response.text
    assert response.json()["execution_location"] == "external"
    for patch in ({"tools": ["coding_local"]}, {"tools": ["coding_" + provider, "system_snapshot"]}):
        assert (
            client.post(
                "/api/agents", json={**body, "permission_profile": "agent_external_coding", **patch}
            ).status_code
            == 422
        )


@pytest.mark.parametrize("provider", ["cursor", "codex"])
@pytest.mark.parametrize("phase", ["queued", "running"])
def test_external_agent_reuses_owned_coding_chain_without_local_inference(monkeypatch, provider, phase):
    def forbidden(*args, **kwargs):
        raise AssertionError("External coding must not resolve or load a local model")

    monkeypatch.setattr("app.schedule.model_endpoint", forbidden)
    monkeypatch.setattr("app.agents_api.model_endpoint", forbidden)
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(
            client, row.id, tools=["coding_" + provider], model="", permission_profile="agent_external_coding"
        )
        frozen = session.get(Run, parent["id"])
        assert "external_ai" in frozen.effective_permissions
        assert (
            frozen.metadata_json["execution_location"] == "external" and frozen.parameters["endpoint"] == ""
        )
        assert tick(session, "external-builder") == parent["id"]
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        assert preparation.executor_type == "worktree_prepare" and preparation.agent_id == agent["id"]
        assert (
            preparation.parameters[provider]["model"] == ""
            and preparation.parameters[provider]["explore"] is True
        )
        assert "Keep tests meaningful" in preparation.parameters[provider]["guidance"]
        assert "agent_coding_deadline" in preparation.parameters[provider]
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
        assert not worktree.owned and worktree.relative_path.startswith("worktrees/")
        preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": worktree.branch}}
        queue_proposal(session, preparation, worktree)
        proposal = session.get(Run, preparation.metadata_json["coding_run_id"])
        finish(session, preparation)
        session.commit()
        assert (
            proposal.executor_type == provider + "_proposal"
            and "external_ai" in proposal.effective_permissions
        )
        assert proposal.parameters["agent_coding_deadline"] == preparation.parameters["agent_coding_deadline"]
        if phase == "running":
            from app.runs import transition
            from app.state import RunStatus

            for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(session, proposal, state, event_type="test.transition")
        request_cancel(session, session.get(Run, parent["id"]))
        session.commit()
        session.refresh(proposal)
        assert proposal.status == ("canceled" if phase == "queued" else "cancel_requested")
        session.commit()
        view = client.get("/api/runs/" + parent["id"]).json()["workflow"]
        assert [s["key"] for s in view["steps"]] == ["coding.prepare", "coding." + provider]


@pytest.mark.parametrize("provider", ["cursor", "codex"])
def test_external_approval_parks_before_any_worktree_or_cli_child(provider):
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        _, parent = start(
            client,
            row.id,
            tools=["coding_" + provider],
            model="",
            permission_profile="agent_external_coding",
            require_approval=True,
        )
        assert parent["status"] == "waiting_for_approval"
        assert tick(session, "no-approval") is None
        assert session.scalar(select(Worktree)) is None
        assert len(list(session.scalars(select(Run)))) == 1
        approval = session.scalar(select(Approval))
        assert approval and approval.resolution == "pending"
        session.commit()
        granted = client.post("/api/runs/" + parent["id"] + "/approval", json={"resolution": "granted"})
        assert granted.status_code == 200, granted.text
        assert tick(session, "approved-external") == parent["id"]
        child = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        assert child.executor_type == "worktree_prepare" and provider in child.parameters


@pytest.mark.parametrize("provider", ["cursor", "codex"])
def test_missing_external_permission_cannot_publish_a_coding_child(provider):
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        _, parent = start(
            client, row.id, tools=["coding_" + provider], model="", permission_profile="agent_external_coding"
        )
        run = session.get(Run, parent["id"])
        run.effective_permissions = [p for p in run.effective_permissions if p != "external_ai"]
        definition = AgentSettings.model_validate(run.parameters["definition"])
        with pytest.raises(PermissionDenied):
            publish_coding(session, run, definition)
        assert session.scalar(select(Worktree)) is None
        assert len(list(session.scalars(select(Run)))) == 1


def test_factory_external_draft_discloses_provider_and_defaults_to_approval():
    with TestClient(app) as client:
        response = client.post(
            "/api/agents/draft", json={"instruction": "Create a coding agent with Codex to build a website"}
        )
        assert response.status_code == 201, response.text
        draft = response.json()
        assert draft["tools"] == ["coding_codex"] and draft["permission_profile"] == "agent_external_coding"
        assert (
            draft["require_approval"] and not draft["enabled"] and draft["execution_location"] == "external"
        )
