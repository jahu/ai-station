import io
import sys
import wave
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import avatars as host_avatar
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
from PIL import Image


def inputs(client):
    image = io.BytesIO()
    Image.new("RGB", (64, 64)).save(image, format="PNG")
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    portrait = client.post(
        "/api/images/uploads", files={"file": ("portrait.png", image.getvalue(), "image/png")}
    )
    speech = client.post("/api/audio/uploads", files={"file": ("speech.wav", audio.getvalue(), "audio/wav")})
    assert portrait.status_code == speech.status_code == 201
    return portrait.json(), speech.json()


@pytest.fixture
def avatar_bridge(tmp_path, monkeypatch):
    for relative in (
        "infer_flash.py",
        "config/config.yaml",
        "transformer/diffusion_pytorch_model.safetensors",
        "Wan2.1-Fun-V1.1-1.3B-InP/Wan2.1_VAE.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_t5_umt5-xxl-enc-bf16.pth",
        "Wan2.1-Fun-V1.1-1.3B-InP/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    python = tmp_path / "python"
    python.symlink_to(sys.executable)
    monkeypatch.setenv("AI_STATION_ECHOMIMIC_PYTHON", str(python))
    monkeypatch.setenv("AI_STATION_ECHOMIMIC_DIR", str(tmp_path))
    monkeypatch.setenv("AI_STATION_ECHOMIMIC_MODELS", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()
    monkeypatch.setattr(host_avatar, "collect", lambda _: {"gpus": [{"index": 7}]})
    monkeypatch.setattr(host_app, "collect", lambda _: {"gpus": [{"index": 7}]})
    original = host_app.manager().start
    calls = []

    def fake_start(**kwargs):
        calls.append(kwargs.copy())
        assert kwargs["argv"][0] == str(python)
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "7"
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        output = kwargs["argv"][kwargs["argv"].index("--output-path") + 1]
        delay = "import time; time.sleep(30); " if "wait" in kwargs["argv"] else ""
        kwargs["argv"] = [
            sys.executable,
            "-c",
            delay + "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'fake MP4')",
            output,
        ]
        return original(**kwargs)

    monkeypatch.setattr(host_app.manager(), "start", fake_start)
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield host, calls
    host_app.manager().shutdown()
    host_app.reset_manager()
    clear_settings_cache()


def test_avatar_run_lineage_and_video_delivery(avatar_bridge):
    _, calls = avatar_bridge
    with TestClient(app) as client:
        portrait, speech = inputs(client)
        response = client.post(
            "/api/avatars/runs", json={"image_artifact_id": portrait["id"], "audio_artifact_id": speech["id"]}
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "avatar-test")
            assert session.get(Run, response.json()["id"]).status == "succeeded"
            assert not active_locks(session)
        output = client.get("/api/artifacts", params={"run_id": response.json()["id"]}).json()[0]
        assert output["type"] == "video"
        assert output["parent_artifact_ids"] == [portrait["id"], speech["id"]]
        file = client.get(f"/api/artifacts/{output['id']}/file")
        assert file.headers["content-type"] == "video/mp4"
        assert file.headers["content-disposition"].startswith("inline")
        assert "--sample_size" in calls[0]["argv"]


def test_runner_rejects_unsafe_inputs_permissions_and_overwrite(avatar_bridge):
    host, _ = avatar_bridge
    with TestClient(app) as client:
        portrait, speech = inputs(client)
        body = {
            "run_id": str(uuid4()),
            "image_relative": portrait["relative_path"],
            "audio_relative": speech["relative_path"],
            "prompt": "Speak",
            "gpu": 7,
            "permissions": ["filesystem_read", "workspace_write"],
        }
        for patch, status in [
            ({"permissions": []}, 403),
            ({"gpu": 99}, 422),
            ({"image_relative": "../escape"}, 403),
            ({"frames": 10000}, 422),
            ({"command": "shell"}, 422),
            ({"image_relative": speech["relative_path"]}, 422),
        ]:
            assert host.post("/v1/runs/avatar", json={**body, **patch}).status_code == status
        root = get_settings().data_dir
        (root / "artifacts/redirect.png").symlink_to(root / portrait["relative_path"])
        assert (
            host.post(
                "/v1/runs/avatar", json={**body, "image_relative": "artifacts/redirect.png"}
            ).status_code
            == 403
        )
        assert host.post("/v1/runs/avatar", json=body).status_code == 200
        assert host.post("/v1/runs/avatar", json=body).status_code == 409


def test_assistant_routes_portrait_and_speech_to_child_run(avatar_bridge):
    with TestClient(app) as client:
        portrait, speech = inputs(client)
        conversation = client.post(
            "/api/chat/conversations", json={"model": "local-test", "execution_mode": "orchestrator"}
        ).json()
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={
                "content": "Animate this portrait",
                "image_artifact_ids": [portrait["id"]],
                "audio_artifact_id": speech["id"],
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            parent = tick(session, "avatar-test")
            child = tick(session, "avatar-test")
            run = session.get(Run, child)
            assert run.parent_run_id == parent and run.status == "succeeded"
            assert run.capability == "avatar.animate"


def test_avatar_cancellation_terminates_only_owned_work(avatar_bridge, monkeypatch):
    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/avatar":
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        portrait, speech = inputs(client)
        response = client.post(
            "/api/avatars/runs",
            json={"image_artifact_id": portrait["id"], "audio_artifact_id": speech["id"], "prompt": "wait"},
        )
        run_id = response.json()["id"]
        with session_factory()() as session:
            tick(session, "avatar-cancel")
            assert session.get(Run, run_id).status == "canceled"
            assert not active_locks(session)
        assert not host_app.manager().inspect(run_id)["alive"]
        assert client.get("/api/artifacts", params={"run_id": run_id}).json() == []
