from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from alembic import command
from app.agent_schema import AgentSettings
from app.api import app
from app.db import alembic_config, reset_engine, session_factory
from app.models import Agent, Run
from app.schedule import compute_next, scheduler_tick
from app.schedule_time import next_cron
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_drafts import model as model


def stamp(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize(
    ("zone", "rule", "after", "expected"),
    [
        ("UTC", "0 9 * * *", "2026-01-12T08:00Z", "2026-01-12T09:00Z"),
        ("Europe/Warsaw", "0 9 * * *", "2026-01-12T00:00Z", "2026-01-12T08:00Z"),
        ("Europe/Warsaw", "0 9 * * *", "2026-07-12T00:00Z", "2026-07-12T07:00Z"),
        ("America/New_York", "0 9 * * *", "2026-07-12T00:00Z", "2026-07-12T13:00Z"),
        ("Asia/Kathmandu", "0 9 * * *", "2026-07-12T00:00Z", "2026-07-12T03:15Z"),
        ("Europe/Warsaw", "30 2 * * *", "2026-03-28T23:00Z", "2026-03-30T00:30Z"),
        ("Europe/Warsaw", "30 2 * * *", "2026-10-24T23:00Z", "2026-10-25T00:30Z"),
        ("Europe/Warsaw", "30 2 * * *", "2026-10-25T00:31Z", "2026-10-26T01:30Z"),
        ("Europe/Warsaw", "30 2 * * *", "2026-10-25T01:10Z", "2026-10-26T01:30Z"),
        ("Europe/Warsaw", "* * * * *", "2026-10-25T01:10Z", "2026-10-25T02:00Z"),
        ("Australia/Lord_Howe", "15 2 * * *", "2026-10-03T15:20Z", "2026-10-04T15:15Z"),
        ("Australia/Lord_Howe", "45 1 * * *", "2026-04-04T14:50Z", "2026-04-05T15:15Z"),
        ("Pacific/Apia", "* * * * *", "2011-12-30T09:59Z", "2011-12-30T10:00Z"),
    ],
)
def test_calendar_occurrences_have_explicit_gap_fold_and_offset_policy(zone, rule, after, expected):
    assert next_cron(rule, zone, stamp(after)) == stamp(expected)


@pytest.mark.parametrize("zone", ["../Europe/Warsaw", "/etc/passwd", "Mars/Olympus", "", None])
def test_invalid_timezone_is_rejected_without_publishing(zone):
    with TestClient(app) as client:
        response = client.post(
            "/api/agents", json={"name": "Clock", "goal": "Report", "schedule_timezone": zone}
        )
        assert response.status_code == 422
        assert client.get("/api/agents").json() == []


def test_api_timezone_choices_and_utc_default():
    with TestClient(app) as client:
        zones = client.get("/api/agents/timezones")
        assert zones.status_code == 200
        assert {"UTC", "Europe/Warsaw", "America/New_York"} <= set(zones.json())
        agent = client.post("/api/agents", json={"name": "Legacy", "goal": "Report"}).json()
        assert agent["schedule_timezone"] == "UTC"


def test_interval_and_explicit_one_shot_remain_utc_instants():
    after = stamp("2026-03-29T00:50Z")
    interval = Agent(trigger="interval", interval_seconds=3600, schedule_timezone="Europe/Warsaw")
    assert compute_next(interval, after=after) == after + timedelta(hours=1)
    once = Agent(trigger="datetime", run_at=stamp("2026-03-29T01:20Z"), schedule_timezone="Europe/Warsaw")
    assert compute_next(once, after=after) == stamp("2026-03-29T01:20Z")


def test_timezone_migration_preserves_legacy_schedule_and_schema():
    with TestClient(app) as client:
        original = client.post(
            "/api/agents",
            json={
                "name": "Legacy clock",
                "goal": "Report",
                "model": "fake-local",
                "trigger": "cron",
                "cron_expr": "0 9 * * *",
                "enabled": True,
            },
        ).json()
        command.downgrade(alembic_config(), "0032")
        command.upgrade(alembic_config(), "head")
        command.check(alembic_config())
        restored = client.get("/api/agents/" + original["id"]).json()
        for key in ("id", "name", "goal", "cron_expr", "enabled", "next_run_at", "created_at", "updated_at"):
            assert restored[key] == original[key]
        assert restored["schedule_timezone"] == "UTC"


def test_old_edit_payload_preserves_selected_zone_and_duplicate_retains_it():
    with TestClient(app) as client:
        agent = client.post(
            "/api/agents",
            json={
                "name": "Local clock",
                "goal": "Report",
                "trigger": "cron",
                "cron_expr": "0 9 * * *",
                "schedule_timezone": "Europe/Warsaw",
            },
        ).json()
        body = {key: agent[key] for key in AgentSettings.model_fields if key != "schedule_timezone"}
        body.update(expected_updated_at=agent["updated_at"], name="Updated name")
        response = client.put("/api/agents/" + agent["id"], json=body)
        assert response.status_code == 200, response.text
        assert response.json()["schedule_timezone"] == "Europe/Warsaw"
        duplicated = client.post(
            "/api/agents/" + agent["id"] + "/duplicate",
            json={"expected_updated_at": response.json()["updated_at"]},
        )
        assert duplicated.status_code == 201, duplicated.text
        assert duplicated.json()["schedule_timezone"] == "Europe/Warsaw"
        assert not duplicated.json()["enabled"] and duplicated.json()["next_run_at"] is None
        reset_engine()
        assert client.get("/api/agents/" + agent["id"]).json()["schedule_timezone"] == "Europe/Warsaw"


def test_two_schedulers_claim_one_zoned_run_and_snapshot_it(monkeypatch):
    now = stamp("2026-10-25T01:10Z")
    monkeypatch.setattr("app.schedule.utcnow", lambda: now)
    with TestClient(app) as client:
        response = client.post(
            "/api/agents",
            json={
                "name": "Daily report",
                "goal": "Report",
                "model": "fake-local",
                "trigger": "cron",
                "cron_expr": "30 2 * * *",
                "schedule_timezone": "Europe/Warsaw",
                "enabled": True,
            },
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        with session_factory()() as session:
            session.get(Agent, agent["id"]).next_run_at = now - timedelta(seconds=1)
            session.commit()
        barrier = Barrier(2)

        def schedule():
            barrier.wait()
            with session_factory()() as session:
                result = scheduler_tick(session)
                session.commit()
                return result

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: schedule(), range(2)))
        assert sum(len(result) for result in results) == 1
        with session_factory()() as session:
            runs = list(session.scalars(select(Run).where(Run.agent_id == agent["id"])))
            assert len(runs) == 1 and runs[0].parameters["definition"]["schedule_timezone"] == "Europe/Warsaw"
            row = session.get(Agent, agent["id"])
            assert row.next_run_at == stamp("2026-10-26T01:30Z")
            row.next_run_at = now - timedelta(seconds=1)
            session.commit()
            assert scheduler_tick(session) == []


