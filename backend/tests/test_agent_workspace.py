"""Project-free agents keep owned setup, provenance, permissions and Stop contracts."""

from datetime import timedelta

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Agent, Project, Run, Worktree
from app.permissions import PermissionDenied
from app.project_setup import ProjectSetupExecutor
from app.runs import request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


def start(client, **changes):
    response = client.post(
        "/api/agents",
        json={
            "name": "Private builder",
            "goal": "Create a calculator",
            "model": "fake-local",
            "tools": ["coding_local"],
            "enabled": True,
            **changes,
        },
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    result = client.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert result.status_code == 202, result.text
    return agent, result.json()


def setup(session, parent):
    assert tick(session, "workspace-worker") == parent["id"]
    child = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
    assert child.executor_type == "project_setup"
    return child


def native_finish(session, child):
    for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
        transition(session, child, status, event_type="test.transition")
    result = ProjectSetupExecutor().finish(
        session,
        child,
        {
            "run_id": child.id,
            "project_id": child.parameters["project_id"],
            "repo_path": "/owned/projects/" + child.parameters["project_id"],
        },
    )
    session.commit()
    assert result == "done"


def test_project_free_agent_creates_owned_workspace_then_existing_worktree_chain():
    client = TestClient(app)
    with session_factory()() as session:
        agent, parent = start(client)
        frozen = session.get(Run, parent["id"]).parameters["definition"]
        stage = setup(session, parent)
        assert stage.agent_id == agent["id"] and stage.task_id == parent["task_id"]
        assert not stage.parameters["settings"]["auto_install_dependencies"]
        assert not stage.parameters["settings"]["auto_validate"]
        native_finish(session, stage)
        project = session.get(Project, stage.project_id)
        saved = session.get(Agent, agent["id"])
        assert saved.project_id == project.id and saved.updated_at.isoformat() != agent["updated_at"]
        root = session.get(Run, parent["id"])
        assert root.parameters["definition"] == frozen and frozen["project_id"] is None
        assert root.project_id == root.task.project_id == project.id
        nested = session.get(Run, stage.metadata_json["workspace_workflow_run_id"])
        assert nested.parameters["definition"] == {**frozen, "project_id": project.id}
        assert nested.parameters["agent_coding_deadline"] == root.parameters["agent_coding_deadline"]
        assert tick(session, "workspace-worker") == nested.id
        preparation = session.scalar(select(Run).where(Run.parent_run_id == nested.id))
        assert preparation.executor_type == "worktree_prepare"
        assert preparation.project_id == project.id and preparation.agent_id == saved.id
        assert preparation.parameters["agent_coding_deadline"] == root.parameters["agent_coding_deadline"]
        assert session.scalar(select(Worktree)).project_id == project.id
        request_cancel(session, root)
        session.commit()
        assert session.get(Run, preparation.id).status == "canceled"
        view = client.get("/api/runs/" + root.id).json()["workflow"]
        assert "project.create" in [step["capability"] for step in view["steps"]]


def test_approval_and_revoked_permissions_prevent_workspace_creation():
    client = TestClient(app)
    with session_factory()() as session:
        _, parent = start(client, require_approval=True)
        assert parent["status"] == "waiting_for_approval"
        assert tick(session, "workspace-worker") is None
        assert not session.scalars(select(Project)).all()
        assert not session.scalars(select(Run).where(Run.parent_run_id == parent["id"])).all()
    with session_factory()() as session:
        _, parent = start(client)
        root = session.get(Run, parent["id"])
        root.effective_permissions = ["filesystem_read"]
        session.commit()
        assert tick(session, "workspace-worker") == root.id
        assert root.status == "failed"
        assert not session.scalars(select(Run).where(Run.parent_run_id == root.id)).all()


@pytest.mark.parametrize("tamper", ["definition", "permissions", "task", "policy"])
def test_workspace_adoption_rejects_changed_scope_and_leaves_no_partial_project(tamper):
    client = TestClient(app)
    with session_factory()() as session:
        agent, parent = start(client)
        stage = setup(session, parent)
        if tamper == "definition":
            session.get(Agent, agent["id"]).goal = "Changed goal"
        elif tamper == "permissions":
            session.get(Run, parent["id"]).effective_permissions = []
        elif tamper == "task":
            stage.parent_run_id = None
        else:
            stage.parameters = {
                **stage.parameters,
                "settings": {**stage.parameters["settings"], "auto_validate": True},
            }
        session.commit()
        with pytest.raises((ValueError, PermissionDenied)):
            native_finish(session, stage)
        session.rollback()
        assert not session.scalars(select(Project)).all()
        assert session.get(Agent, agent["id"]).project_id is None


def test_expired_workspace_preserves_created_project_without_starting_code():
    client = TestClient(app)
    with session_factory()() as session:
        agent, parent = start(client)
        stage = setup(session, parent)
        expired = (utcnow() - timedelta(seconds=1)).isoformat()
        root = session.get(Run, parent["id"])
        root.parameters = {**root.parameters, "agent_coding_deadline": expired}
        stage.parameters = {**stage.parameters, "agent_coding_deadline": expired}
        session.commit()
        native_finish(session, stage)
        assert stage.status == "failed" and stage.error_type == "AgentRuntimeLimit"
        assert session.get(Agent, agent["id"]).project_id == stage.project_id
        assert session.get(Project, stage.project_id) is not None
        assert not session.scalars(select(Run).where(Run.parent_run_id == stage.id)).all()
        assert not session.scalars(select(Worktree)).all()


@pytest.mark.parametrize(
    "tamper", ["project", "definition", "deadline", "source", "permissions", "missing_binding"]
)
def test_derived_workflow_cannot_rebind_or_expand_reviewed_scope(tamper):
    client = TestClient(app)
    with session_factory()() as session:
        _, parent = start(client)
        stage = setup(session, parent)
        native_finish(session, stage)
        nested = session.get(Run, stage.metadata_json["workspace_workflow_run_id"])
        if tamper == "project":
            nested.project_id = None
        elif tamper == "definition":
            nested.parameters = {
                **nested.parameters,
                "definition": {**nested.parameters["definition"], "goal": "Other task"},
            }
        elif tamper == "deadline":
            nested.parameters = {
                **nested.parameters,
                "agent_coding_deadline": (utcnow() + timedelta(days=1)).isoformat(),
            }
        elif tamper == "source":
            nested.parent_run_id = parent["id"]
        elif tamper == "missing_binding":
            nested.parameters = {
                key: value for key, value in nested.parameters.items() if key != "workspace_source_run_id"
            }
        else:
            nested.effective_permissions = [*nested.effective_permissions, "external_ai"]
        session.commit()
        assert tick(session, "workspace-worker") == nested.id
        assert nested.status == "failed"
        assert not session.scalars(select(Worktree)).all()


def test_page_coding_shares_the_original_workspace_deadline():
    client = TestClient(app)
    with session_factory()() as session:
        _, parent = start(client, tools=["coding_local", "http_fetch"], fetch_urls=["https://example.com/"])
        stage = setup(session, parent)
        native_finish(session, stage)
        nested = session.get(Run, stage.metadata_json["workspace_workflow_run_id"])
        assert tick(session, "workspace-worker") == nested.id
        children = list(session.scalars(select(Run).where(Run.parent_run_id == nested.id)))
        assert {child.executor_type for child in children} == {"agent_tool", "agent_page_coding"}
        assert all(
            child.parameters["deadline_at"] == stage.parameters["agent_coding_deadline"] for child in children
        )
        assert all(child.project_id == stage.project_id for child in children)


def test_repeated_execution_and_manual_retry_reuse_the_verified_project():
    from app.runs import mark_failed
    from app.schedule import launch_agent, retry_workflow

    client = TestClient(app)
    with session_factory()() as session:
        agent, parent = start(client, retry_policy={"mode": "manual"})
        stage = setup(session, parent)
        native_finish(session, stage)
        nested = session.get(Run, stage.metadata_json["workspace_workflow_run_id"])
        transition(session, nested, RunStatus.CLAIMED, event_type="test.claimed")
        mark_failed(session, nested, "SyntheticFailure", "Test failure before coding")
        session.commit()
        retry = session.get(Run, retry_workflow(session, session.get(Run, parent["id"])))
        session.commit()
        assert retry.project_id == stage.project_id
        assert retry.parameters["definition"]["project_id"] == stage.project_id
        assert tick(session, "workspace-worker") == retry.id
        prep = session.scalar(select(Run).where(Run.parent_run_id == retry.id))
        assert prep.executor_type == "worktree_prepare"
        request_cancel(session, retry)
        session.commit()
        next_id = launch_agent(session, session.get(Agent, agent["id"]), triggered_by="manual")
        session.commit()
        assert tick(session, "workspace-worker") == next_id
        prep2 = session.scalar(select(Run).where(Run.parent_run_id == next_id))
        assert prep2.executor_type == "worktree_prepare" and prep2.project_id == stage.project_id
        assert len(list(session.scalars(select(Project)))) == 1
        assert len(list(session.scalars(select(Run).where(Run.executor_type == "project_setup")))) == 1


@pytest.mark.parametrize("change", ["permissions", "definition"])
def test_changed_scope_is_rejected_before_native_workspace_dispatch(monkeypatch, change):
    from app.runner_client import RunnerClient

    client = TestClient(app)
    with session_factory()() as session:
        agent, parent = start(client)
        stage = setup(session, parent)
        if change == "permissions":
            session.get(Run, parent["id"]).effective_permissions = []
        else:
            session.get(Agent, agent["id"]).goal = "Changed goal"
        session.commit()
        monkeypatch.setattr(
            RunnerClient, "request", lambda *a, **k: pytest.fail("Changed scope reached native creation")
        )
        assert tick(session, "workspace-worker") == stage.id
        assert stage.status == "failed"
        assert not stage.metadata_json.get("dispatch_attempted")
        assert not session.scalars(select(Project)).all()
