"""Actual API/worker/Artifact graph with fake native inference and real CPU media."""

import hashlib
import json
import wave
from fractions import Fraction
from uuid import uuid4

import av
import pytest
from ai_station_runner.sonic_jobs import WholeAvatarRequest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run, Task
from app.resources import active_locks
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_whole_avatars import PROFILE
from test_whole_avatars import sources as sources


def fake_movie(path, body, root):
    observed = body["observed_input"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as movie:
        video = movie.add_stream("libx264", rate=25)
        video.width, video.height, video.pix_fmt = observed["width"], observed["height"], "yuv420p"
        sound = movie.add_stream("aac", rate=observed["sample_rate"])
        sound.layout = "mono"
        for index in range(observed["target_frames"]):
            frame = av.VideoFrame(video.width, video.height, "yuv420p")
            frame.pts, frame.time_base = index, Fraction(1, 25)
            for plane in frame.planes:
                plane.update(b"\x80" * plane.buffer_size)
            for packet in video.encode(frame):
                movie.mux(packet)
        for packet in video.encode():
            movie.mux(packet)
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=observed["sample_rate"])
        with av.open(str(root / body["audio"]["relative_path"])) as source:
            for decoded in source.decode(audio=0):
                for frame in resampler.resample(decoded):
                    for packet in sound.encode(frame):
                        movie.mux(packet)
        for frame in resampler.resample(None):
            for packet in sound.encode(frame):
                movie.mux(packet)
        for packet in sound.encode():
            movie.mux(packet)
    report = {
        "version": 1,
        "verified": True,
        "run_id": body["run_id"],
        "backend": "sonic",
        "recipe": body["recipe"],
        "observed_input": observed,
        "input_sha256": {key: body[key]["sha256"] for key in ("portrait", "audio")},
        "video_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    path.with_suffix(".json").write_text(json.dumps(report))


@pytest.fixture
def bridge(monkeypatch, session, sources):
    identifiers = [artifact.id for artifact in sources]
    session.commit()
    state = {"whole": [], "speech": [], "records": {}, "fail": False, "hold": False, "cancel_task": None}

    def request(self, method, path, body=None):
        if (method, path) == ("GET", "/v1/avatar/whole-capabilities"):
            return PROFILE
        if (method, path) == ("GET", "/v1/audio/capabilities"):
            return {"available": True, "languages": ["pl"]}
        assert method == "POST" and path in {"/v1/runs/whole-avatar", "/v1/runs/audio"}, (method, path)
        root, identifier = get_settings().data_dir, body["run_id"]
        target = root / f"artifacts/{identifier[:2]}/{identifier[2:4]}/{identifier}"
        if path.endswith("whole-avatar"):
            WholeAvatarRequest.model_validate(body)
            state["whole"].append(body)
            if not state["fail"]:
                fake_movie(target.with_suffix(".mp4"), body, root)
            executor, code = "sonic_whole", 1 if state["fail"] else 0
        else:
            state["speech"].append(body)
            output = target.with_suffix(".wav")
            output.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00" * (24000 * 2))
            executor, code = "chatterbox", 0
        record = {
            "pid": 777,
            "process_group_id": 777,
            "runner_id": "fake-native",
            "executor": executor,
            "exit_code": code,
            "alive": state["hold"],
        }
        state["records"][identifier] = record
        return record

    def inspect(self, identifier, **offsets):
        record = state["records"][identifier]
        if state["cancel_task"]:
            from app.task_control import cancel_task

            with session_factory()() as db:
                cancel_task(db, db.get(Task, state["cancel_task"]))
                db.commit()
            state["cancel_task"] = None
        return {
            **record,
            "status": "canceled" if record["exit_code"] == -15 else "exited",
            "completion_pending": False,
            "stdout": "",
            "stderr": "",
            "stderr_tail": "Fake native failure" if record["exit_code"] == 1 else "",
            "stdout_offset": 0,
            "stderr_offset": 0,
            "stdout_more": False,
            "stderr_more": False,
        }

    def cancel(self, identifier):
        state["records"][identifier].update(alive=False, exit_code=-15)
        return inspect(self, identifier)

    monkeypatch.setattr(RunnerClient, "request", request)
    monkeypatch.setattr(RunnerClient, "inspect_process", inspect)
    monkeypatch.setattr(RunnerClient, "cancel_process", cancel)
    monkeypatch.setattr(
        RunnerClient,
        "hardware",
        lambda self: {
            "gpus": [{"index": i, "memory_total_mib": 12288, "memory_used_mib": 200} for i in [7, 11]],
            "memory": {"available_mib": 32768},
        },
    )
    return identifiers, state


def body(identifiers, **changes):
    return {
        "client_request_id": str(uuid4()),
        "image_artifact_id": identifiers[0],
        "audio_artifact_id": identifiers[1],
        "generation_profile": PROFILE["recipe"]["id"],
        **changes,
    }


def drain():
    for index in range(10):
        with session_factory()() as db:
            if tick(db, "whole-fake-" + str(index)) is None:
                return
    pytest.fail("Whole-recording fake workflow did not drain")


def test_manual_whole_recording_is_one_normal_run_with_actual_library_output(bridge):
    identifiers, state = bridge
    with TestClient(app) as client:
        accepted = client.post("/api/media/jobs/avatar", json=body(identifiers))
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()
        assert job["mode"] == "whole_recording" and job["total_stages"] == 1
        assert job["total_segments"] == 0
        drain()
        result = client.get("/api/media/jobs/" + job["task_id"]).json()
        assert result["status"] == "succeeded" and result["completed_stages"] == 1, result
        artifact = client.get("/api/artifacts/" + result["final_artifact_id"]).json()
        assert artifact["metadata"]["verified"] is True and artifact["metadata"]["backend"] == "sonic"
        assert artifact["parent_artifact_ids"] == identifiers
        assert not artifact["metadata"].get("internal_media")
        assert any(item["id"] == artifact["id"] for item in client.get("/api/artifacts").json())
    assert len(state["whole"]) == 1 and not state["speech"]
    with session_factory()() as db:
        plan = db.get(Task, job["task_id"]).metadata_json["media_plan"]
        assert plan["version"] == 2 and not plan.get("compose_run_id") and not plan.get("segment_run_ids")
        runs = list(db.scalars(select(Run).where(Run.task_id == job["task_id"])))
        assert [run.executor_type for run in runs] == ["sonic_whole"] and not active_locks(db)


def test_conversation_uses_the_ready_whole_engine_and_returns_its_final_film(bridge):
    identifiers, state = bridge
    with TestClient(app) as client:
        conversation = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "work"}
        ).json()
        path = f"/api/chat/conversations/{conversation['id']}"
        response = client.post(
            path + "/messages",
            json={
                "content": "Animate this portrait",
                "action": "avatar.animate",
                "image_artifact_ids": identifiers[:1],
                "audio_artifact_id": identifiers[1],
            },
        )
        assert response.status_code == 202, response.text
        drain()
        message = client.get(path).json()["messages"][-1]
        assert message["media_job"]["mode"] == "whole_recording"
        assert message["media_job"]["status"] == "succeeded", message
        assert len(message["artifacts"]) == 1
        assert message["artifacts"][0]["metadata"]["verified"] is True
    assert len(state["whole"]) == 1


