from datetime import timedelta

from app.api import app
from app.db import utcnow
from app.models import Agent, Project
from app.runs import create_run, create_task
from fastapi.testclient import TestClient


def test_combined_filters_are_applied_before_pagination(session):
    now = utcnow()
    project = Project(name="Repository", repo_path="/fixture/repo")
    agent = Agent(name="Agent")
    session.add_all([project, agent])
    session.flush()
    expected = []
    for i in range(6):
        task = create_task(session, title="Test", prompt="", capability="image.generate")
        row = create_run(
            session,
            task,
            run_type="image",
            capability="image.generate",
            executor_type="photo_pipe",
            project_id=project.id,
            agent_id=agent.id,
            requested_gpu="7",
        )
        row.created_at = now - timedelta(minutes=i)
        row.actual_gpu = "3" if i == 0 else None
        if i in {2, 3}:
            expected.append(row.id)
        if i == 1:
            row.executor_type = "other"
    session.commit()
    api = TestClient(app)
    params = {
        "status": "queued",
        "capability": "image.generate",
        "executor": "photo_pipe",
        "target": "host",
        "project_id": project.id,
        "agent_id": agent.id,
        "gpu": "7",
        "created_after": (now - timedelta(minutes=3)).isoformat(),
        "created_before": now.isoformat(),
        "limit": 1,
    }
    assert [r["id"] for r in api.get("/api/runs", params=params).json()] == expected[:1]
    assert [r["id"] for r in api.get("/api/runs", params={**params, "offset": 1}).json()] == expected[1:]
    assert len(api.get("/api/runs", params={"gpu": "3"}).json()) == 1
    assert len(api.get("/api/runs", params={"gpu": "7"}).json()) == 5


def test_filter_validation_rejects_ambiguous_dates_and_invalid_ids():
    api = TestClient(app)
    for params in [
        {"project_id": "not-a-uuid"},
        {"agent_id": "not-a-uuid"},
        {"target": "shell"},
        {"offset": -1},
        {"created_after": "2026-09-26T10:00:00"},
        {"created_after": "2026-09-26T10:00:00Z", "created_before": "2026-09-25T10:00:00Z"},
    ]:
        assert api.get("/api/runs", params=params).status_code == 422
