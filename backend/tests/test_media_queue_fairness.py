from concurrent.futures import ThreadPoolExecutor

from ai_station_runner import app as host_app
from app.api import app
from app.db import session_factory
from app.models import Task
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from test_parallel_media_shots import (
    await_state,
    bridge as bridge,
    hold_videos,
    post_job,
    view,
    work,
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
            work("observe-resource-wait")
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
            assert not session.get(Task, tid).metadata_json.get("media_resource_wait_until")
        monkeypatch.setattr(host_app, "start_video", original_video)
        work("next-shot-after-release")
        assert len(bridge) == 2
