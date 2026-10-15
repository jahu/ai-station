import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import av
import pytest
from ai_station_runner import app as host_app
from ai_station_runner import video as host_video
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, RunDependency
from app.resources import active_locks
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_media_jobs import bridge as bridge


def post_job(client, *, mode="shots", seconds=5, gpu="auto"):
    body = {
        "client_request_id": str(uuid4()),
        "prompt": "Independent shots",
        "duration_seconds": seconds,
        "composition_mode": mode,
        "gpu": gpu,
        "width": 128,
        "height": 128,
        "steps": 4,
    }
    r = client.post("/api/media/jobs/video", json=body)
    assert r.status_code == 202, r.text
    assert client.post("/api/media/jobs/video", json=body).json() == r.json()
    return r.json()["task_id"]


def work(name):
    with session_factory()() as session:
        return tick(session, name)


def view(client, task_id):
    r = client.get("/api/media/jobs/" + task_id)
    assert r.status_code == 200, r.text
    return r.json()


def stage_ids(client, tid):
    rows = client.get("/api/media/jobs/" + tid + "/stages").json()
    segments = sorted(
        (r for r in rows if r["executor_type"] == "wan_video"),
        key=lambda r: r["parameters"]["media_segment"]["index"],
    )
    compose = next(r for r in rows if r["executor_type"] == "media_compose")
    return [r["id"] for r in segments], compose["id"]


def await_state(client, tid, predicate, futures=()):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        for future in futures:
            if future.done() and future.exception():
                raise future.exception()
        value = view(client, tid)
        if predicate(value):
            return value
        time.sleep(0.02)
    raise AssertionError(value)


def hold_videos(monkeypatch, *, devices=(2, 7), available=64000):
    def hardware(_):
        return {"gpus": [{"index": i} for i in devices], "memory": {"available_mib": available}}

    monkeypatch.setattr(host_app, "collect", hardware)
    monkeypatch.setattr(host_video, "collect", hardware)
    original = host_app.start_video
    gates = {}

    def held(manager, body):
        rid = str(body.run_id)
        gate = host_app.get_settings().host_data_dir() / ("gate-" + rid)
        gates[rid] = gate
        ordinal = len(gates)

        def start(**kwargs):
            argv = list(kwargs["argv"])
            argv[2] = (
                "from pathlib import Path\nimport time\n"
                + f"while not Path({str(gate)!r}).exists(): time.sleep(.02)\n"
                + argv[2].replace("50+n%150", str(70 if ordinal == 1 else 130))
            )
            return manager.start(**{**kwargs, "argv": argv})

        return original(SimpleNamespace(start=start), body)

    monkeypatch.setattr(host_app, "start_video", held)
    return gates


@pytest.mark.parametrize("mode", ["shots", "continuous"])
def test_shot_dependencies_and_resume_keep_only_required_motion_edges(bridge, mode):
    with TestClient(app) as client:
        tid = post_job(client, mode=mode, seconds=8)
        segments, compose = stage_ids(client, tid)
        for revision in (1, 2):
            with session_factory()() as session:
                edges = {
                    (r.run_id, r.prerequisite_id)
                    for r in session.scalars(
                        select(RunDependency).where(RunDependency.run_id.in_([*segments, compose]))
                    )
                }
            expected = {(compose, rid) for rid in segments}
            if mode == "continuous":
                expected |= set(zip(segments[1:], segments[:-1]))
            assert edges == expected
            if revision == 1:
                assert client.post("/api/media/jobs/" + tid + "/cancel").status_code == 200
                r = client.post(
                    "/api/media/jobs/" + tid + "/resume",
                    json={"expected_revision": 1, "client_request_id": str(uuid4())},
                )
                assert r.status_code == 202, r.text
                with session_factory()() as session:
                    from app.models import Task

                    plan = session.get(Task, tid).metadata_json["media_plan"]
                    old_segments = segments
                    segments, compose = plan["segment_run_ids"], plan["compose_run_id"]
                assert set(segments).isdisjoint(old_segments)


@pytest.mark.parametrize("stop", [False, True])
def test_parallel_shots_use_distinct_devices_and_task_stop_or_ordered_composition(bridge, monkeypatch, stop):
    gates = hold_videos(monkeypatch)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        tid = post_job(client, seconds=8 if stop else 5)
        ids, compose = stage_ids(client, tid)
        first = pool.submit(work, "first-shot")
        second = None
        try:
            await_state(client, tid, lambda x: x["running_segments"] == 1, [first])
            second = pool.submit(work, "second-shot")
            current = await_state(client, tid, lambda x: x["running_segments"] == 2, [first, second])
            assert {x["gpu"] for x in current["active_segments"]} == {"2", "7"}
            assert {x["run_id"] for x in current["active_segments"]} == set(ids[:2])
            assert current["queued_segments"] == (1 if stop else 0)
            assert client.get("/api/runs/" + compose).json()["status"] == "queued"
            with session_factory()() as session:
                assert {"gpu:2", "gpu:7"} <= active_locks(session)
            if stop:
                assert client.post("/api/media/jobs/" + tid + "/cancel").status_code == 200
                first.result(timeout=15)
                second.result(timeout=15)
                current = view(client, tid)
                assert (
                    current["status"] == "canceled"
                    and not current["active_run_ids"]
                    and not current["active_segments"]
                )
                assert len(bridge) == 2
                for rid in ids[:2]:
                    assert not host_app.manager().inspect(rid)["alive"]
                with session_factory()() as session:
                    assert not active_locks(session)
            else:
                gates[ids[1]].touch()
                second.result(timeout=15)
                current = view(client, tid)
                assert current["completed_segments"] == 1 and current["running_segments"] == 1
                assert current["status"] == "generating" and current["final_artifact_id"] is None
                with session_factory()() as session:
                    assert current["preview_artifact_id"] == session.scalar(
                        select(Artifact.id).where(Artifact.run_id == ids[1])
                    )
                gates[ids[0]].touch()
                first.result(timeout=15)
                with session_factory()() as session:
                    assert view(client, tid)["preview_artifact_id"] == session.scalar(
                        select(Artifact.id).where(Artifact.run_id == ids[0])
                    )
                work("ordered-compose")
                current = view(client, tid)
                assert current["status"] == "succeeded", current
                with session_factory()() as session:
                    artifact = session.get(Artifact, current["final_artifact_id"])
                    parents = [
                        session.scalar(select(Artifact).where(Artifact.run_id == rid)).id for rid in ids
                    ]
                    assert artifact.parent_artifact_ids == parents
                    path = host_app.get_settings().host_data_dir() / artifact.relative_path
                    assert not active_locks(session)
                with av.open(str(path)) as c:
                    values = [bytes(f.planes[0])[0] for f in c.decode(video=0)]
                assert len(values) == 120 and abs(values[0] - 70) <= 3 and abs(values[81] - 130) <= 3
        finally:
            for gate in gates.values():
                gate.touch()
            first.result(timeout=15)
            if second is not None:
                second.result(timeout=15)