def test_send_receipt_returns_the_same_plan_and_rejects_changed_intent(bridge):
    identifiers, state = bridge
    request = body(identifiers)
    with TestClient(app) as client:
        first = client.post("/api/media/jobs/avatar", json=request)
        second = client.post("/api/media/jobs/avatar", json=request)
        assert first.status_code == second.status_code == 202 and first.json() == second.json()
        assert client.post("/api/media/jobs/avatar", json={**request, "seed": 44}).status_code == 409
    assert not state["whole"]


def test_generated_speech_is_bound_to_its_exact_owned_planner_and_complete_movie(bridge):
    identifiers, state = bridge
    with TestClient(app) as client:
        response = client.post(
            "/api/media/jobs/avatar", json=body(identifiers, speech_text="Neutral test speech.")
        )
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["total_stages"] == 2 and job["status"] == "preparing"
        drain()
        final = client.get("/api/media/jobs/" + job["task_id"]).json()
        assert final["status"] == "succeeded" and final["total_stages"] == final["completed_stages"] == 3, (
            final
        )
    assert len(state["speech"]) == len(state["whole"]) == 1
    with session_factory()() as db:
        plan = db.get(Task, job["task_id"]).metadata_json["media_plan"]
        speech, animation = db.get(Run, plan["speech_run_id"]), db.get(Run, plan["whole_run_id"])
        assert animation.parent_run_id == plan["planner_run_id"]
        audio = db.get(Artifact, plan["canonical_audio_id"])
        assert audio.run_id == speech.id and audio.id != identifiers[1]
        assert animation.parameters["observed_input"]["samples"] == 24000
        assert animation.parameters["execution_deadline_at"] == speech.parameters["execution_deadline_at"]


