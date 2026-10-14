import sys
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import video as host_video
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run, Task
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_VIDEO_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_COMFY_DIR", str(tmp_path))
    (tmp_path / "nodes.py").touch()
    for key in ("WAN_MODEL", "WAN_TEXT_ENCODER", "WAN_VAE"):
        path = tmp_path / (key + ".safetensors")
        path.touch()
        monkeypatch.setenv("AI_STATION_" + key, str(path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()

    def hardware(_):
        return {"gpus": [{"index": 7}], "memory": {"available_mib": 64000}}

    monkeypatch.setattr(host_app, "collect", hardware)
    monkeypatch.setattr(host_video, "collect", hardware)
    started = []

    def fake_video(manager, body):
        root = host_app.get_settings().host_data_dir()
        rid = str(body.run_id)
        output = root / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        started.append(rid)
        script = """import av,sys
p,count,w,h=sys.argv[1:];count=int(count)
with av.open(p,'w') as c:
 s=c.add_stream('libx264',rate=24);s.width=int(w);s.height=int(h);s.pix_fmt='yuv420p'
 for n in range(count):
  f=av.VideoFrame(int(w),int(h),'yuv420p')
  for plane in f.planes:plane.update(bytes([50+n%150])*plane.buffer_size)
  for packet in s.encode(f):c.mux(packet)
 for packet in s.encode():c.mux(packet)
"""
        return manager.start(
            run_id=rid,
            argv=[
                sys.executable,
                "-c",
                script,
                str(output),
                str(body.frames),
                str(body.width),
                str(body.height),
            ],
            cwd=root,
            executor="wan_video",
        )

    monkeypatch.setattr(host_app, "start_video", fake_video)
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield started
    host_app.manager().shutdown()
    host_app.reset_manager()
    clear_settings_cache()


def test_segmented_job_is_durable_and_finishes_only_after_real_cpu_composition(bridge):
    with TestClient(app) as client:
        body = {
            "client_request_id": str(uuid4()),
            "prompt": "A scene",
            "duration_seconds": 5,
            "width": 128,
            "height": 128,
            "steps": 4,
        }
        response = client.post("/api/media/jobs/video", json=body)
        assert response.status_code == 202, response.text
        view = response.json()
        assert view["status"] == "queued" and view["total_segments"] == 2
        tid = view["task_id"]
        assert client.post("/api/media/jobs/video", json=body).json()["task_id"] == tid
        with session_factory()() as session:
            tick(session, "first")
        partial = client.get("/api/media/jobs/" + tid).json()
        assert partial["completed_segments"] == 1 and partial["status"] != "succeeded"
        for worker in ("second", "compose"):
            with session_factory()() as session:
                tick(session, worker)
        result = client.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded", result
        artifact = client.get("/api/artifacts/" + result["final_artifact_id"]).json()
        assert artifact["metadata"]["frames"] == 120 and artifact["metadata"]["verified"]
        assert len(artifact["parent_artifact_ids"]) == 2
        assert len(client.get("/api/artifacts").json()) == 1
        assert len(client.get("/api/artifacts?include_internal=true").json()) == 3
        assert len(bridge) == 2
        assert client.post("/api/media/jobs/video", json={**body, "prompt": "Other"}).status_code == 409
        with session_factory()() as session:
            assert len(list(session.scalars(select(Task)))) == 1
            assert not active_locks(session)


def test_job_stop_and_resume_reuses_completed_clip_and_receipt(bridge):
    with TestClient(app) as client:
        response = client.post(
            "/api/media/jobs/video",
            json={
                "client_request_id": str(uuid4()),
                "prompt": "Scene",
                "duration_seconds": 5,
                "width": 128,
                "height": 128,
                "steps": 4,
            },
        )
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        with session_factory()() as session:
            tick(session, "partial")
        stopped = client.post("/api/media/jobs/" + tid + "/cancel").json()
        assert stopped["status"] == "canceled" and stopped["completed_segments"] == 1
        values = {"client_request_id": str(uuid4()), "expected_revision": 1}
        resumed = client.post("/api/media/jobs/" + tid + "/resume", json=values)
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["revision"] == 2
        assert client.post("/api/media/jobs/" + tid + "/resume", json=values).json() == resumed.json()
        assert (
            client.post(
                "/api/media/jobs/" + tid + "/resume", json={**values, "expected_revision": 2}
            ).status_code
            == 409
        )
        for worker in ("resume", "compose"):
            with session_factory()() as session:
                tick(session, worker)
        final = client.get("/api/media/jobs/" + tid).json()
        assert final["status"] == "succeeded", final
        assert len(bridge) == 2
        with session_factory()() as session:
            keys = [r.operation_key for r in session.scalars(select(Run))]
            assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "extra",
    [
        {"frames": 81},
        {"duration_seconds": 61},
        {"composition_mode": "loop"},
        {"duration_seconds": True},
    ],
)
def test_unbounded_or_conflicting_media_settings_do_not_publish(bridge, extra):
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/media/jobs/video", json={"client_request_id": str(uuid4()), "prompt": "Scene", **extra}
            ).status_code
            == 422
        )
    with session_factory()() as session:
        assert not list(session.scalars(select(Run)))


