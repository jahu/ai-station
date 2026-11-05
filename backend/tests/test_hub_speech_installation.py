"""New speech sources reuse ordinary model Tasks, native admission and speech Runs."""

import copy
import hashlib
import json
import struct
import wave
from uuid import uuid4

import pytest
from ai_station_runner import speech_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.speech_runtime_schema import CheckpointSelection
from app import (
    hub_checkpoint_headers,
    hub_native_profiles,
    hub_sources,
    hub_speech_candidates,
    model_download_job,
    model_hub,
)
from app.api import app
from app.config import get_settings
from app.db import control_session_factory
from app.engine import tick
from app.model_setup import fingerprint
from app.models import ModelDefinition, Run, RunDependency
from app.runner_client import RunnerClient
from app.speech_setup_client import SpeechSetupClient
from app.video_setup_client import VideoSetupClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work():
    with control_session_factory()() as db:
        return tick(db, "speech-import-test")


@pytest.fixture
def speech_bridge(monkeypatch):
    from ai_station_runner.speech_environment import recipe
    from ai_station_runner.video_checkpoints import PROFILE as VIDEO_PROFILE
    from ai_station_runner.video_checkpoints import recipe as video_slot

    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    header = json.dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
    data = struct.pack("<Q", len(header)) + header + bytes(4)
    sha = hashlib.sha256(data).hexdigest()
    setup = recipe()
    slot = copy.deepcopy(slots.recipe(slots.PROFILE))
    slot.update(
        tensor_count=1,
        schema_sha256=fingerprint({"weight": [1]}),
        reference={"sha256": sha, "size_bytes": len(data)},
    )
    monkeypatch.setattr(slots, "recipe", lambda profile: slot)
    monkeypatch.setattr(
        VideoSetupClient,
        "runtime_setup_catalog",
        lambda self: {"checkpoint_slots": [video_slot(VIDEO_PROFILE)]},
    )
    runtime = {"profile": setup["profile"], "manifest_sha256": fingerprint(setup), "environment_id": "c" * 64}
    hardware = {
        "memory": {"total_mib": 32768, "available_mib": 30000},
        "gpus": [{"index": 7, "memory_total_mib": 12288, "memory_used_mib": 0}],
    }
    state = {
        "ready": True,
        "sha": sha,
        "slot": slot,
        "runtime": runtime,
        "hardware": hardware,
        "downloads": [],
        "headers": [],
        "starts": [],
        "storage": {"free_bytes": 100 * 1024**3, "headroom_bytes": 1024**3},
    }

    def catalog(self):
        return {
            "recipe": setup,
            "manifest_sha256": fingerprint(setup),
            "checkpoint_slots": [slot],
            "installation_available": True,
            "managed_speech": {"available": state["ready"], "managed_runtime": runtime},
            "recommendation": {"fits": True},
            "storage": {"required_bytes": 8 * 1024**3},
            "licenses": [{"name": "Speech model", "url": "https://huggingface.co/ResembleAI/chatterbox"}],
        }

    monkeypatch.setattr(SpeechSetupClient, "runtime_setup_catalog", catalog)
    monkeypatch.setattr(model_hub, "storage_info", lambda h: state["storage"])

    async def metadata(url, check):
        check()
        return {
            "id": "publisher/new-speech",
            "sha": "a" * 40,
            "pipeline_tag": "",
            "cardData": {},
            "siblings": [
                {
                    "rfilename": "new-t3.safetensors",
                    "size": len(data),
                    "lfs": {"sha256": sha, "size": len(data)},
                }
            ],
        }

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)

    async def inspect_header(file, check):
        check()
        state["headers"].append(file["filename"])
        return hub_checkpoint_headers.describe(header, len(data))

    monkeypatch.setattr(hub_native_profiles, "inspect_header", inspect_header)

    async def obtain(root, spec, *, check, progress, source_recovered=lambda value: None):
        check()
        state["downloads"].append(spec)
        path = root / "models/store" / spec.sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
            path.chmod(0o400)
        progress(len(data), len(data))
        return path

    monkeypatch.setattr(model_download_job, "obtain", obtain)

    def request(self, method, path, json=None):
        if path == "/v1/hardware":
            return hardware
        if path == "/v1/models/verify":
            report = verify_model(VerifyModel.model_validate(json))
            if state.get("bad_proof"):
                report["checkpoint_profile"]["header_sha256"] = "f" * 64
            if state.get("after_verify"):
                state["after_verify"]()
            return report
        if path == "/v1/audio/capabilities":
            return {"available": False}  # Explicit model selection must bypass an unavailable default.
        if path == "/v1/audio/model-capabilities":
            body = CheckpointSelection.model_validate(json)
            assert body.managed_runtime.model_dump(mode="json") == runtime
            file = get_settings().data_dir / body.checkpoint.relative_path
            proof = slots.inspect_checkpoint(
                file, body.checkpoint.size_bytes, body.checkpoint.mtime, slots.PROFILE
            )
            assert proof["schema_sha256"] == body.checkpoint.schema_sha256
            return {
                "available": True,
                "configuration_source": "managed",
                "managed_runtime": runtime,
                "runtime_manifest_sha256": runtime["manifest_sha256"],
                "eligible_gpu_indices": [7],
            }
        if path == "/v1/runs/audio":
            from ai_station_runner.audio import AudioRequest

            body = AudioRequest.model_validate(json)
            assert body.checkpoint.sha256 == sha and body.gpu == 7
            state["starts"].append(json)
            output = (
                get_settings().data_dir
                / f"artifacts/{str(body.run_id)[:2]}/{str(body.run_id)[2:4]}/{body.run_id}.wav"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output), "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(bytes(3200))
            state["terminal"] = {
                "run_id": str(body.run_id),
                "runner_id": "fake-speech",
                "executor": "chatterbox",
                "pid": 12345,
                "process_group_id": 12345,
                "alive": False,
                "status": "exited",
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
            return state["terminal"]
        if path.startswith("/v1/process/"):
            return state["terminal"]
        raise AssertionError((method, path))

    monkeypatch.setattr(RunnerClient, "request", request)
    yield state
    clear_settings_cache()


def plan(api):
    source = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-speech"},
    )
    assert source.status_code == 202, source.text
    work()
    source = api.get("/api/runs/" + source.json()["id"]).json()
    assert source["status"] == "succeeded", source
    report = source["metadata"]["source_inspection"]
    assert report["speech_profile"] and not report.get("video_profile")
    queued = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": source["id"],
            "observation_sha256": report["observation_sha256"],
            "filename": report["files"][0]["filename"],
        },
    )
    assert queued.status_code == 202, queued.text
    work()
    value = api.get("/api/runs/" + queued.json()["id"]).json()
    assert value["status"] == "succeeded", value
    return value


