from concurrent.futures import ThreadPoolExecutor

from ai_station_runner import app as host_app
from app.api import app
from app.db import session_factory
from app.models import Task
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from test_parallel_media_shots import (
    await_state,
    hold_videos,
    post_job,
    view,
    work,
)
from test_parallel_media_shots import (
    bridge as bridge,
)


def test_resource_blocked_shot_batch_does_not_hide_a_new_cpu_run(bridge, monkeypatch):
    original_video = host_app.start_video
    gates = hold_videos(monkeypatch, devices=(7,))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        tid = post_job(client, seconds=60)
        first = pool.submit(work, "held-first-shot")
        try:
            await_state(client, tid, lambda item: item["running_segments"] == 1, [first])
            with session_factory()() as session:
                task = create_task(session, title="Interactive CPU task", prompt="", capability="test")
                cpu = create_run(session, task, run_type="test", capability="test", executor_type="fake")
                cpu_id = cpu.id
                session.commit()
            # One attempt observes the held GPU. The remaining older shots must
            # then yield to independent CPU work, rather than occupying every tick.
            blocked_id = work("observe-resource-wait")
            events = client.get("/api/runs/" + blocked_id + "/events").json()
            deferred = [event for event in events if event["event_type"] == "run.requeued"]
            assert deferred[-1]["payload"]["resource_wait_until"]
            observed = client.get("/api/runs/" + blocked_id).json()["resource_wait"]
            assert observed["reason"] == "gpu" and observed["run_id"] == blocked_id
            assert view(client, tid)["resource_wait"] == observed
            assert len(bridge) == 1
            assert work("interactive-next-tick") == cpu_id
            assert client.get("/api/runs/" + cpu_id).json()["status"] == "succeeded"
            assert view(client, tid)["running_segments"] == 1
        finally:
            for gate in gates.values():
                gate.touch()
            first.result(timeout=15)
        # Finishing the owned shot frees capacity immediately; the batch does not
        # wait for an old backoff timer after the resource is actually released.
        with session_factory()() as session:
            assert not session.get(Task, tid).metadata_json.get("resource_wait_until")
        monkeypatch.setattr(host_app, "start_video", original_video)
        work("next-shot-after-release")
        assert len(bridge) == 2


def test_deferred_media_allows_same_task_cpu_work_and_expires_without_changing_queue_time(
    session, monkeypatch
):
    from datetime import datetime, timedelta

    from app import media_admission, runs
    from app.db import utcnow
    from app.media_admission import WAIT_KEY, defer_media_task

    task = create_task(session, title="Shot task", prompt="", capability="video.long")
    shot = create_run(
        session,
        task,
        run_type="video",
        capability="video.generate",
        executor_type="wan_video",
        requested_gpu="auto",
        parameters={"internal_media": True},
    )
    task.metadata_json = {"media_plan": {"kind": "video", "mode": "shots", "segment_run_ids": [shot.id]}}
    cpu = create_run(session, task, run_type="test", capability="test", executor_type="fake")
    session.commit()
    queued = shot.queued_at
    moment = utcnow()
    monkeypatch.setattr(media_admission, "utcnow", lambda: moment)
    assert defer_media_task(session, shot)
    session.commit()
    deadline = datetime.fromisoformat(task.metadata_json[WAIT_KEY])
    monkeypatch.setattr(runs, "utcnow", lambda: deadline - timedelta(microseconds=1))
    assert runs.claim_next(session, "cpu").id == cpu.id
    session.commit()
    assert runs.claim_next(session, "not-yet") is None
    monkeypatch.setattr(runs, "utcnow", lambda: deadline + timedelta(microseconds=1))
    assert runs.claim_next(session, "eligible").id == shot.id
    assert shot.queued_at == queued


def test_atomic_claim_rechecks_media_deferral_after_candidate_was_selected(session, monkeypatch):
    from datetime import timedelta

    from app.db import utcnow
    from app.media_admission import WAIT_KEY
    from app.runs import claim_next

    task = create_task(session, title="Shots", prompt="", capability="video.long")
    shot = create_run(
        session,
        task,
        run_type="video",
        capability="video.generate",
        executor_type="wan_video",
        requested_gpu="auto",
    )
    sid, tid = shot.id, task.id
    session.commit()
    original = session.scalar
    changed = False

    def candidate_then_defer(statement, *args, **kwargs):
        nonlocal changed
        result = original(statement, *args, **kwargs)
        if not changed and getattr(result, "id", None) == sid:
            changed = True
            # SQLite serializes the normal selection transaction. Explicitly
            # release it to inject a stale candidate and exercise the UPDATE guard.
            session.commit()
            with session_factory()() as other:
                current = other.get(Task, tid)
                current.metadata_json = {WAIT_KEY: (utcnow() + timedelta(seconds=30)).isoformat()}
                other.commit()
        return result

    monkeypatch.setattr(session, "scalar", candidate_then_defer)
    assert claim_next(session, "stale-candidate") is None
    assert changed
    session.refresh(shot)
    assert shot.status == "queued" and shot.worker_id is None


def test_finishing_a_shot_never_leaves_a_task_write_lock_open(bridge):
    import sqlite3

    from app.engine import tick

    with TestClient(app) as client:
        post_job(client, seconds=1)
        with session_factory()() as session:
            tick(session, "finish-no-marker")
            with sqlite3.connect(session.bind.url.database, timeout=0.2) as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()


def test_stop_during_resource_rejection_cannot_requeue_a_stopped_shot(bridge, monkeypatch):
    from app import host_media_executor

    with TestClient(app) as client:
        tid = post_job(client)

        def refuse_after_stop(session, run, *args):
            from app.task_control import cancel_task

            # Inject the existing Stop service at the admission boundary. Current
            # SQLite holds BEGIN IMMEDIATE here, so a second writer would wait.
            cancel_task(session, run.task)
            return False

        monkeypatch.setattr(host_media_executor, "reserve_memory", refuse_after_stop)
        work("stop-during-admission")
        result = view(client, tid)
        assert result["status"] == "canceled" and not result["active_run_ids"] and not bridge
        with session_factory()() as session:
            assert session.get(Task, tid).metadata_json["stop_requested_at"]
            assert not session.get(Task, tid).metadata_json.get("resource_wait_until")
