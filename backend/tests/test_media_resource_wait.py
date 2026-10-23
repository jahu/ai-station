"""Admission observations survive polling without dispatching or changing budgets."""

from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks, memory_observation, reserve_memory
from app.runner_client import RunnerClient
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from test_media_jobs import bridge as bridge


@pytest.mark.parametrize("available", [None, 12272])
def test_wait_observation_is_reported_then_cleared_after_admission(bridge, monkeypatch, available):
    with TestClient(app) as client:
        response = client.post(
            "/api/media/jobs/video",
            json={
                "client_request_id": str(uuid4()),
                "prompt": "Test",
                "duration_seconds": 1,
                "width": 128,
                "height": 128,
                "steps": 4,
            },
        )
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        assert response.json()["resource_wait"] is None
        rid = client.get(f"/api/media/jobs/{tid}/stages").json()[0]["id"]
        with session_factory()() as session:
            run = session.get(Run, rid)
            run.requested_resources = {"ram_mib": 16384}
            session.commit()
        monkeypatch.setattr(
            RunnerClient,
            "hardware",
            lambda _: {"gpus": [{"index": 7}], "memory": {"available_mib": available}},
        )
        with session_factory()() as session:
            assert tick(session, "resource-observer") == rid
            assert not active_locks(session)
        waiting = client.get(f"/api/runs/{rid}").json()
        observed = waiting["resource_wait"]
        assert waiting["status"] == "queued" and not waiting["metadata"].get("dispatch_attempted")
        assert observed == {
            "run_id": rid,
            "reason": "memory",
            "checked_at": observed["checked_at"],
            "required_mib": 16384,
            "available_mib": available,
            "reserved_mib": 0,
            "headroom_mib": 1024,
        }
        assert client.get(f"/api/media/jobs/{tid}").json()["resource_wait"] == observed
        events = client.get(f"/api/runs/{rid}/events").json()
        event = next(event for event in events if event["event_type"] == "run.interrupted")
        assert event["payload"]["resource_wait"]["available_mib"] == available
        assert not bridge
        monkeypatch.setattr(
            RunnerClient, "hardware", lambda _: {"gpus": [{"index": 7}], "memory": {"available_mib": 64000}}
        )
        with session_factory()() as session:
            assert tick(session, "resources-now-available") == rid
        finished = client.get(f"/api/runs/{rid}").json()
        assert finished["status"] == "succeeded" and finished["resource_wait"] is None
        assert "resource_wait" not in finished["metadata"]
        assert client.get(f"/api/media/jobs/{tid}").json()["resource_wait"] is None
        assert bridge == [rid]


def test_observation_accounts_for_other_reservations_without_changing_admission(session):
    task = create_task(session, title="RAM", prompt="", capability="test")
    first = create_run(session, task, run_type="test", capability="test", executor_type="fake")
    second = create_run(session, task, run_type="test", capability="test", executor_type="fake")
    assert reserve_memory(session, first, 32000, 16000)
    observed = memory_observation(session, second, 32000, 16000)
    assert observed == {
        "required_mib": 16000,
        "available_mib": 32000,
        "reserved_mib": 16000,
        "headroom_mib": 1024,
    }
    assert not reserve_memory(session, second, 32000, 16000)
    assert memory_observation(session, first, 32000, 16000)["reserved_mib"] == 0


def test_stopped_and_running_runs_never_present_old_wait_as_current(session):
    from app.resources import latest_resource_wait
    from app.runs import run_dict

    task = create_task(session, title="RAM", prompt="", capability="test")
    run = create_run(session, task, run_type="test", capability="test", executor_type="fake")
    run.metadata_json = {"resource_wait": {"reason": "memory", "checked_at": "2026-10-23T12:00:00+00:00"}}
    assert run_dict(run)["resource_wait"]["reason"] == "memory"
    for status in ["running", "cancel_requested", "canceled", "failed", "succeeded", "interrupted"]:
        run.status = status
        assert run_dict(run)["resource_wait"] is None
        assert latest_resource_wait([run]) is None