def install(api, review):
    value = api.post(
        "/api/model-hub/downloads",
        json={
            "client_request_id": str(uuid4()),
            "plan_run_id": review["id"],
            "manifest_sha256": review["metadata"]["source_inspection"]["manifest_sha256"],
            "license_accepted": True,
        },
    )
    assert value.status_code == 202, value.text
    return value.json()


def prepared(api):
    queued = install(api, plan(api))
    work()
    value = api.get("/api/setup/downloads/" + queued["id"]).json()
    assert value["run"]["status"] == "succeeded", value
    assert value["definition_id"] and value["model_key"] is None
    return value


def test_new_card_free_speech_source_installs_once_and_generates_through_the_selected_binding(speech_bridge):
    from test_audio import wav_bytes

    with TestClient(app) as api:
        installed = prepared(api)
        assert len(speech_bridge["headers"]) == 1 and len(speech_bridge["downloads"]) == 1
        assert api.get("/api/audio/models").json()["items"][0]["id"] == installed["definition_id"]
        voice = api.post("/api/audio/uploads", files={"file": ("voice.wav", wav_bytes(), "audio/wav")}).json()
        queued = api.post(
            "/api/audio/runs",
            json={
                "model_id": installed["definition_id"],
                "text": "Dzień dobry.",
                "reference_artifact_id": voice["id"],
            },
        )
        assert queued.status_code == 202, queued.text
        work()
        run = api.get("/api/runs/" + queued.json()["id"]).json()
        assert run["status"] == "succeeded", json.dumps(run)
        assert run["requested_resources"]["ram_mib"] == 11264
        assert speech_bridge["starts"][0]["checkpoint"]["sha256"] == speech_bridge["sha"]
        artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
        assert len(artifacts) == 1 and artifacts[0]["type"] == "audio"


