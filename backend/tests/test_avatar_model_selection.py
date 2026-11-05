"""Installed avatar choice follows source -> Run -> artifact and resume, with fake inference."""

import copy
import wave
from uuid import uuid4

import pytest
from ai_station_runner.avatar_model_selection import ModelSelection
from ai_station_runner.sonic_jobs import WholeAvatarRequest
from app.api import app
from app.artifacts import register_file
from app.config import get_settings
from app.db import control_session_factory
from app.models import ModelDefinition
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from PIL import Image
from test_account_private_api import private_app as private_app
from test_hub_avatar_installation import bridge as bridge
from test_hub_avatar_installation import install, plan, work
from test_whole_avatar_jobs import fake_movie


@pytest.fixture
def generation(bridge, monkeypatch, tmp_path):
    previous = RunnerClient.request
    state = {"starts": [], "probes": [], "records": {}, "fail": False, "default_calls": 0}

    def request(self, method, path, json=None):
        if path == "/v1/avatar/whole-capabilities":
            state["default_calls"] += 1
            return {"available": False}
        if path == "/v1/avatar/model-capabilities":
            checked = ModelSelection.model_validate(json)
            state["probes"].append(copy.deepcopy(json))
            return {
                "available": True,
                "backend": "sonic",
                "ram_mib": 18432,
                "max_side": 768,
                "max_pixels": 512 * 768,
                "fps": 25,
                "detected_gpu_count": 1,
                "eligible_gpu_indices": [7],
                "configuration_source": "managed",
                "checkpoint": checked.checkpoint,
                "managed_runtime": json["managed_runtime"],
                "recipe": {
                    "id": "sonic_whole_768_v1",
                    "observation": "d" * 64,
                    "environment_id": json["managed_runtime"]["environment_id"],
                },
            }
        if path == "/v1/audio/capabilities":
            return {"available": True, "languages": ["pl"]}
        if path in {"/v1/runs/whole-avatar", "/v1/runs/audio"}:
            identifier = json["run_id"]
            root = get_settings().data_dir
            output = root / f"artifacts/{identifier[:2]}/{identifier[2:4]}/{identifier}"
            output.parent.mkdir(parents=True, exist_ok=True)
            if path.endswith("whole-avatar"):
                WholeAvatarRequest.model_validate(json)
                state["starts"].append(copy.deepcopy(json))
                if not state["fail"]:
                    fake_movie(output.with_suffix(".mp4"), json, root)
                executor, code = "sonic_whole", 1 if state["fail"] else 0
            else:
                with wave.open(str(output.with_suffix(".wav")), "wb") as target:
                    target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    target.writeframes(bytes(48000))
                executor, code = "chatterbox", 0
            value = {
                "run_id": identifier,
                "pid": 777,
                "process_group_id": 777,
                "runner_id": "fake-native",
                "executor": executor,
                "exit_code": code,
                "alive": False,
                "status": "exited",
            }
            state["records"][identifier] = value
            return value
        return previous(self, method, path, json)

    monkeypatch.setattr(RunnerClient, "request", request)

    def inspect(self, identifier, **offsets):
        return {
            **state["records"][identifier],
            "stdout": "",
            "stderr": "",
            "stdout_offset": 0,
            "stderr_offset": 0,
            "stdout_more": False,
            "stderr_more": False,
        }

    monkeypatch.setattr(RunnerClient, "inspect_process", inspect)
    portrait, audio = tmp_path / "portrait.png", tmp_path / "recording.wav"
    Image.new("RGB", (512, 768), "white").save(portrait)
    with wave.open(str(audio), "wb") as target:
        target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        target.writeframes(bytes(48000))
    with control_session_factory()() as db:
        state["image"] = register_file(
            db,
            source=portrait,
            artifact_type="image",
            mime_type="image/png",
            original_filename="portrait.png",
            run_id=None,
        ).id
        state["audio"] = register_file(
            db,
            source=audio,
            artifact_type="audio",
            mime_type="audio/wav",
            original_filename="recording.wav",
            run_id=None,
        ).id
        db.commit()
    return state


def installed(api):
    response = install(api, plan(api))
    assert response.status_code == 202, response.text
    queued = response.json()
    work()
    result = api.get("/api/setup/downloads/" + queued["id"]).json()
    assert result["run"]["status"] == "succeeded", result
    return result["definition_id"]