def test_quick_factory_uses_reviewed_operator_zone_and_defaults_legacy_to_utc():
    with TestClient(app) as client:
        for extra, expected in [({}, "UTC"), ({"schedule_timezone": "Europe/Warsaw"}, "Europe/Warsaw")]:
            response = client.post(
                "/api/agents/draft",
                json={"instruction": "Every morning at 9 check workstation status", **extra},
            )
            assert response.status_code == 201, response.text
            agent = response.json()
            assert (
                agent["schedule_timezone"] == expected
                and agent["cron_expr"] == "0 9 * * *"
                and not agent["enabled"]
            )


@pytest.mark.parametrize(
    ("instruction", "zone", "cron"),
    [
        ("Codziennie o 9 sprawdzaj stan stacji", "Europe/Warsaw", "0 9 * * *"),
        ("Every evening at 9 pm check workstation", "Europe/Warsaw", "0 21 * * *"),
        ("Every morning at 09:00 UTC check workstation", "UTC", "0 9 * * *"),
        ("Every evening at 9 pm UTC check workstation", "UTC", "0 21 * * *"),
    ],
)
def test_factory_clock_and_explicit_utc_are_reviewed_correctly(instruction, zone, cron):
    with TestClient(app) as client:
        response = client.post(
            "/api/agents/draft", json={"instruction": instruction, "schedule_timezone": "Europe/Warsaw"}
        )
        assert response.status_code == 201, response.text
        assert response.json()["schedule_timezone"] == zone
        assert response.json()["cron_expr"] == cron