def test_native_header_disagreement_and_stop_cannot_publish_a_speech_definition(speech_bridge):
    speech_bridge["bad_proof"] = True
    with TestClient(app) as api:
        queued = install(api, plan(api))
        work()
        value = api.get("/api/setup/downloads/" + queued["id"]).json()
        assert value["run"]["status"] == "failed" and "differs" in value["run"]["error_message"]
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_cancellation_during_verification_preserves_object_without_registration(speech_bridge):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        queued = install(api, plan(api))

        def stop():
            with control_session_factory()() as db:
                cancel_task(db, db.get(Run, queued["run"]["id"]).task)
                db.commit()

        speech_bridge["after_verify"] = stop
        work()
        assert api.get("/api/setup/downloads/" + queued["id"]).json()["run"]["status"] == "canceled"
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_speech_setup_prerequisite_needs_exact_ownership_manifest_and_dependency(speech_bridge):
    from app.speech_setup_job import SpeechSetupExecutor

    speech_bridge["ready"] = False
    with TestClient(app) as api:
        queued = install(api, plan(api))
        assert queued["progress"]["phase"] == "preparing_speech_engine"
        with control_session_factory()() as db:
            engine = db.get(Run, queued["progress"]["engine_run_id"])
            SpeechSetupExecutor().validate(engine)
            db.delete(db.get(RunDependency, (queued["run"]["id"], engine.id)))
            db.flush()
            with pytest.raises(ValueError):
                SpeechSetupExecutor().validate(engine)
            db.rollback()
        assert api.post("/api/setup/downloads/" + queued["id"] + "/cancel").status_code == 200
        resumed = api.post(
            "/api/setup/downloads/" + queued["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": queued["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        assert not speech_bridge["downloads"]


def test_shared_speech_choices_do_not_expose_private_source_history(accounts, speech_bridge):
    owner, alice, bob = accounts
    installed = prepared(owner)
    assert alice.get("/api/audio/models").json()["items"][0]["id"] == installed["definition_id"]
    assert bob.get("/api/setup/downloads/" + installed["id"]).status_code == 404
    assert alice.get("/api/runs/" + installed["run"]["id"]).status_code == 404


def test_speech_hardware_needs_real_capacity_and_does_not_pool_smaller_cards(speech_bridge):
    from app.hub_candidates import download_candidate

    with TestClient(app) as api:
        entry = download_candidate(plan(api)["metadata"]["source_inspection"]["candidate"])
    hardware = copy.deepcopy(speech_bridge["hardware"])
    hardware["gpus"] = [{"index": 3, "memory_total_mib": 4096}, {"index": 9, "memory_total_mib": 4096}]
    assert not hub_speech_candidates.recommendation(entry, hardware)["fits"]
    hardware["gpus"][1]["memory_total_mib"] = 6144
    assert hub_speech_candidates.recommendation(entry, hardware)["gpus"] == [9]
    hardware["memory"]["total_mib"] = 8192
    assert not hub_speech_candidates.recommendation(entry, hardware)["fits"]


@pytest.mark.parametrize("shortage", ["gpu", "ram", "disk", "unknown_gpu", "unknown_ram", "unknown_disk"])
def test_unsuitable_or_unknown_hardware_blocks_install_before_any_transfer(speech_bridge, shortage):
    if shortage == "gpu":
        # Two smaller cards cannot satisfy an adapter that requires one 6-GiB card.
        speech_bridge["hardware"]["gpus"] = [
            {"index": 3, "memory_total_mib": 4096},
            {"index": 9, "memory_total_mib": 4096},
        ]
    elif shortage == "ram":
        speech_bridge["hardware"]["memory"]["total_mib"] = 8192
    elif shortage == "disk":
        speech_bridge["storage"]["free_bytes"] = 1
    elif shortage == "unknown_gpu":
        speech_bridge["hardware"]["gpus"][0].pop("memory_total_mib")
    elif shortage == "unknown_ram":
        speech_bridge["hardware"]["memory"].pop("total_mib")
    else:
        speech_bridge["storage"] = None
    with TestClient(app) as api:
        reviewed = plan(api)
        report = reviewed["metadata"]["source_inspection"]
        response = api.post(
            "/api/model-hub/downloads",
            json={
                "client_request_id": str(uuid4()),
                "plan_run_id": reviewed["id"],
                "manifest_sha256": report["manifest_sha256"],
                "license_accepted": True,
            },
        )
        assert response.status_code == 409, response.text
    assert not speech_bridge["downloads"] and not speech_bridge["starts"]
    with control_session_factory()() as db:
        assert not list(
            db.scalars(select(Run).where(Run.executor_type.in_(["model_download", "speech_setup"])))
        )


def test_temporarily_busy_gpu_is_reported_separately_from_capacity(speech_bridge):
    speech_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 10000
    with TestClient(app) as api:
        reviewed = plan(api)
    assessment = reviewed["metadata"]["source_inspection"]["files"][0]["assessment"]
    assert assessment["hardware_status"] == "estimated_fit"
    assert assessment["profiles"][0]["occupancy"] == "in_use"
    assert assessment["automatic_ram_offload"] is False
    assert assessment["automatic_cloud_fallback"] is False
    assert not speech_bridge["downloads"] and not speech_bridge["starts"]


@pytest.mark.parametrize("changed", ["gpu", "ram"])
def test_hardware_change_after_review_blocks_even_prerequisite_transfers(speech_bridge, monkeypatch, changed):
    from app import speech_setup_job

    async def forbidden(*args, **kwargs):
        pytest.fail("Changed hardware must be checked before downloading engine or companion weights")

    monkeypatch.setattr(speech_setup_job, "obtain", forbidden)
    speech_bridge["ready"] = False
    with TestClient(app) as api:
        queued = install(api, plan(api))
        engine = queued["progress"]["engine_run_id"]
        if changed == "gpu":
            speech_bridge["hardware"]["gpus"][0]["memory_total_mib"] = 4096
        else:
            speech_bridge["hardware"]["memory"]["total_mib"] = 8192
        work()
        run = api.get("/api/runs/" + engine).json()
        assert run["status"] == "failed" and "hardware profile changed" in run["error_message"], run
    assert not speech_bridge["downloads"] and not speech_bridge["starts"]


def test_fish_cannot_silently_ignore_a_chatterbox_model_choice():
    from app.audio_schema import SpeechRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Fish"):
        SpeechRequest(
            text="Dzień dobry",
            model_id=uuid4(),
            engine="fish_s2_pro",
            reference_artifact_id=None,
            voice_source="model",
        )


def test_speech_definition_recheck_never_downloads_a_second_object(speech_bridge):
    with TestClient(app) as api:
        installed = prepared(api)
        detail = api.get("/api/models/definitions/" + installed["definition_id"]).json()
        assert detail["speech_backend"] == "chatterbox"
        assert detail["compatibility"]["adapter"] == "managed-native"
        assert (
            api.patch(
                "/api/models/definitions/" + installed["definition_id"], json={"context_size": 8192}
            ).status_code
            == 422
        )
        queued = api.post("/api/models/definitions/" + installed["definition_id"] + "/install", json={})
        assert queued.status_code == 202, queued.text
        work()
        assert api.get("/api/runs/" + queued.json()["id"]).json()["status"] == "succeeded"
        assert len(speech_bridge["downloads"]) == 1


def test_agent_execution_keeps_explicit_speech_model_despite_unavailable_default(speech_bridge, monkeypatch):
    from app.local_provider import LocalChatProvider
    from test_agent_media import create, no_text_model, start
    from test_audio import wav_bytes

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        installed = prepared(api)
        reference = api.post(
            "/api/audio/uploads", files={"file": ("voice.wav", wav_bytes(), "audio/wav")}
        ).json()
        agent = create(
            api,
            kind="speech",
            request={
                "model_id": installed["definition_id"],
                "text": "Dzień dobry.",
                "reference_artifact_id": reference["id"],
            },
        )
        parent = start(api, agent)
        work()
        work()
        with control_session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "chatterbox")
                )
            )
            assert children and all(
                child.parameters["checkpoint"]["sha256"] == speech_bridge["sha"] for child in children
            )


