from datetime import timedelta

from app.api import app
from app.db import utcnow
from app.models import Agent, Artifact, Conversation, Project, RuntimeInstance
from app.runs import create_run, create_task
from fastapi.testclient import TestClient


def test_overview_is_bounded_and_preserves_schedule_and_runtime_truth(session):
    now = utcnow()
    project = Project(name="Workstation docs", repo_path="/fixture/repo")
    session.add(project)
    session.flush()
    for i in range(12):
        task = create_task(session, title=f"Task {i}", prompt="private prompt", capability="test")
        run = create_run(session, task, run_type="test", capability="test", executor_type="fake")
        run.status = "running" if i == 11 else "queued"
        session.add(Artifact(artifact_type="markdown", relative_path=f"artifacts/{i}.md", run_id=run.id))
        session.add(Conversation(title=f"Conversation {i}", system_prompt="private system prompt"))
        session.add(
            Agent(
                name=f"Agent {i}",
                enabled=True,
                trigger="interval",
                interval_seconds=3600,
                next_run_at=now + timedelta(minutes=i - 1),
                system_prompt="private agent prompt",
                project_id=project.id if i == 0 else None,
            )
        )
    session.add(Agent(name="Paused", enabled=False, trigger="interval", next_run_at=now - timedelta(days=1)))
    session.add(Agent(name="Manual", enabled=True, trigger="manual", next_run_at=now - timedelta(days=1)))
    session.add(Artifact(artifact_type="image", relative_path="uploads/input.png"))
    session.add(
        RuntimeInstance(
            name="Old service",
            runtime_key="ollama",
            status="observed",
            updated_at=now - timedelta(minutes=6),
            metadata_json={"source": "host_process"},
        )
    )
    session.add(
        RuntimeInstance(
            name="Endpoint",
            runtime_key="openai-compatible",
            status="unavailable",
            updated_at=now,
            metadata_json={"source": "configured_endpoint"},
        )
    )
    session.commit()
    response = TestClient(app).get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["active_run_count"] == 12 and len(data["active_runs"]) == 8
    assert data["active_runs"][0]["status"] == "running"
    assert data["enabled_agent_count"] == 13 and len(data["agents"]) == 6
    assert len(data["upcoming"]) == 6
    assert data["upcoming"][0]["name"] == "Agent 0" and data["upcoming"][0]["overdue"]
    assert data["upcoming"][0]["project_id"] == project.id
    assert all(row["name"] not in {"Paused", "Manual"} for row in data["upcoming"])
    assert all("project_id" in row for row in data["agents"])
    assert len(data["conversations"]) == 5 and len(data["artifacts"]) == 6
    assert all(row["type"] == "markdown" for row in data["artifacts"])
    runtimes = {row["name"]: row for row in data["runtimes"]}
    assert runtimes["Old service"]["stale"] and runtimes["Old service"]["status"] == "observed"
    assert not runtimes["Endpoint"]["stale"] and runtimes["Endpoint"]["status"] == "unavailable"
    assert "private" not in response.text
    session.expire_all()
    assert run.status == "running"


def test_empty_overview_does_not_require_runner_or_model():
    data = TestClient(app).get("/api/dashboard").json()
    assert data["active_run_count"] == data["enabled_agent_count"] == 0
    assert all(
        data[key] == []
        for key in (
            "active_runs",
            "upcoming",
            "agents",
            "conversations",
            "artifacts",
            "runtimes",
            "interrupted_runs",
        )
    )