def test_failed_generation_resumes_with_new_run_and_same_frozen_sources(bridge):
    identifiers, state = bridge
    state["fail"] = True
    with TestClient(app) as client:
        job = client.post("/api/media/jobs/avatar", json=body(identifiers)).json()
        drain()
        failed = client.get("/api/media/jobs/" + job["task_id"]).json()
        assert failed["status"] == "failed" and failed["resume_allowed"]
        request = {"client_request_id": str(uuid4()), "expected_revision": 1}
        resumed = client.post("/api/media/jobs/" + job["task_id"] + "/resume", json=request)
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["revision"] == 2 and resumed.json()["whole_run_id"] != failed["whole_run_id"]
        assert (
            client.post("/api/media/jobs/" + job["task_id"] + "/resume", json=request).json()
            == resumed.json()
        )
        state["fail"] = False
        drain()
        assert client.get("/api/media/jobs/" + job["task_id"]).json()["status"] == "succeeded"
    assert len(state["whole"]) == 2
    assert state["whole"][0]["recipe"] == state["whole"][1]["recipe"]
    assert state["whole"][0]["portrait"] == state["whole"][1]["portrait"]


def test_task_stop_before_dispatch_never_launches_a_model(bridge):
    identifiers, state = bridge
    with TestClient(app) as client:
        job = client.post("/api/media/jobs/avatar", json=body(identifiers)).json()
        stopped = client.post("/api/media/jobs/" + job["task_id"] + "/cancel")
        assert stopped.status_code == 200
        drain()
        assert client.get("/api/media/jobs/" + job["task_id"]).json()["status"] == "canceled"
    assert not state["whole"]


def test_stop_during_native_execution_does_not_publish_even_an_existing_output_file(bridge):
    identifiers, state = bridge
    state["hold"] = True
    with TestClient(app) as client:
        job = client.post("/api/media/jobs/avatar", json=body(identifiers)).json()
        state["cancel_task"] = job["task_id"]
        drain()
        final = client.get("/api/media/jobs/" + job["task_id"]).json()
        assert final["status"] == "canceled" and final["final_artifact_id"] is None
    with session_factory()() as db:
        assert not active_locks(db)
        assert not list(db.scalars(select(Artifact).where(Artifact.run_id == job["whole_run_id"])))


@pytest.mark.parametrize("fault", ["missing", "wrong-source", "changed-video"])
def test_unverified_native_output_never_becomes_a_library_result(bridge, monkeypatch, fault):
    original = fake_movie

    def corrupt(path, body, root):
        original(path, body, root)
        report = path.with_suffix(".json")
        if fault == "missing":
            report.unlink()
        elif fault == "wrong-source":
            value = json.loads(report.read_text())
            value["input_sha256"]["portrait"] = "f" * 64
            report.write_text(json.dumps(value))
        else:
            with path.open("ab") as output:
                output.write(b"changed after native verification")

    monkeypatch.setattr("test_whole_avatar_jobs.fake_movie", corrupt)
    identifiers, _ = bridge
    with TestClient(app) as client:
        job = client.post("/api/media/jobs/avatar", json=body(identifiers)).json()
        drain()
        final = client.get("/api/media/jobs/" + job["task_id"]).json()
        assert final["status"] == "failed" and final["final_artifact_id"] is None
    with session_factory()() as db:
        assert not active_locks(db)
        assert not list(db.scalars(select(Artifact).where(Artifact.run_id == job["whole_run_id"])))


@pytest.mark.parametrize("fault", ["changed-source", "changed-model", "uncertain-alive"])
def test_resume_cannot_replace_reviewed_inputs_or_repeat_an_uncertain_live_dispatch(
    bridge, monkeypatch, fault
):
    identifiers, state = bridge
    state["fail"] = True
    with TestClient(app) as client:
        job = client.post("/api/media/jobs/avatar", json=body(identifiers)).json()
        drain()
        if fault == "changed-model":
            monkeypatch.setattr(
                "app.whole_avatars.capabilities",
                lambda: {**PROFILE, "recipe": {**PROFILE["recipe"], "observation": "f" * 64}},
            )
        else:
            with session_factory()() as db:
                if fault == "changed-source":
                    artifact = db.get(Artifact, identifiers[0])
                    (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed portrait")
                else:
                    run = db.get(Run, job["whole_run_id"])
                    run.metadata_json = {"dispatch_attempted": True}
                    db.commit()
                    state["records"][run.id]["alive"] = True
        resumed = client.post(
            "/api/media/jobs/" + job["task_id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        assert resumed.status_code == 409, resumed.text
        assert client.get("/api/media/jobs/" + job["task_id"]).json()["revision"] == 1
    assert len(state["whole"]) == 1