def submit(api, identity, state, **changes):
    response = api.post(
        "/api/media/jobs/avatar",
        json={
            "client_request_id": str(uuid4()),
            "model_id": identity,
            "image_artifact_id": state["image"],
            "audio_artifact_id": state["audio"],
            **changes,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def settle():
    for _ in range(6):
        work()


@pytest.mark.parametrize("speech", [False, True])
def test_selected_model_publishes_complete_video_with_unavailable_default(generation, speech):
    with TestClient(app) as api:
        identity = installed(api)
        choices = api.get("/api/avatars/models").json()["items"]
        assert choices[0]["id"] == identity and choices[0]["available"]
        job = submit(api, identity, generation, **({"speech_text": "Dzień dobry."} if speech else {}))
        settle()
        result = api.get("/api/media/jobs/" + job["task_id"]).json()
        assert result["status"] == "succeeded", result
        assert result["request"]["model_id"] == identity and result["final_artifact_id"]
        assert generation["starts"][0]["checkpoint"]["profile"] == "sonic-whole-unet-v1"
        assert generation["default_calls"] == 0


def test_resume_uses_original_model_after_definition_binding_changes(generation):
    with TestClient(app) as api:
        identity = installed(api)
        generation["fail"] = True
        job = submit(api, identity, generation)
        settle()
        failed = api.get("/api/media/jobs/" + job["task_id"]).json()
        assert failed["status"] == "failed", failed
        original = copy.deepcopy(generation["starts"][0])
        with control_session_factory()() as db:
            definition = db.get(ModelDefinition, identity)
            metadata = copy.deepcopy(definition.metadata_json)
            metadata["avatar"]["binding"]["managed_runtime"]["environment_id"] = "f" * 64
            definition.metadata_json = metadata
            db.commit()
        generation["fail"] = False
        response = api.post(
            "/api/media/jobs/" + job["task_id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": failed["revision"]},
        )
        assert response.status_code == 202, response.text
        settle()
        result = api.get("/api/media/jobs/" + job["task_id"]).json()
        assert result["status"] == "succeeded", result
        assert generation["starts"][1]["checkpoint"] == original["checkpoint"]
        assert generation["starts"][1]["recipe"] == original["recipe"]


def test_registered_model_recheck_and_rename_keep_avatar_controls(generation, bridge):
    with TestClient(app) as api:
        identity = installed(api)
        detail = api.get("/api/models/definitions/" + identity).json()
        assert detail["avatar_backend"] == "sonic" and detail["compatibility"]["adapter"] == "native-avatar"
        assert (
            api.patch("/api/models/definitions/" + identity, json={"name": "My portrait model"}).status_code
            == 200
        )
        assert (
            api.patch("/api/models/definitions/" + identity, json={"context_size": 8192}).status_code == 422
        )
        response = api.post("/api/models/definitions/" + identity + "/install", json={})
        assert response.status_code == 202, response.text
        settle()
        detail = api.get("/api/models/definitions/" + identity).json()
        assert detail["status"] == "registered", detail
        assert len(bridge["downloads"]) == 1


def test_reviewed_agent_retains_selected_avatar_without_default_engine(generation, monkeypatch):
    from app.local_provider import LocalChatProvider
    from app.models import Run
    from test_agent_media import create, no_text_model, start

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        identity = installed(api)
        agent = create(
            api,
            kind="avatar",
            request={
                "model_id": identity,
                "image_artifact_id": generation["image"],
                "audio_artifact_id": generation["audio"],
            },
            maximum_runtime=7200,
        )
        root = start(api, agent)
        settle()
        result = api.get("/api/agents/" + agent["id"]).json()
        assert result["last_status"] == "succeeded", result
        with control_session_factory()() as db:
            workflow = db.get(Run, root["id"])
            assert workflow.parameters["avatar_model"]["definition_id"] == identity
        assert generation["starts"] and generation["default_calls"] == 0


def test_conversation_uses_explicit_avatar_model_and_publishes_its_film(generation):
    with TestClient(app) as api:
        identity = installed(api)
        conversation = api.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "work"}
        ).json()
        path = "/api/chat/conversations/" + conversation["id"]
        sent = api.post(
            path + "/messages",
            json={
                "content": "Animate this portrait",
                "action": "avatar.animate",
                "image_artifact_ids": [generation["image"]],
                "audio_artifact_id": generation["audio"],
                "avatar_model_id": identity,
            },
        )
        assert sent.status_code == 202, sent.text
        settle()
        assert generation["starts"] and generation["default_calls"] == 0
        messages = api.get(path).json()["messages"]
        assert any(message.get("artifacts") for message in messages), messages


def test_factory_offers_avatar_model_only_for_its_registered_role(generation):
    from app.agent_media_choices import catalog, validate_selection
    from app.agent_media_schema import AgentAvatarScope

    with TestClient(app) as api:
        identity = installed(api)
    with control_session_factory()() as db:
        offered = catalog(db, identifier=identity)
        assert len(offered) == 1 and offered[0]["kind"] == "avatar"
        scope = AgentAvatarScope(kind="avatar", request={"model_id": identity})
        assert validate_selection(db, scope, offered)["model_id"] == identity
