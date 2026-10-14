import io
import sys
import wave
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import audio as host_audio
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
    speech_script = tmp_path / "fake_speech.py"
    speech_script.write_text("""import sys,time,wave
args=sys.argv
text=args[args.index('--text')+1]
if text == 'fail': sys.exit(3)
if text == 'wait': time.sleep(30)
with wave.open(args[args.index('--out')+1], 'wb') as wav:
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
    wav.writeframes(b'\\0\\0' * 16000)
""")
    monkeypatch.setenv("AI_STATION_CHATTERBOX_PYTHON", str(python))
    monkeypatch.setenv("AI_STATION_CHATTERBOX_SCRIPT", str(speech_script))
    monkeypatch.setenv("AI_STATION_CHATTERBOX_CACHE", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()
    monkeypatch.setattr(host_audio, "collect", lambda _: {"gpus": [{"index": 7}]})
    monkeypatch.setattr(host_avatar, "collect", lambda _: {"gpus": [{"index": 7}]})
    monkeypatch.setattr(host_app, "collect", lambda _: {"gpus": [{"index": 7}]})
    original = host_app.manager().start
    calls = []

    def fake_start(**kwargs):
        calls.append(kwargs.copy())
        assert kwargs["argv"][0] == str(python)
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "7"
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        if kwargs["executor"] == "chatterbox":
            return original(**kwargs)
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


def test_spoken_avatar_chain_keeps_both_artifacts_after_restart(avatar_bridge):
    from app.db import reset_engine

    with TestClient(app) as client:
        portrait, voice = inputs(client)
        result = client.post(
            "/api/avatars/runs",
            json={
                "image_artifact_id": portrait["id"],
                "audio_artifact_id": voice["id"],
                "speech_text": "Cześć!",
                "gpu": "7",
                "size": 256,
                "frames": 17,
            },
        )
        assert result.status_code == 202, result.text
        first = result.json()
        assert first["executor_type"] == "chatterbox"
        assert first["parameters"]["text"] == "Cześć!"
        with session_factory()() as session:
            assert tick(session, "avatar-workflow") == first["id"]
            assert not active_locks(session)
        chain = client.get(f"/api/avatars/runs/{first['id']}/workflow").json()["steps"]
        assert [r["status"] for r in chain] == ["succeeded", "queued"]
        child = chain[1]
        audio = client.get(f"/api/artifacts?run_id={first['id']}").json()[0]
        assert child["parameters"]["parent_artifact_ids"] == [portrait["id"], audio["id"]]
        assert child["parameters"]["audio_relative"] == audio["relative_path"]
        assert child["requested_gpu"] == first["requested_gpu"]
        assert child["effective_permissions"] == first["effective_permissions"]
        assert child["task_id"] == first["task_id"] and child["parent_run_id"] == first["id"]
        assert child["parameters"]["size"] == 256 and child["parameters"]["frames"] == 17
        reset_engine()
        with session_factory()() as session:
            assert tick(session, "avatar-restart") == child["id"]
            assert tick(session, "avatar-restart") is None
            assert not active_locks(session)
        final = client.get(f"/api/artifacts?run_id={child['id']}").json()[0]
        assert final["parent_artifact_ids"] == [portrait["id"], audio["id"]]
        assert audio["parent_artifact_ids"] == [voice["id"]]
        assert [
            r["status"] for r in client.get(f"/api/avatars/runs/{first['id']}/workflow").json()["steps"]
        ] == ["succeeded", "succeeded"]


@pytest.mark.parametrize("case", ["failed", "cancel", "unknown"])
def test_unsuccessful_speech_does_not_publish_avatar(avatar_bridge, monkeypatch, case):
    with TestClient(app) as client:
        portrait, voice = inputs(client)
        first = client.post(
            "/api/avatars/runs",
            json={
                "image_artifact_id": portrait["id"],
                "audio_artifact_id": voice["id"],
                "speech_text": "fail" if case == "failed" else "Cześć!",
            },
        ).json()
        if case == "cancel":
            client.post(f"/api/runs/{first['id']}/cancel").raise_for_status()
        if case == "unknown":
            original = RunnerClient.inspect_process

            def unknown(self, run_id, **offsets):
                info = original(self, run_id, **offsets)
                if not info["alive"]:
                    info.update(status="interrupted", exit_code=None)
                return info

            monkeypatch.setattr(RunnerClient, "inspect_process", unknown)
        with session_factory()() as session:
            tick(session, "avatar-workflow")
            assert not active_locks(session)
        chain = client.get(f"/api/avatars/runs/{first['id']}/workflow").json()["steps"]
        assert len(chain) == 1 and chain[0]["status"] in {"failed", "canceled", "interrupted"}
        assert not client.get(f"/api/artifacts?run_id={first['id']}").json()


def test_cancel_queued_avatar_preserves_generated_speech(avatar_bridge):
    with TestClient(app) as client:
        portrait, voice = inputs(client)
        first = client.post(
            "/api/avatars/runs",
            json={
                "image_artifact_id": portrait["id"],
                "audio_artifact_id": voice["id"],
                "speech_text": "Cześć!",
            },
        ).json()
        with session_factory()() as session:
            tick(session, "avatar-workflow")
        child = client.get(f"/api/avatars/runs/{first['id']}/workflow").json()["steps"][1]
        canceled = client.post(f"/api/runs/{first['id']}/cancel")
        canceled.raise_for_status()
        assert canceled.json()["id"] == child["id"]
        with session_factory()() as session:
            assert tick(session, "avatar-workflow") is None
        assert client.get(f"/api/artifacts?run_id={first['id']}").json()[0]["type"] == "audio"
        assert not client.get(f"/api/artifacts?run_id={child['id']}").json()


def test_assistant_spoken_avatar_projects_three_runs(avatar_bridge):
    with TestClient(app) as client:
        portrait, voice = inputs(client)
        conversation = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        response = client.post(
            route + "/messages",
            json={
                "content": "Animate this portrait",
                "image_artifact_ids": [portrait["id"]],
                "audio_artifact_id": voice["id"],
                "speech_text": "Cześć!",
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            for _ in range(3):
                tick(session, "avatar-workflow")
        detail = client.get(route).json()
        assert detail["active_run"] is None
        result = detail["messages"][-1]
        assert result["task_status"] == "succeeded"
        assert [s["capability"] for s in result["steps"]] == [
            "assistant.orchestrate",
            "audio.speech",
            "avatar.animate",
        ]
        assert [a["type"] for a in result["artifacts"]] == ["audio", "video"]
        assert (
            client.post(
                route + "/messages", json={"content": "Hello", "speech_text": "Hello", "action": "chat"}
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "content,text",
    [
        ("Zrób awatar, który powie: Cześć!", "Cześć!"),
        ('Animate this portrait saying "Hello there".', "Hello there"),
        ("Animate this portrait naturally", None),
    ],
)
def test_current_spoken_words_route_without_inventing_text(avatar_bridge, content, text):
    with TestClient(app) as client:
        portrait, voice = inputs(client)
        conversation = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        client.post(
            route + "/messages",
            json={
                "content": content,
                "image_artifact_ids": [portrait["id"]],
                "audio_artifact_id": voice["id"],
            },
        ).raise_for_status()
        with session_factory()() as session:
            tick(session, "avatar-natural")
        run = client.get(route).json()["active_run"]
        assert run["executor_type"] == ("chatterbox" if text else "echomimic")
        if text:
            assert run["parameters"]["text"] == text


def test_native_avatar_uses_absolute_audio_window_and_pads_only_final_tail(avatar_bridge):
    from app.config import get_settings

    host, calls = avatar_bridge
    with TestClient(app) as client:
        portrait, speech = inputs(client)
        response = host.post(
            "/v1/runs/avatar",
            json={
                "run_id": str(uuid4()),
                "image_relative": portrait["relative_path"],
                "audio_relative": speech["relative_path"],
                "prompt": "Speak",
                "size": 256,
                "frames": 33,
                "steps": 4,
                "gpu": 7,
                "audio_window": {"start_frame": 17},
                "permissions": ["filesystem_read", "workspace_write"],
            },
        )
        assert response.status_code == 200, response.text
        args = calls[-1]["argv"]
        window = args[args.index("--audio_path") + 1]
        with wave.open(window, "rb") as sound:
            assert sound.getnframes() == 34 * 16000 // 25
            assert sound.getframerate() == 16000
        with wave.open(str(get_settings().data_dir / speech["relative_path"]), "rb") as sound:
            assert sound.getnframes() == 16000  # Canonical source is unchanged.
        assert window.endswith("audio-window.wav")
