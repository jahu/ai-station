from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Agent, Run, Worktree
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_agent_coding import project, start
from test_coding_model_routing import candidate


def test_factory_coding_uses_auto_but_report_and_external_choices_stay_distinct():
    with TestClient(app) as client:
        local = client.post(
            "/api/agents/draft",
            json={"instruction": "Create a coding agent to write code", "model": "small-chat"},
        ).json()
        report = client.post(
            "/api/agents/draft", json={"instruction": "Every morning check GPU status", "model": "small-chat"}
        ).json()
        external = client.post(
            "/api/agents/draft",
            json={"instruction": "Create a coding agent with Codex to write code", "model": "small-chat"},
        ).json()
        assert local["tools"] == ["coding_local"] and local["model"] == "auto" and not local["enabled"]
        assert report["model"] == "small-chat"
        assert external["model"] == "" and external["permission_profile"] == "agent_external_coding"


def test_auto_activation_without_a_fitting_model_creates_no_agent_or_work():
    with TestClient(app) as client, session_factory()() as session:
        row = project(session)
        response = client.post(
            "/api/agents",
            json={
                "name": "Auto builder",
                "goal": "Build a calculator",
                "model": "auto",
                "tools": ["coding_local"],
                "project_id": row.id,
                "enabled": True,
            },
        )
        assert response.status_code == 409, response.text
        assert session.scalar(select(func.count()).select_from(Agent)) == 0
        assert session.scalar(select(func.count()).select_from(Run)) == 0
        assert session.scalar(select(func.count()).select_from(Worktree)) == 0


def test_auto_checks_fit_without_binding_or_loading_before_approval(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Auto is a coding policy, not a provider model")

    monkeypatch.setattr("app.agents_api.model_endpoint", forbidden)
    monkeypatch.setattr("app.schedule.model_endpoint", forbidden)
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda _: {
            "gpus": [{"index": 2, "memory_total_mib": 12288}, {"index": 7, "memory_total_mib": 12288}]
        },
    )
    client = TestClient(app)
    with session_factory()() as session:
        model, _ = candidate(session)
        row = project(session)
        prior_loads = session.scalar(
            select(func.count()).select_from(Run).where(Run.executor_type == "llamacpp")
        )
        session.commit()
        _, parent = start(client, row.id, model="auto", require_approval=True)
        assert parent["status"] == "waiting_for_approval" and parent["parameters"]["endpoint"] == ""
        assert session.scalar(select(Worktree)) is None
        assert (
            session.scalar(select(func.count()).select_from(Run).where(Run.executor_type == "llamacpp"))
            == prior_loads
        )
        session.commit()
        response = client.post("/api/runs/" + parent["id"] + "/approval", json={"resolution": "granted"})
        assert response.status_code == 200, response.text
        assert tick(session, "auto-coding") == parent["id"]
        child = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        request = child.parameters["local_coding"]
        assert request["model"] == "llamacpp:" + model.id
        assert request["model_selection"]["requested"] == "auto"
        assert request["model_selection"]["context_size"] >= 100000
        assert "external_ai" not in child.effective_permissions
        assert (
            session.scalar(select(func.count()).select_from(Run).where(Run.executor_type == "llamacpp"))
            == prior_loads
        )
