"""Website drafts propose scoped build automation; old agents and tools retain their policy."""

import pytest
from app.agent_schema import AgentSettings
from app.factory import draft_agent
from app.models import Agent
from pydantic import ValidationError


@pytest.mark.parametrize(
    "goal",
    [
        "Create a website from https://example.com",
        "Build a web app from https://example.com",
        "Zbuduj nową stronę dla https://example.com",
        "Stwórz mi stronę na podstawie https://example.com",
    ],
)
def test_website_factory_proposes_reviewable_builds_in_a_disabled_local_draft(goal):
    draft = draft_agent(goal)
    assert draft.tools == ["coding_local", "http_fetch"] and draft.model == "auto"
    assert not draft.enabled and draft.project_id is None
    assert draft.workspace_policy == {"auto_install_dependencies": True, "auto_validate": True}
    assert draft.maximum_runtime == 1800
    assert draft.fetch_urls == ["https://example.com"]


@pytest.mark.parametrize(
    "tools,profile",
    [
        (["system_snapshot"], "agent_local"),
        (["python_data"], "agent_local"),
        (["coding_cursor"], "agent_external_coding"),
    ],
)
def test_build_scope_cannot_be_attached_to_other_tools(tools, profile):
    with pytest.raises(ValidationError, match="only to Local coding"):
        AgentSettings(
            name="Wrong scope",
            goal="Inspect",
            tools=tools,
            permission_profile=profile,
            workspace_policy={"auto_validate": True},
        )


def test_generic_agent_factory_keeps_automation_off():
    assert draft_agent("Write code to calculate totals").workspace_policy == {}


def test_migration_preserves_legacy_agent_and_defaults_build_automation_off(session, legacy_schema):
    from alembic import command
    from app.db import alembic_config

    agent = Agent(name="Legacy builder", goal="Keep my original goal", tools=["coding_local"])
    session.add(agent)
    session.commit()
    aid = agent.id
    legacy_schema("0027")
    command.upgrade(alembic_config(), "head")
    session.expire_all()
    row = session.get(Agent, aid)
    assert row.name == "Legacy builder" and row.goal == "Keep my original goal"
    assert AgentSettings(
        name=row.name, goal=row.goal, tools=row.tools, workspace_policy=row.workspace_policy
    ).workspace_policy.model_dump() == {"auto_install_dependencies": False, "auto_validate": False}


def test_workspace_policy_survives_api_save_reload_and_duplicate():
    from app.api import app
    from fastapi.testclient import TestClient

    body = {
        "name": "Website builder",
        "goal": "Create a website",
        "tools": ["coding_local"],
        "model": "fake-local",
        "workspace_policy": {"auto_install_dependencies": True, "auto_validate": True},
    }
    with TestClient(app) as client:
        created = client.post("/api/agents", json=body)
        assert created.status_code == 201, created.text
        agent = created.json()
        assert client.get("/api/agents/" + agent["id"]).json()["workspace_policy"] == body["workspace_policy"]
        saved = client.put(
            "/api/agents/" + agent["id"],
            json={
                **body,
                "description": "Reviewed dependency downloads",
                "expected_updated_at": agent["updated_at"],
            },
        )
        assert saved.status_code == 200, saved.text
        duplicate = client.post(
            "/api/agents/" + agent["id"] + "/duplicate",
            json={"expected_updated_at": saved.json()["updated_at"]},
        )
        assert duplicate.status_code == 201, duplicate.text
        assert (
            not duplicate.json()["enabled"]
            and duplicate.json()["workspace_policy"] == body["workspace_policy"]
        )


def test_reading_a_website_does_not_grant_website_build_automation():
    draft = draft_agent("Create an agent that reads CSV files from a website at https://example.com")
    assert "coding_local" not in draft.tools
    assert draft.workspace_policy == {} and not draft.enabled