@pytest.fixture
def full_avatar_bridge(bridge, tmp_path, monkeypatch):
    from ai_station_runner import audio as native_audio
    from ai_station_runner import avatars as native_avatar

    for key in ("ECHOMIMIC_PYTHON", "CHATTERBOX_PYTHON"):
        monkeypatch.setenv("AI_STATION_" + key, sys.executable)
    for key in ("ECHOMIMIC_DIR", "ECHOMIMIC_MODELS", "CHATTERBOX_CACHE"):
        monkeypatch.setenv("AI_STATION_" + key, str(tmp_path))
    started = []

    def fake_avatar(manager, body):
        root = host_app.get_settings().host_data_dir()
        rid = str(body.run_id)
        output = root / f"artifacts/{rid[:2]}/{rid[2:4]}/{rid}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        started.append(body)
        script = """import av,sys
p,count,size=sys.argv[1:]
with av.open(p,'w') as c:
 s=c.add_stream('libx264',rate=25);s.width=s.height=int(size);s.pix_fmt='yuv420p'
 for n in range(int(count)):
  f=av.VideoFrame(int(size),int(size),'yuv420p')
  for plane in f.planes:plane.update(bytes([60+n])*plane.buffer_size)
  for packet in s.encode(f):c.mux(packet)
 for packet in s.encode():c.mux(packet)
"""
        return manager.start(
            run_id=rid,
            executor="echomimic",
            cwd=root,
            argv=[sys.executable, "-c", script, str(output), str(body.frames), str(body.size)],
        )

    monkeypatch.setattr(host_app, "start_avatar", fake_avatar)
    monkeypatch.setattr(native_avatar, "collect", lambda _: {"gpus": [{"index": 7}]})
    monkeypatch.setattr(native_audio, "collect", lambda _: {"gpus": [{"index": 7}]})
    speech_script = tmp_path / "speech.py"
    speech_script.write_text("""import sys,wave
out=sys.argv[sys.argv.index('--out')+1]
with wave.open(out,'wb') as w:
 w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\\0\\0'*80000)
""")
    monkeypatch.setenv("AI_STATION_CHATTERBOX_SCRIPT", str(speech_script))
    clear_settings_cache()
    yield started


def avatar_sources(client):
    import io
    import wave

    from PIL import Image

    image = io.BytesIO()
    Image.new("RGB", (64, 64)).save(image, format="PNG")
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 80000)
    portrait = client.post(
        "/api/images/uploads", files={"file": ("portrait.png", image.getvalue(), "image/png")}
    )
    speech = client.post("/api/audio/uploads", files={"file": ("speech.wav", audio.getvalue(), "audio/wav")})
    assert portrait.status_code == speech.status_code == 201
    return {
        "client_request_id": str(uuid4()),
        "image_artifact_id": portrait.json()["id"],
        "audio_artifact_id": speech.json()["id"],
        "size": 256,
        "steps": 4,
    }


@pytest.mark.parametrize("speech_text", [None, "A full spoken sentence"])
def test_full_avatar_preserves_complete_sound_once_and_continuous_windows(full_avatar_bridge, speech_text):
    import av
    from app.config import get_settings
    from app.models import Artifact
    from app.paths import safe_join

    with TestClient(app) as client:
        body = avatar_sources(client)
        if speech_text:
            body["speech_text"] = speech_text
        response = client.post("/api/media/jobs/avatar", json=body)
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        assert client.post("/api/media/jobs/avatar", json=body).json()["task_id"] == tid
        for i in range(6):
            with session_factory()() as session:
                tick(session, f"avatar-{i}")
        view = client.get("/api/media/jobs/" + tid).json()
        assert view["status"] == "succeeded", view
        assert view["duration_seconds"] == 5
        assert len(full_avatar_bridge) == 2
        assert full_avatar_bridge[1].audio_window.start_frame == 64
        assert full_avatar_bridge[1].previous_video is not None
        with session_factory()() as session:
            artifact = session.get(Artifact, view["final_artifact_id"])
            assert artifact.metadata_json["frames"] == 125
            assert artifact.metadata_json["verified"]
            assert len(artifact.parent_artifact_ids) == 3
            path = safe_join(get_settings().data_dir, artifact.relative_path)
            with av.open(str(path)) as stream:
                sound = stream.streams.audio[0]
                assert abs(float(sound.duration * sound.time_base) - 5) < 1 / 25
            assert not active_locks(session)


def test_full_avatar_resume_after_speech_does_not_repeat_speech(full_avatar_bridge):
    with TestClient(app) as client:
        body = {**avatar_sources(client), "speech_text": "Do not synthesize twice"}
        response = client.post("/api/media/jobs/avatar", json=body)
        tid = response.json()["task_id"]
        with session_factory()() as session:
            tick(session, "speech")
        assert client.post("/api/media/jobs/" + tid + "/cancel").json()["status"] == "canceled"
        resume = {"expected_revision": 1, "client_request_id": str(uuid4())}
        response = client.post("/api/media/jobs/" + tid + "/resume", json=resume)
        assert response.status_code == 202, response.text
        for i in range(5):
            with session_factory()() as session:
                tick(session, f"resume-avatar-{i}")
        result = client.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded" and result["revision"] == 2, result
        with session_factory()() as session:
            speech = list(
                session.scalars(select(Run).where(Run.task_id == tid, Run.executor_type == "chatterbox"))
            )
            assert len(speech) == 1
