"""Ordinary settings edits must not postpone an existing scheduled observation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app import schedule
from app.agent_schema import AgentSettings
from app.agent_tools import AGENT_TOOLS
from app.api import app
from app.db import session_factory
from app.models import Agent
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient

NOW = datetime(2030, 1, 1, 12, 3, tzinfo=UTC)


@pytest.fixture
def scheduled_video(monkeypatch):
    monkeypatch.setattr(schedule, "utcnow", lambda: NOW)
    monkeypatch.setitem(AGENT_TOOLS, "create_media", replace(AGENT_TOOLS["create_media"], operational=True))

    def capabilities(self, method, path, json=None):
        assert method == "GET", "A settings edit launched native work"
        assert path == "/v1/video/capabilities"
        return {
            "available": True,
            "memory_profiles": [{"id": "bounded_11g", "available": True, "ram_mib": 11264}],
        }

    monkeypatch.setattr(RunnerClient, "request", capabilities)
    return TestClient(app)


def create(api, **calendar):
    response = api.post(
        "/api/agents",
        json={
            "name": "Coastal film",
            "goal": "Create the reviewed film",
            "enabled": True,
            "tools": ["create_media"],
            "maximum_runtime": 600,
            "media": {
                "kind": "video",
                "description_source": "fixed",
                "request": {"prompt": "Coast", "duration_seconds": 15},
            },
            "trigger": "interval",
            "interval_seconds": 300,
            **calendar,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def update_body(aid):
    with session_factory()() as db:
        row = db.get(Agent, aid)
        body = AgentSettings.model_validate(
            {key: getattr(row, key) for key in AgentSettings.model_fields}
        ).model_dump(mode="json")
        body["expected_updated_at"] = row.updated_at.isoformat()
    return body


@pytest.mark.parametrize(
    "calendar,due",
    [
        ({}, NOW + timedelta(minutes=1)),
        (
            {
                "trigger": "cron",
                "cron_expr": "0 12 * * *",
                "interval_seconds": None,
                "schedule_timezone": "UTC",
            },
            NOW - timedelta(minutes=3),
        ),
    ],
)
def test_video_setup_edit_preserves_exact_due_instant_including_overdue_cron(scheduled_video, calendar, due):
    api = scheduled_video
    aid = create(api, **calendar)
    with session_factory()() as db:
        row = db.get(Agent, aid)
        row.next_run_at = due
        db.commit()
    body = update_body(aid)
    body["maximum_runtime"] = 7200
    body["media"]["request"]["memory_profile"] = "bounded_11g"
    response = api.put("/api/agents/" + aid, json=body)
    assert response.status_code == 200, response.text
    with session_factory()() as db:
        row = db.get(Agent, aid)
        assert row.next_run_at == due
        assert row.enabled and row.maximum_runtime == 7200
        assert row.media["request"]["memory_profile"] == "bounded_11g"
    assert api.get("/api/runs").json() == []


def test_explicit_calendar_change_reanchors_interval(scheduled_video):
    api = scheduled_video
    aid = create(api)
    body = update_body(aid)
    body["interval_seconds"] = 600
    response = api.put("/api/agents/" + aid, json=body)
    assert response.status_code == 200, response.text
    with session_factory()() as db:
        assert db.get(Agent, aid).next_run_at == NOW + timedelta(seconds=600)


def test_disabled_setting_still_clears_schedule(scheduled_video):
    api = scheduled_video
    aid = create(api)
    body = update_body(aid)
    body["enabled"] = False
    response = api.put("/api/agents/" + aid, json=body)
    assert response.status_code == 200, response.text
    with session_factory()() as db:
        row = db.get(Agent, aid)
        assert not row.enabled and row.next_run_at is None


def test_missing_due_time_is_repaired_instead_of_preserved(scheduled_video):
    api = scheduled_video
    aid = create(api)
    with session_factory()() as db:
        row = db.get(Agent, aid)
        row.next_run_at = None
        db.commit()
    response = api.put("/api/agents/" + aid, json=update_body(aid))
    assert response.status_code == 200, response.text
    with session_factory()() as db:
        assert db.get(Agent, aid).next_run_at == NOW + timedelta(seconds=300)
