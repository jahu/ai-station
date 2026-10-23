import sys
import time
from datetime import timedelta
from uuid import uuid4

from ai_station_runner import app as host_app
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.recovery import recover_stale
from app.resources import active_locks, reserve_gpu
from app.runner_client import RunnerClient
from app.runs import claim_next, transition
from fastapi.testclient import TestClient
from test_images import bridge as bridge
from test_music import body
from test_music import music_bridge as music_bridge


def test_expired_queued_media_never_dispatches_a_process(music_bridge, monkeypatch):
    with TestClient(app) as client:
        run = client.post("/api/audio/music/runs", json=body()).json()
        with session_factory()() as session:
            row = session.get(Run, run["id"])
            row.parameters = {
                **row.parameters,
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            session.commit()

            def forbidden(*args, **kwargs):
                raise AssertionError("An expired media job attempted native dispatch")

            monkeypatch.setattr(RunnerClient, "request", forbidden)
            assert tick(session, "expired-media") == row.id
            session.refresh(row)
            assert row.status == "canceled" and not active_locks(session)
            assert not row.metadata_json.get("dispatch_attempted")


def test_running_media_carries_its_deadline_and_releases_resources_after_owned_stop(
    music_bridge, monkeypatch
):
    from app import heartbeat
    from app.music import MusicExecutor

    deadline = utcnow() + timedelta(seconds=60)
    original_start = MusicExecutor._start

    def start_then_expire(self, runner, run, allocated, output):
        # Exercise expiry only after the native process has actually accepted its
        # budget. A 0.5s wall-clock budget could expire before dispatch on busy CI,
        # correctly canceling without creating the ownership record this test needs.
        started = original_start(self, runner, run, allocated, output)
        monkeypatch.setattr(heartbeat, "utcnow", lambda: deadline + timedelta(seconds=1))
        return started

    monkeypatch.setattr(MusicExecutor, "_start", start_then_expire)
    with TestClient(app) as client:
        run = client.post("/api/audio/music/runs", json=body(caption="wait")).json()
        with session_factory()() as session:
            row = session.get(Run, run["id"])
            row.parameters = {**row.parameters, "execution_deadline_at": deadline.isoformat()}
            session.commit()
            tick(session, "budgeted-media")
            session.refresh(row)
            assert row.status == "canceled" and not active_locks(session)
            inspected = host_app.manager().inspect(row.id)
            assert not inspected["alive"] and inspected["deadline_at"] == deadline.timestamp()
        assert client.get("/api/artifacts", params={"run_id": run["id"]}).json() == []


def test_native_budget_expires_without_any_control_plane_worker(music_bridge):
    run_id = str(uuid4())
    response = music_bridge.post(
        "/v1/runs/music",
        json={
            "run_id": run_id,
            "caption": "wait",
            "duration_seconds": 10,
            "seed": 42,
            "gpu": 7,
            "permissions": ["filesystem_read", "workspace_write"],
            "deadline_at": time.time() + 0.4,
        },
    )
    assert response.status_code == 200, response.text
    until = time.monotonic() + 4
    while time.monotonic() < until:
        inspected = host_app.manager().inspect(run_id)
        if not inspected["alive"] and not inspected["completion_pending"]:
            break
        time.sleep(0.02)
    assert inspected["status"] == "canceled" and not inspected["alive"]
    assert inspected["deadline_exceeded_at"] >= inspected["deadline_at"]


def test_expired_stale_worker_cancels_only_the_owned_media_and_confirms_cleanup(music_bridge):
    with TestClient(app) as client:
        run_id = client.post("/api/audio/music/runs", json=body(caption="wait")).json()["id"]
        with session_factory()() as session:
            run = claim_next(session, "lost-media-worker")
            assert run.id == run_id
            transition(session, run, "preparing", event_type="executor.preparing")
            assert reserve_gpu(session, run, [7]) == "7"
            session.commit()
            process = music_bridge.post(
                "/v1/runs/music",
                json={
                    "run_id": run_id,
                    **{
                        key: run.parameters[key]
                        for key in ("caption", "lyrics", "instrumental", "duration_seconds", "seed")
                    },
                    "gpu": 7,
                    "permissions": run.effective_permissions,
                },
            ).json()
            transition(session, run, "running", event_type="executor.started")
            run.pid = process["pid"]
            run.parameters = {
                **run.parameters,
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            }
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recover_stale(session)
            session.commit()
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recover_stale(session)
            session.commit()
            session.refresh(run)
            assert run.status == "canceled" and not active_locks(session)
            assert not host_app.manager().inspect(run_id)["alive"]


def test_public_music_form_cannot_supply_an_internal_execution_deadline():
    with TestClient(app) as client:
        response = client.post("/api/audio/music/runs", json=body(execution_deadline_at=utcnow().isoformat()))
        assert response.status_code == 422


def test_photo_pipeline_receives_the_same_owned_native_budget(bridge, monkeypatch):
    # The fixture configures a temporary fake pipeline; no real image model is
    # started. Keep typed request/path/permission handling and ProcessManager.
    monkeypatch.setattr(
        host_app,
        "build_photo_argv",
        lambda *args, **kwargs: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    with TestClient(app) as client:
        response = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "Piano"})
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            run = session.get(Run, response.json()["id"])
            run.parameters = {
                **run.parameters,
                "execution_deadline_at": (utcnow() + timedelta(seconds=0.5)).isoformat(),
            }
            session.commit()
            tick(session, "photo-budget")
            session.refresh(run)
            inspected = host_app.manager().inspect(run.id)
            assert run.status == "canceled" and not inspected["alive"]
            assert inspected["deadline_at"] and not active_locks(session)
