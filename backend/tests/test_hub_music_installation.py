"""New music sources reuse ordinary model Tasks, native admission and music Runs."""

import copy
import hashlib
import json
import struct
import wave
from uuid import uuid4

import pytest
from ai_station_runner import music_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.music_runtime_schema import CheckpointSelection
from app import (
    hub_checkpoint_headers,
    hub_music_candidates,
    hub_native_profiles,
    hub_sources,
    model_download_job,
    model_hub,
)
from app.api import app
from app.config import get_settings
from app.db import control_session_factory
from app.engine import tick
from app.model_setup import fingerprint
from app.models import ModelDefinition, Run, RunDependency
from app.music_setup_client import MusicSetupClient
from app.runner_client import RunnerClient
from app.video_setup_client import VideoSetupClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work():
    with control_session_factory()() as db:
        return tick(db, "music-import-test")


@pytest.fixture
def music_bridge(monkeypatch):
    from ai_station_runner.music_environment import recipe
    from ai_station_runner.video_checkpoints import PROFILE as VIDEO_PROFILE
    from ai_station_runner.video_checkpoints import recipe as video_slot

    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    header = json.dumps({"weight": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}}).encode()
    data = struct.pack("<Q", len(header)) + header + bytes(2)
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
            "managed_music": {"available": state["ready"], "managed_runtime": runtime},
            "recommendation": {"fits": True},
            "storage": {"required_bytes": 8 * 1024**3},
            "licenses": [{"name": "Music model", "url": "https://huggingface.co/ResembleAI/ace_step_music"}],
        }

    from app.speech_setup_client import SpeechSetupClient

    monkeypatch.setattr(SpeechSetupClient, "runtime_setup_catalog", lambda self: {"checkpoint_slots": []})
    monkeypatch.setattr(MusicSetupClient, "runtime_setup_catalog", catalog)
    monkeypatch.setattr(model_hub, "storage_info", lambda h: state["storage"])

    async def metadata(url, check):
        check()
        return {
            "id": "publisher/new-music",
            "sha": "a" * 40,
            "pipeline_tag": "",
            "cardData": {},
            "siblings": [
                {
                    "rfilename": "new-diffusion.safetensors",
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
        if path == "/v1/music/capabilities":
            return {"available": False}  # Explicit model selection must bypass an unavailable default.
        if path == "/v1/music/model-capabilities":
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
                "max_seconds": 600,
                "profile_sha256": "912b4a5cd50f729d8874dcbd44776d87643f04d199b748ba3706b7181a69c658",
            }
        if path == "/v1/runs/music":
            from ai_station_runner.music import MusicRequest

            body = MusicRequest.model_validate(json)
            assert body.checkpoint.sha256 == sha and body.gpu == 7
            state["starts"].append(json)
            output = (
                get_settings().data_dir
                / f"artifacts/{str(body.run_id)[:2]}/{str(body.run_id)[2:4]}/{body.run_id}.wav"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output), "wb") as wav:
                wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\1\0" * (48000 * body.duration_seconds))
            state["terminal"] = {
                "run_id": str(body.run_id),
                "runner_id": "fake-music",
                "executor": "ace_step_music",
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
        json={"client_request_id": str(uuid4()), "source": "publisher/new-music"},
    )
    assert source.status_code == 202, source.text
    work()
    source = api.get("/api/runs/" + source.json()["id"]).json()
    assert source["status"] == "succeeded", source
    report = source["metadata"]["source_inspection"]
    assert report["music_profile"] and not report.get("video_profile")
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
            "workload_accepted": True,
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


def test_native_header_disagreement_and_stop_cannot_publish_a_music_definition(music_bridge):
    music_bridge["bad_proof"] = True
    with TestClient(app) as api:
        queued = install(api, plan(api))
        work()
        value = api.get("/api/setup/downloads/" + queued["id"]).json()
        assert value["run"]["status"] == "failed" and "differs" in value["run"]["error_message"]
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_cancellation_during_verification_preserves_object_without_registration(music_bridge):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        queued = install(api, plan(api))

        def stop():
            with control_session_factory()() as db:
                cancel_task(db, db.get(Run, queued["run"]["id"]).task)
                db.commit()

        music_bridge["after_verify"] = stop
        work()
        assert api.get("/api/setup/downloads/" + queued["id"]).json()["run"]["status"] == "canceled"
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_music_setup_prerequisite_needs_exact_ownership_manifest_and_dependency(music_bridge):
    from app.music_setup_job import MusicSetupExecutor

    music_bridge["ready"] = False
    with TestClient(app) as api:
        queued = install(api, plan(api))
        assert queued["progress"]["phase"] == "preparing_music_engine"
        with control_session_factory()() as db:
            engine = db.get(Run, queued["progress"]["engine_run_id"])
            MusicSetupExecutor().validate(engine)
            db.delete(db.get(RunDependency, (queued["run"]["id"], engine.id)))
            db.flush()
            with pytest.raises(ValueError):
                MusicSetupExecutor().validate(engine)
            db.rollback()
        assert api.post("/api/setup/downloads/" + queued["id"] + "/cancel").status_code == 200
        resumed = api.post(
            "/api/setup/downloads/" + queued["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": queued["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        assert not music_bridge["downloads"]


def test_shared_music_choices_do_not_expose_private_source_history(accounts, music_bridge):
    owner, alice, bob = accounts
    installed = prepared(owner)
    assert alice.get("/api/audio/music/models").json()["items"][0]["id"] == installed["definition_id"]
    assert bob.get("/api/setup/downloads/" + installed["id"]).status_code == 404
    assert alice.get("/api/runs/" + installed["run"]["id"]).status_code == 404


def test_music_hardware_needs_real_capacity_and_does_not_pool_smaller_cards(music_bridge):
    from app.hub_candidates import download_candidate

    with TestClient(app) as api:
        entry = download_candidate(plan(api)["metadata"]["source_inspection"]["candidate"])
    assert (
        "24-GiB physical RAM"
        in hub_music_candidates.recommendation(entry, music_bridge["hardware"])["reason"]
    )
    hardware = copy.deepcopy(music_bridge["hardware"])
    hardware["gpus"] = [{"index": 3, "memory_total_mib": 4096}, {"index": 9, "memory_total_mib": 4096}]
    assert not hub_music_candidates.recommendation(entry, hardware)["fits"]
    hardware["gpus"][1]["memory_total_mib"] = 12288
    assert hub_music_candidates.recommendation(entry, hardware)["gpus"] == [9]
    hardware["memory"]["total_mib"] = 8192
    assert not hub_music_candidates.recommendation(entry, hardware)["fits"]


@pytest.mark.parametrize("shortage", ["gpu", "ram", "disk", "unknown_gpu", "unknown_ram", "unknown_disk"])
def test_unsuitable_or_unknown_hardware_blocks_install_before_any_transfer(music_bridge, shortage):
    if shortage == "gpu":
        # Two smaller cards cannot satisfy an adapter that requires one 6-GiB card.
        music_bridge["hardware"]["gpus"] = [
            {"index": 3, "memory_total_mib": 4096},
            {"index": 9, "memory_total_mib": 4096},
        ]
    elif shortage == "ram":
        music_bridge["hardware"]["memory"]["total_mib"] = 8192
    elif shortage == "disk":
        music_bridge["storage"]["free_bytes"] = 1
    elif shortage == "unknown_gpu":
        music_bridge["hardware"]["gpus"][0].pop("memory_total_mib")
    elif shortage == "unknown_ram":
        music_bridge["hardware"]["memory"].pop("total_mib")
    else:
        music_bridge["storage"] = None
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
                "workload_accepted": True,
            },
        )
        assert response.status_code == 409, response.text
    assert not music_bridge["downloads"] and not music_bridge["starts"]
    with control_session_factory()() as db:
        assert not list(
            db.scalars(select(Run).where(Run.executor_type.in_(["model_download", "music_setup"])))
        )


def test_temporarily_busy_gpu_is_reported_separately_from_capacity(music_bridge):
    music_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 10000
    with TestClient(app) as api:
        reviewed = plan(api)
    assessment = reviewed["metadata"]["source_inspection"]["files"][0]["assessment"]
    assert assessment["hardware_status"] == "estimated_fit"
    assert assessment["profiles"][0]["occupancy"] == "in_use"
    assert assessment["automatic_ram_offload"] is False
    assert assessment["automatic_cloud_fallback"] is False
    assert not music_bridge["downloads"] and not music_bridge["starts"]


@pytest.mark.parametrize("changed", ["gpu", "ram"])
def test_hardware_change_after_review_blocks_even_prerequisite_transfers(music_bridge, monkeypatch, changed):
    from app import speech_setup_job

    async def forbidden(*args, **kwargs):
        pytest.fail("Changed hardware must be checked before downloading engine or companion weights")

    monkeypatch.setattr(speech_setup_job, "obtain", forbidden)
    music_bridge["ready"] = False
    with TestClient(app) as api:
        queued = install(api, plan(api))
        engine = queued["progress"]["engine_run_id"]
        if changed == "gpu":
            music_bridge["hardware"]["gpus"][0]["memory_total_mib"] = 4096
        else:
            music_bridge["hardware"]["memory"]["total_mib"] = 8192
        work()
        run = api.get("/api/runs/" + engine).json()
        assert run["status"] == "failed" and "hardware profile changed" in run["error_message"], run
    assert not music_bridge["downloads"] and not music_bridge["starts"]


def test_music_definition_recheck_never_downloads_a_second_object(music_bridge):
    with TestClient(app) as api:
        installed = prepared(api)
        detail = api.get("/api/models/definitions/" + installed["definition_id"]).json()
        assert detail["music_backend"] == "ace-step-1.5"
        assert detail["compatibility"]["adapter"] == "native-music"
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
        assert len(music_bridge["downloads"]) == 1


def test_new_source_installs_then_generates_with_selected_weights_even_if_default_unavailable(music_bridge):
    with TestClient(app) as api:
        installed = prepared(api)
        choices = api.get("/api/audio/music/models").json()["items"]
        assert choices[0]["id"] == installed["definition_id"] and choices[0]["cpu_offload"] is True
        request = {
            "client_request_id": str(uuid4()),
            "model_id": installed["definition_id"],
            "caption": "Warm piano",
            "duration_seconds": 10,
        }
        queued = api.post("/api/audio/music/runs", json=request)
        assert queued.status_code == 202, queued.text
        work()
        run = api.get("/api/runs/" + queued.json()["id"]).json()
        assert run["status"] == "succeeded", json.dumps(run)
        assert run["requested_resources"]["ram_mib"] == 12288
        assert music_bridge["starts"][0]["checkpoint"]["sha256"] == music_bridge["sha"]
        artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
        assert len(artifacts) == 1 and artifacts[0]["metadata"]["model_id"] == installed["definition_id"]
        assert len(music_bridge["headers"]) == 1 and len(music_bridge["downloads"]) == 1


def test_agent_keeps_selected_music_model_and_no_text_model_is_used(music_bridge, monkeypatch):
    from app.local_provider import LocalChatProvider
    from test_agent_media import create, no_text_model, start

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        installed = prepared(api)
        agent = create(
            api,
            kind="music",
            request={"model_id": installed["definition_id"], "caption": "Calm piano", "duration_seconds": 10},
        )
        parent = start(api, agent)
        work()
        work()
        with control_session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "ace_step_music")
                )
            )
            assert (
                len(children) == 1
                and children[0].parameters["music_model"]["checkpoint"]["sha256"] == music_bridge["sha"]
            )
        work()
        assert music_bridge["starts"]


def test_conversation_publishes_the_selected_music_model_without_text_inference(music_bridge, monkeypatch):
    from app.local_provider import LocalChatProvider
    from test_agent_media import no_text_model
    from test_assistant import create

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        installed = prepared(api)
        conversation = create(api)
        response = api.post(
            f"/api/chat/conversations/{conversation}/messages",
            json={
                "content": "Generate a calm piano track",
                "action": "audio.music",
                "music": {"model_id": installed["definition_id"], "duration_seconds": 10},
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        work()
        with control_session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(
                        Run.task_id == response.json()["task_id"], Run.executor_type == "ace_step_music"
                    )
                )
            )
            assert (
                len(children) == 1
                and children[0].parameters["music_model"]["checkpoint"]["sha256"] == music_bridge["sha"]
            )
        work()
        assert music_bridge["starts"]