def test_cron_rejects_naive_instants_and_impossible_calendar_rule():
    with pytest.raises(ValueError):
        next_cron("0 9 * * *", "Europe/Warsaw", datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        next_cron("0 9 31 2 *", "UTC", stamp("2026-01-01T00:00Z"))


def test_ai_draft_freezes_operator_zone_and_replay_rejects_changed_zone(model):
    import json
    from uuid import uuid4

    from app.engine import tick
    from test_agent_drafts import PROPOSAL

    calls, responses = model
    responses[:] = [
        json.dumps({**PROPOSAL, "trigger": "cron", "interval_seconds": None, "cron_expr": "0 9 * * *"})
    ]
    request = {
        "client_request_id": str(uuid4()),
        "instruction": "Every morning at 9 research local AI news",
        "model": "fake-local",
        "schedule_timezone": "Europe/Warsaw",
    }
    with TestClient(app) as client:
        response = client.post("/api/agent-drafts", json=request)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "timezone-draft-test")
            run = session.get(Run, response.json()["id"])
            assert run.status == "succeeded", run.error_message
            agent = session.get(Agent, run.metadata_json["agent_id"])
            assert agent.schedule_timezone == "Europe/Warsaw" and not agent.enabled
            assert run.parameters["schedule_timezone"] == "Europe/Warsaw"
        assert client.post("/api/agent-drafts", json=request).json()["id"] == response.json()["id"]
        assert (
            client.post("/api/agent-drafts", json={**request, "schedule_timezone": "UTC"}).status_code == 409
        )
        assert calls


def test_legacy_draft_receipt_without_timezone_replays(model):
    from uuid import uuid4

    from app.models import Task

    request = {
        "client_request_id": str(uuid4()),
        "instruction": "Every morning research local AI",
        "model": "fake-local",
    }
    with TestClient(app) as client:
        accepted = client.post("/api/agent-drafts", json=request)
        assert accepted.status_code == 202
        with session_factory()() as session:
            task = session.get(Task, request["client_request_id"])
            prior = dict(task.metadata_json["draft_request"])
            prior.pop("schedule_timezone")
            task.metadata_json = {**task.metadata_json, "draft_request": prior}
            session.commit()
        assert client.post("/api/agent-drafts", json=request).json()["id"] == accepted.json()["id"]


def test_work_factory_and_receipt_bind_current_browser_zone(model):
    import json
    from uuid import uuid4

    from app.engine import tick
    from test_agent_drafts import PROPOSAL

    _, responses = model
    responses[:] = [
        json.dumps({**PROPOSAL, "trigger": "cron", "interval_seconds": None, "cron_expr": "0 9 * * *"})
    ]
    request = {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "work", "model": "fake-local"},
        "content": "Create an agent every morning at 9 to research local AI news",
        "action": "agent.create",
        "schedule_timezone": "America/New_York",
        "web_search": {"enabled": False},
    }
    with TestClient(app) as client:
        accepted = client.post("/api/chat/turns", json=request)
        assert accepted.status_code == 202, accepted.text
        with session_factory()() as session:
            tick(session, "timezone-work")
            tick(session, "timezone-work")
            root = session.get(Run, accepted.json()["run"]["id"])
            child = session.get(Run, root.metadata_json["child_run_id"])
            assert child.status == "succeeded", child.error_message
            assert child.parameters["schedule_timezone"] == "America/New_York"
            agent = session.get(Agent, child.metadata_json["agent_id"])
            assert agent.schedule_timezone == "America/New_York" and not agent.enabled
        assert client.post("/api/chat/turns", json=request).json()["run"]["id"] == root.id
        assert client.post("/api/chat/turns", json={**request, "schedule_timezone": "UTC"}).status_code == 409
