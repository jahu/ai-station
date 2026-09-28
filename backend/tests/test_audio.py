import io
import sys
import wave

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import audio as host_audio
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import request_cancel
from fastapi.testclient import TestClient


def wav_bytes():
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 3200)
    return result.getvalue()


@pytest.fixture
def audio_bridge(tmp_path, monkeypatch):
    script = tmp_path / "speech.py"
    script.write_text("""import os, sys, wave, time
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
assert os.environ['CUDA_VISIBLE_DEVICES'] == '7'
text = sys.argv[sys.argv.index('--text')+1]
if text == 'wait': time.sleep(30)
if text == 'fail': sys.exit(3)
with wave.open(sys.argv[sys.argv.index('--out')+1], 'wb') as wav:
 wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
 wav.writeframes(b'\\0\\0' * 4800)
print('speech generated')
""")
    monkeypatch.setenv("AI_STATION_CHATTERBOX_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_CHATTERBOX_SCRIPT", str(script))
    monkeypatch.setenv("AI_STATION_CHATTERBOX_CACHE", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()

    def hardware(_):
        return {"gpus": [{"index": 7}]}

    monkeypatch.setattr(host_app, "collect", hardware)
    monkeypatch.setattr(host_audio, "collect", hardware)
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
    clear_settings_cache()


def reference(client):
    result = client.post("/api/audio/uploads", files={"file": ("../voice.wav", wav_bytes(), "audio/wav")})
    assert result.status_code == 201, result.text
    return result.json()


def test_audio_run_artifact_lineage_and_playback(audio_bridge):
    with TestClient(app) as client:
        source = reference(client)
        response = client.post(
            "/api/audio/runs", json={"text": "Witaj", "reference_artifact_id": source["id"]}
        )
        assert response.status_code == 202, response.text
        run = response.json()
        with session_factory()() as session:
            tick(session, "audio-test")
            assert session.get(Run, run["id"]).status == "succeeded"
            assert not active_locks(session)
        artifacts = client.get("/api/artifacts", params={"run_id": run["id"]}).json()
        assert len(artifacts) == 1
        result = artifacts[0]
        assert result["type"] == "audio" and result["mime_type"] == "audio/wav"
        assert result["parent_artifact_ids"] == [source["id"]]
        assert result["metadata"]["sample_rate"] == 24000
        assert result["metadata"]["duration_seconds"] == 0.2
        file = client.get(f"/api/artifacts/{result['id']}/file")
        assert file.status_code == 200 and file.headers["content-disposition"].startswith("inline")
        assert file.content.startswith(b"RIFF")


@pytest.mark.parametrize("data", [b"bad", wav_bytes()[:-10]])
def test_invalid_audio_upload_is_rejected(data):
    with TestClient(app) as client:
        assert (
            client.post("/api/audio/uploads", files={"file": ("test.wav", data, "audio/wav")}).status_code
            == 422
        )
        assert client.get("/api/artifacts").json() == []


def test_cancel_managed_audio_releases_resources(audio_bridge, monkeypatch):
    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/audio":
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        source = reference(client)
        run = client.post(
            "/api/audio/runs", json={"text": "wait", "reference_artifact_id": source["id"]}
        ).json()
        with session_factory()() as session:
            tick(session, "audio-test")
            assert session.get(Run, run["id"]).status == "canceled"
            assert not active_locks(session)
        assert not host_app.manager().inspect(run["id"])["alive"]
        assert not client.get("/api/artifacts", params={"run_id": run["id"]}).json()


def test_audio_runner_enforces_permissions_and_paths(audio_bridge):
    from uuid import uuid4

    with TestClient(app) as client:
        source = reference(client)
        body = {
            "run_id": str(uuid4()),
            "text": "hello",
            "reference_relative": source["relative_path"],
            "gpu": 7,
            "permissions": ["filesystem_read", "workspace_write"],
        }
        assert audio_bridge.post("/v1/runs/audio", json={**body, "permissions": []}).status_code == 403
        assert (
            audio_bridge.post(
                "/v1/runs/audio", json={**body, "reference_relative": "../escape.wav"}
            ).status_code
            == 403
        )
        assert audio_bridge.post("/v1/runs/audio", json={**body, "gpu": 123}).status_code == 422
        root = get_settings().data_dir
        (root / "artifacts/redirect.wav").symlink_to(root / source["relative_path"])
        assert (
            audio_bridge.post(
                "/v1/runs/audio", json={**body, "reference_relative": "artifacts/redirect.wav"}
            ).status_code
            == 403
        )
        assert audio_bridge.post("/v1/runs/audio", json={**body, "command": "arbitrary"}).status_code == 422


def test_assistant_dispatches_speech_and_returns_audio_result(audio_bridge):
    with TestClient(app) as client:
        source = reference(client)
        conversation = client.post(
            "/api/chat/conversations", json={"model": "local-test", "execution_mode": "orchestrator"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        result = client.post(
            route + "/messages",
            json={"content": "Witaj", "action": "audio.speech", "audio_artifact_id": source["id"]},
        )
        assert result.status_code == 202, result.text
        parent = result.json()
        with session_factory()() as session:
            assert tick(session, "audio-assistant-test") == parent["id"]
            child_id = tick(session, "audio-assistant-test")
            child = session.get(Run, child_id)
            assert child.status == "succeeded"
            assert child.task_id == parent["task_id"] and child.parent_run_id == parent["id"]
        result = client.get(route).json()["messages"][-1]
        assert result["task_status"] == "succeeded"
        assert result["artifacts"][0]["type"] == "audio"
        assert result["artifacts"][0]["parent_artifact_ids"] == [source["id"]]


def test_audio_runner_never_overwrites_existing_output(audio_bridge):
    from uuid import uuid4

    with TestClient(app) as client:
        source = reference(client)
        run_id = str(uuid4())
        path = get_settings().data_dir / f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing output")
        response = audio_bridge.post(
            "/v1/runs/audio",
            json={
                "run_id": run_id,
                "text": "hello",
                "reference_relative": source["relative_path"],
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
            },
        )
        assert response.status_code == 409
        assert path.read_bytes() == b"existing output"
