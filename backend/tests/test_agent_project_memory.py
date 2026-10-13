import json
from datetime import timedelta

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.memory import upsert_memory
from app.models import Agent, MemoryEntry, Project, Run
from app.schedule import scheduler_tick
from fastapi.testclient import TestClient
from sqlalchemy import select


def targets():
    with session_factory()() as session:
        projects = [Project(name=name, repo_path=f"/unused/{name}") for name in ("first", "second")]
        session.add_all(projects)
        session.flush()
        own = upsert_memory(
            session,
            scope="project",
            scope_id=projects[0].id,
            content="Reviewed project decision",
            pinned=True,
            memory_type="decision",
        )
        upsert_memory(session, scope="project", scope_id=projects[1].id, content="OTHER PROJECT SECRET")
        upsert_memory(session, scope="global", content="GLOBAL SECRET")
        disabled = upsert_memory(session, scope="project", scope_id=projects[0].id, content="DISABLED SECRET")
        disabled.enabled = False
        upsert_memory(session, scope="project", scope_id=projects[0].id, content="x" * 13000)
        session.commit()
        return [p.id for p in projects], own.id


def create(api, project_id=None, **extra):
    response = api.post(
        "/api/agents",
        json={
            "name": "Project reviewer",
            "goal": "Summarize saved project decisions",
            "model": "fake-local",
            "tools": ["project_memory"],
            "project_id": project_id,
            "enabled": True,
            **extra,
        },
    )
    return response


def queue(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def drain():
    with session_factory()() as session:
        for _ in range(12):
            if tick(session, "project-memory-test") is None:
                return
    raise AssertionError("Workflow queue did not drain")


def test_activation_requires_project_and_separate_read_permission():
    api = TestClient(app)
    assert create(api).status_code == 422
    assert create(api, enabled=False).status_code == 201
    projects, _ = targets()
    response = create(api, projects[0])
    assert response.status_code == 201, response.text
    assert response.json()["effective_permissions"] == ["project_memory_read"]
    linked_only = create(api, projects[0], tools=[]).json()
    assert linked_only["effective_permissions"] == []


@pytest.mark.parametrize("scheduled", [False, True])
def test_workflow_reads_only_snapshotted_project_and_persists_exact_context(monkeypatch, scheduled):
    projects, memory_id = targets()
    api = TestClient(app)
    messages = []

    async def stream(self, **params):
        messages.append(params["messages"])
        yield "# Saved project decisions\n\nReviewed project decision"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = create(
        api,
        projects[0],
        trigger="interval" if scheduled else "manual",
        interval_seconds=60 if scheduled else None,
        tools=["project_memory", "remember_workflow"],
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    if scheduled:
        with session_factory()() as session:
            session.get(Agent, agent["id"]).next_run_at = utcnow() - timedelta(seconds=1)
            session.commit()
            run_id = scheduler_tick(session)[0]
            session.commit()
    else:
        run_id = queue(api, agent)
    with session_factory()() as session:
        session.get(Agent, agent["id"]).project_id = projects[1]
        session.commit()
        tick(session, "publish-snapshot")
        tick(session, "read-snapshot")
        upsert_memory(
            session,
            scope="project",
            scope_id=projects[0],
            entry_id=memory_id,
            content="UPDATED LATER",
            memory_type="decision",
            pinned=True,
        )
        session.commit()
    drain()
    parent = api.get("/api/runs/" + run_id).json()
    assert parent["status"] == "succeeded", parent
    step = next(s for s in parent["workflow"]["steps"] if s["key"] == "project_memory")
    child = api.get("/api/runs/" + step["run_id"]).json()
    observed = child["metadata"]["observation"]
    assert observed["scope"] == "project" and observed["scope_id"] == projects[0]
    assert [e["id"] for e in observed["entries"]] == [memory_id]
    assert observed["entries"][0]["source_run_id"] is None
    assert observed["entries"][0]["untrusted"] is True
    assert "Reviewed project decision" in str(messages)
    assert all(
        secret not in str(messages)
        for secret in ("OTHER PROJECT SECRET", "GLOBAL SECRET", "DISABLED SECRET", "UPDATED LATER")
    )
    artifacts = api.get("/api/artifacts?run_id=" + child["id"]).json()
    saved = api.get("/api/artifacts/" + artifacts[0]["id"] + "/file").json()
    assert saved == observed
    with session_factory()() as session:
        assert not list(session.scalars(select(MemoryEntry).where(MemoryEntry.scope == "agent")))
    reset_engine()
    assert api.get("/api/runs/" + child["id"]).json()["metadata"]["observation"] == observed
    assert "tool.completed" in api.get("/api/runs/" + child["id"] + "/stream").text


@pytest.mark.parametrize("failure", ["permission", "target"])
def test_revoked_permission_or_changed_target_never_reaches_inference(monkeypatch, failure):
    projects, _ = targets()
    api = TestClient(app)
    response = create(api, projects[0])
    assert response.status_code == 201, response.text
    run_id = queue(api, response.json())
    with session_factory()() as session:
        tick(session, "publish-only")
        child = session.scalar(
            select(Run).where(Run.parent_run_id == run_id, Run.executor_type == "agent_tool")
        )
        child_id = child.id
        if failure == "permission":
            child.effective_permissions = []
        else:
            child.project_id = projects[1]
        session.commit()

    called = []

    async def fail(self, **params):
        called.append(True)
        raise AssertionError("Invalid scope reached inference")
        yield "never"

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    drain()
    assert api.get("/api/runs/" + child_id).json()["status"] == "failed"
    assert api.get("/api/artifacts?run_id=" + child_id).json() == []
    view = api.get("/api/runs/" + run_id).json()["workflow"]["steps"]
    assert next(step for step in view if step["key"] == "report")["status"] == "failed"
    assert not called


def test_model_cannot_choose_scope_and_link_does_not_grant_tool():
    from uuid import uuid4

    from app.agent_schema import AgentSettings
    from app.agent_tools import parse_tool_call

    definition = AgentSettings(name="Reviewer", goal="Review", tools=["project_memory"], project_id=uuid4())
    assert parse_tool_call(definition, {"name": "project_memory", "arguments": "{}"})[0] == "project_memory"
    with pytest.raises(ValueError, match="arguments"):
        parse_tool_call(
            definition, {"name": "project_memory", "arguments": json.dumps({"project_id": str(uuid4())})}
        )
    definition.tools = []
    with pytest.raises(ValueError, match="unauthorized"):
        parse_tool_call(definition, {"name": "project_memory", "arguments": "{}"})
