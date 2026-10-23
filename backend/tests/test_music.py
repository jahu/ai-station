import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import music as native_music
from ai_station_runner.music_protocol import MODEL_REVISION
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.recovery import recover_stale
from app.resources import active_locks, reserve_gpu, reserve_memory
from app.runner_client import RunnerClient, RunnerError
from app.runs import claim_next, request_cancel, transition
from fastapi.testclient import TestClient


@pytest.fixture
def music_bridge(tmp_path, monkeypatch):
    python = tmp_path / "fake-music-python"
    python.write_text(
        f"#!{sys.executable}\n"
        """import json, os, sys, time, wave
from pathlib import Path
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
assert os.environ['CUDA_VISIBLE_DEVICES'] == '7'
run_id, root = sys.argv[3], Path(sys.argv[4])
body = json.loads((root / 'runtime/music' / run_id / 'request.json').read_text())
if body['caption'] == 'wait': time.sleep(30)
if body['caption'] == 'fail': sys.exit(4)
output = root / 'artifacts' / run_id[:2] / run_id[2:4] / (run_id + '.wav')
output.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(output), 'wb') as wav:
 wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(48000)
 for _ in range(10 if body['caption'] == 'clamped' else body['duration_seconds']):
  wav.writeframesraw(b'\\x01\\x00' * 96000)
if body['caption'] == 'truncated':
 with output.open('r+b') as handle: handle.truncate(output.stat().st_size - 3)
print('fake music generated')
"""
    )
    python.chmod(0o700)
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    monkeypatch.setenv("AI_STATION_CANCEL_GRACE_SECONDS", "0.03")
    monkeypatch.setattr(native_music, "configured", lambda: (python, tmp_path, tmp_path))
    monkeypatch.setattr(native_music, "runtime_ready", lambda *args: True)

    def hardware(root):
        return {"gpus": [{"index": 7}], "memory": {"available_mib": 65536}}

    monkeypatch.setattr(native_music, "collect", hardware)
    monkeypatch.setattr(host_app, "collect", hardware)
    host_app.reset_manager()
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield host
    host_app.manager().shutdown()
    host_app.reset_manager()


def body(**kwargs):
    return {"client_request_id": str(uuid4()), "caption": "Piano", "duration_seconds": 10, **kwargs}


def test_music_runs_share_lifecycle_and_return_playable_library_audio(music_bridge):
    with TestClient(app) as client:
        payload = body()
        response = client.post("/api/audio/music/runs", json=payload)
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["status"] == "queued"
        assert run["capability"] == "audio.music"
        repeated = client.post("/api/audio/music/runs", json=payload)
        assert repeated.status_code == 202 and repeated.json()["id"] == run["id"]
        changed = client.post("/api/audio/music/runs", json={**payload, "caption": "Different"})
        assert changed.status_code == 409
        with session_factory()() as session:
            assert tick(session, "music-test")
            current = session.get(Run, run["id"])
            assert current.status == "succeeded", current.error_message
            assert current.actual_gpu == "7"
            assert current.parameters["seed"] == run["parameters"]["seed"]
            assert not active_locks(session)
        artifacts = client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert artifact["type"] == "audio" and artifact["mime_type"] == "audio/wav"
        assert artifact["metadata"]["duration_seconds"] == 10
        assert artifact["title"] == "Piano"
        assert artifact["metadata"]["actual_gpu"] == "7"
        assert artifact["metadata"]["model_revision"] == MODEL_REVISION
        assert client.get(f"/api/artifacts/{artifact['id']}/file").content.startswith(b"RIFF")
        assert len(client.get("/api/runs", params={"capability": "audio.music"}).json()) == 1


@pytest.mark.parametrize("caption", ["fail", "truncated", "clamped"])
def test_failed_or_invalid_output_never_publishes_a_music_artifact(music_bridge, caption):
    with TestClient(app) as client:
        response = client.post("/api/audio/music/runs", json=body(caption=caption, duration_seconds=30))
        assert response.status_code == 202, response.text
        run = response.json()
        with session_factory()() as session:
            tick(session, "music-test")
            assert session.get(Run, run["id"]).status == "failed"
            assert not active_locks(session)
        assert client.get("/api/artifacts", params={"run_id": run["id"]}).json() == []


def test_stop_cancels_only_the_owned_music_group(music_bridge, monkeypatch):
    original = RunnerClient.request

    def request(self, method, path, json=None):
        response = original(self, method, path, json)
        if path == "/v1/runs/music":
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return response

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        response = client.post("/api/audio/music/runs", json=body(caption="wait"))
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session_factory()() as session:
            tick(session, "music-test")
            assert session.get(Run, run_id).status == "canceled"
            assert not active_locks(session)
        assert not host_app.manager().inspect(run_id)["alive"]
        assert client.get("/api/artifacts", params={"run_id": run_id}).json() == []


def test_unconfigured_music_does_not_enqueue_any_run():
    with TestClient(app) as client:
        assert client.get("/api/audio/music/capabilities").json()["available"] is False
        assert client.post("/api/audio/music/runs", json=body()).status_code == 409
        assert client.get("/api/runs").json() == []


def test_recovery_inspects_live_music_without_reexecution_and_confirms_stop(music_bridge):
    with TestClient(app) as client:
        response = client.post("/api/audio/music/runs", json=body(caption="wait"))
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session_factory()() as session:
            run = claim_next(session, "disappeared-worker")
            assert run.id == run_id
            transition(session, run, "preparing", event_type="executor.preparing", payload={})
            assert reserve_memory(session, run, 65536, 16384)
            assert reserve_gpu(session, run, [7]) == "7"
            native_body = {
                "run_id": run_id,
                **{
                    key: run.parameters[key]
                    for key in ("caption", "lyrics", "instrumental", "duration_seconds", "seed")
                },
                "gpu": 7,
                "permissions": run.effective_permissions,
            }
            session.commit()
            process = RunnerClient().request("POST", "/v1/runs/music", native_body)
            run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
            run.pid = process["pid"]
            transition(session, run, "running", event_type="executor.started", payload={})
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recover_stale(session)
            session.commit()
            session.refresh(run)
            assert run.status == "running" and active_locks(session)
            assert host_app.manager().inspect(run_id)["pid"] == process["pid"]
            request_cancel(session, run)
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
        assert client.get("/api/artifacts", params={"run_id": run_id}).json() == []