@pytest.mark.parametrize("constraint", ["one_gpu", "ram", "explicit_gpu"])
def test_independent_shots_remain_serial_when_resources_do_not_fit(bridge, monkeypatch, constraint):
    gates = hold_videos(monkeypatch, devices=(7,) if constraint == "one_gpu" else (2, 7))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        tid = post_job(client, gpu="7" if constraint == "explicit_gpu" else "auto")
        ids, _ = stage_ids(client, tid)
        if constraint == "ram":
            required = client.get("/api/runs/" + ids[0]).json()["requested_resources"]["ram_mib"]
            monkeypatch.setattr(
                host_app,
                "collect",
                lambda _: {
                    "gpus": [{"index": 2}, {"index": 7}],
                    "memory": {"available_mib": required * 2 + 1023},
                },
            )
        first = pool.submit(work, "limited-first")
        try:
            await_state(client, tid, lambda x: x["running_segments"] == 1, [first])
            work("limited-second")
            current = view(client, tid)
            assert current["running_segments"] == 1 and current["queued_segments"] == 1 and len(bridge) == 1
            if constraint == "explicit_gpu":
                assert current["active_segments"][0]["gpu"] == "7"
            assert client.get("/api/runs/" + ids[1]).json()["status"] == "queued"
        finally:
            for gate in gates.values():
                gate.touch()
            first.result(timeout=15)
        # Once the first owned process exits, the next shot can use its resources.
        gates.clear()
        original = host_app.start_video

        def released(manager, body):
            result = original(manager, body)
            gates[str(body.run_id)].touch()
            return result

        monkeypatch.setattr(host_app, "start_video", released)
        work("limited-next")
        work("limited-compose")
        assert view(client, tid)["status"] == "succeeded"


def test_shot_resume_reuses_successes_after_failed_gap_and_preserves_seeds(bridge, monkeypatch):
    from app.models import Run, Task

    original = host_app.start_video
    calls = []

    def fail_once(manager, body):
        calls.append(str(body.run_id))
        if len(calls) == 1:
            return manager.start(
                run_id=str(body.run_id),
                argv=[sys.executable, "-c", "raise SystemExit(3)"],
                cwd=host_app.get_settings().host_data_dir(),
                executor="wan_video",
            )
        return original(manager, body)

    monkeypatch.setattr(host_app, "start_video", fail_once)
    with TestClient(app) as client:
        tid = post_job(client, seconds=8)
        old, _ = stage_ids(client, tid)
        for index in range(4):
            work(f"gap-{index}")
        current = view(client, tid)
        assert current["status"] == "failed" and current["completed_segments"] == 2
        assert current["resume_allowed"] and not current["active_run_ids"]
        with session_factory()() as session:
            seed = session.get(Run, old[0]).parameters["media_segment"]["seed"]
            previous_artifacts = {
                r.run_id: r.id for r in session.scalars(select(Artifact).where(Artifact.run_id.in_(old[1:])))
            }
        receipt = {"client_request_id": str(uuid4()), "expected_revision": 1}
        response = client.post("/api/media/jobs/" + tid + "/resume", json=receipt)
        assert response.status_code == 202, response.text
        assert client.post("/api/media/jobs/" + tid + "/resume", json=receipt).json() == response.json()
        with session_factory()() as session:
            plan = session.get(Task, tid).metadata_json["media_plan"]
            selected = plan["segment_run_ids"]
            assert selected[0] != old[0] and selected[1:] == old[1:]
            assert session.get(Run, selected[0]).parameters["media_segment"]["seed"] == seed
            assert not list(session.scalars(select(RunDependency).where(RunDependency.run_id == selected[0])))
        work("resume-only-gap")
        work("compose-resumed-shots")
        current = view(client, tid)
        assert current["status"] == "succeeded" and len(calls) == 4
        with session_factory()() as session:
            assert session.get(Run, old[0]).status == "failed"
            final = session.get(Artifact, current["final_artifact_id"])
            assert final.metadata_json["frames"] == 192
            assert final.parent_artifact_ids[1:] == [previous_artifacts[rid] for rid in old[1:]]
            assert not active_locks(session)