def test_factory_knows_the_registered_speech_choice_but_never_launches_it(speech_bridge, monkeypatch):
    from app.local_provider import LocalChatProvider
    from test_agent_drafts import state, step, submit

    calls = []
    with TestClient(app) as api:
        installed = prepared(api)

        async def stream(self, **params):
            calls.append(params)
            yield json.dumps(
                {
                    "name": "Polish speech",
                    "goal": "Speak a Polish greeting",
                    "tools": ["create_media"],
                    "media": {
                        "kind": "speech",
                        "request": {
                            "model_id": installed["definition_id"],
                            "text": "Dzień dobry",
                            "reference_artifact_id": None,
                        },
                    },
                }
            )

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        queued = submit(api, instruction="Create an agent that speaks Polish using my installed speech model")
        step()
        result = state(api, queued)
        assert result["status"] == "succeeded", result
        agent = api.get("/api/agents/" + result["metadata"]["agent_id"]).json()
        assert not agent["enabled"] and agent["media"]["request"]["model_id"] == installed["definition_id"]
        choices = json.loads(calls[0]["messages"][1]["content"])["registered_media_models"]
        assert choices[0]["kind"] == "speech" and choices[0]["model_id"] == installed["definition_id"]
        assert not speech_bridge["starts"]


def test_owned_speech_inspection_resume_does_not_require_a_mutable_model_catalog(monkeypatch):
    from types import SimpleNamespace

    from app.audio import AudioExecutor
    from app.host_media_executor import HostMediaExecutor

    resumed = []
    monkeypatch.setattr(
        HostMediaExecutor, "execute", lambda self, session, run: resumed.append(run.id) or "resumed"
    )
    monkeypatch.setattr(
        RunnerClient,
        "request",
        lambda *args, **kwargs: pytest.fail(
            "Inspection recovery must not launch or query current model readiness"
        ),
    )
    run = SimpleNamespace(id="owned-speech", metadata_json={"media_inspection_resume": True})
    assert AudioExecutor().execute(SimpleNamespace(refresh=lambda run: None), run) == "resumed"
    assert resumed == ["owned-speech"]


def test_conversation_speech_publishes_the_chosen_model_without_calling_a_text_model(
    speech_bridge, monkeypatch
):
    from app.local_provider import LocalChatProvider
    from test_agent_media import no_text_model
    from test_assistant import create
    from test_audio import wav_bytes

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        installed = prepared(api)
        reference = api.post(
            "/api/audio/uploads", files={"file": ("voice.wav", wav_bytes(), "audio/wav")}
        ).json()
        conversation = create(api)
        response = api.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={
                "content": "Dzień dobry.",
                "action": "audio.speech",
                "audio_artifact_id": reference["id"],
                "speech_model_id": installed["definition_id"],
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        work()
        with control_session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(
                        Run.task_id == response.json()["task_id"], Run.executor_type == "chatterbox"
                    )
                )
            )
            assert (
                len(children) == 1 and children[0].parameters["checkpoint"]["sha256"] == speech_bridge["sha"]
            )
        work()
        assert speech_bridge["starts"]
        invalid = api.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={
                "content": "Question",
                "action": "chat",
                "audio_artifact_id": reference["id"],
                "speech_model_id": installed["definition_id"],
                "web_search": {"enabled": False},
            },
        )
        assert invalid.status_code == 422
