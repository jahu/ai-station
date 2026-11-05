"""New video sources use the normal owned setup and media Run infrastructure."""

import copy
import hashlib
import json
import struct
from uuid import uuid4

import pytest
from ai_station_runner import video_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.video import CheckpointSelection, VideoRequest
from app import (
    hub_checkpoint_headers,
    hub_native_profiles,
    hub_sources,
    hub_video_candidates,
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
from app.video_setup_client import VideoSetupClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work(executors=None):
    with control_session_factory()() as db:
        return tick(db, "video-import-test", **({"executors": executors} if executors else {}))


@pytest.fixture
def video_bridge(monkeypatch):
    from ai_station_runner.video_environment import recipe

    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    header = json.dumps({"weight": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
    data = struct.pack("<Q", len(header)) + header + bytes(4)
    sha = hashlib.sha256(data).hexdigest()
    setup = recipe()
    slot = copy.deepcopy(slots.recipe(slots.PROFILE))
    slot.update(
        tensor_count=1,
        schema_sha256=fingerprint({"weight": [2]}),
        reference={"size_bytes": len(data), "sha256": sha},
    )
    monkeypatch.setattr(slots, "recipe", lambda profile: slot)
    hardware = {
        "host": {"system": "Linux"},
        "memory": {"total_mib": 32768, "available_mib": 30000},
        "gpus": [{"index": i, "memory_total_mib": 12288, "memory_used_mib": 0} for i in (7, 19)],
    }
    runtime = {"profile": setup["profile"], "manifest_sha256": fingerprint(setup), "environment_id": "c" * 64}
    state = {
        "ready": True,
        "calls": [],
        "starts": [],
        "bad_proof": False,
        "hardware": hardware,
        "slot": slot,
        "sha": sha,
        "runtime": runtime,
        "metadata_calls": [],
        "setup": setup,
    }

    def catalog(_):
        return {
            "recipe": setup,
            "manifest_sha256": fingerprint(setup),
            "checkpoint_slots": [slot],
            "installation_available": True,
            "managed_video": {"available": state["ready"], "managed_runtime": runtime},
            "recommendation": {"fits": True},
            "licenses": [{"name": "Wan Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"}],
            "storage": {"required_bytes": 12 * 1024**3},
        }

    monkeypatch.setattr(VideoSetupClient, "runtime_setup_catalog", catalog)
    monkeypatch.setattr(
        model_hub, "storage_info", lambda h: {"free_bytes": 100 * 1024**3, "headroom_bytes": 1024**3}
    )

    async def metadata(url, check):
        check()
        state["metadata_calls"].append(url)
        if url.endswith("config.json"):
            raise AssertionError("No mutable publisher configuration should be requested")
        if "/publisher/base/" in url:
            return {"id": "publisher/base", "sha": "b" * 40}
        return {
            "id": "publisher/new-video",
            "sha": "a" * 40,
            "pipeline_tag": "" if state.get("missing_card") else "text-to-video",
            "cardData": {}
            if state.get("missing_card")
            else {"license": "apache-2.0", "base_model": "publisher/base"},
            "siblings": [
                {
                    "rfilename": "new-video.fp16.safetensors",
                    "size": len(data),
                    "lfs": {"size": len(data), "sha256": sha},
                }
            ],
        }

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)

    async def header_metadata(file, check):
        check()
        return hub_checkpoint_headers.describe(header, len(data))

    monkeypatch.setattr(hub_native_profiles, "inspect_header", header_metadata)

    async def obtain(root, spec, *, check, progress, source_recovered=lambda u: None):
        check()
        state["calls"].append(spec)
        path = root / "models/store" / spec.sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
            path.chmod(0o444)
        progress(len(data), len(data))
        return path

    monkeypatch.setattr(model_download_job, "obtain", obtain)
    profile = {
        "available": True,
        "configuration_source": "managed",
        "managed_runtime": runtime,
        "eligible_gpu_indices": [7, 19],
        "profile_observation": {
            k: {"size_bytes": len(data) if k == "wan_model" else 2, "mtime": 1.0}
            for k in ("wan_model", "wan_text_encoder", "wan_vae")
        },
        "memory_profiles": [{"id": "bounded_11g", "available": True, "ram_mib": 11264}],
        "continuation_frames": [1, 17],
    }

    def request(_, method, path, json=None):
        if path == "/v1/hardware":
            return hardware
        if path == "/v1/models/verify":
            result = verify_model(VerifyModel.model_validate(json))
            if state["bad_proof"]:
                result["checkpoint_profile"]["schema_sha256"] = "f" * 64
            if state.get("after_verify"):
                state["after_verify"]()
            return result
        if path == "/v1/video/capabilities":
            return {"available": False}  # A broken configured runtime must not replace explicit selection.
        if path == "/v1/video/model-capabilities":
            selection = CheckpointSelection.model_validate(json)
            assert selection.managed_runtime.model_dump(mode="json") == runtime
            current = get_settings().data_dir / selection.checkpoint.relative_path
            proof = slots.inspect_checkpoint(
                current, selection.checkpoint.size_bytes, selection.checkpoint.mtime, slots.PROFILE
            )
            assert proof["schema_sha256"] == selection.checkpoint.schema_sha256
            result = copy.deepcopy(profile)
            result["profile_observation"]["wan_model"]["mtime"] = current.stat().st_mtime
            return result
        if path == "/v1/runs/video":
            body = VideoRequest.model_validate(json)
            assert body.checkpoint.sha256 == sha and body.memory_profile == "bounded_11g"
            state["starts"].append(json)
            target = (
                get_settings().data_dir
                / f"artifacts/{str(body.run_id)[:2]}/{str(body.run_id)[2:4]}/{body.run_id}.mp4"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake-video")
            state["terminal"] = dict(
                run_id=str(body.run_id),
                runner_id="fake-video",
                executor="wan_video",
                pid=12345,
                process_group_id=12345,
                alive=False,
                status="exited",
                exit_code=0,
                stdout="",
                stderr="",
                stdout_offset=0,
                stderr_offset=0,
                stdout_more=False,
                stderr_more=False,
            )
            return state["terminal"]
        if path.startswith("/v1/process/"):
            return state["terminal"]
        raise AssertionError((method, path))

    monkeypatch.setattr(RunnerClient, "request", request)
    yield state
    clear_settings_cache()


def plan(api):
    response = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-video"},
    )
    assert response.status_code == 202, response.text
    work()
    source = api.get("/api/runs/" + response.json()["id"]).json()
    assert source["status"] == "succeeded", source
    observation = source["metadata"]["source_inspection"]
    assert (
        observation["video_profile"] and observation["files"][0]["assessment"]["requires_cpu_offload_consent"]
    )
    response = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": source["id"],
            "observation_sha256": observation["observation_sha256"],
            "filename": observation["files"][0]["filename"],
        },
    )
    assert response.status_code == 202, response.text
    work()
    reviewed = api.get("/api/runs/" + response.json()["id"]).json()
    assert reviewed["status"] == "succeeded", reviewed
    return reviewed


def install(api, review, *, accepted=True):
    response = api.post(
        "/api/model-hub/downloads",
        json={
            "client_request_id": str(uuid4()),
            "plan_run_id": review["id"],
            "manifest_sha256": review["metadata"]["source_inspection"]["manifest_sha256"],
            "license_accepted": True,
            "workload_accepted": accepted,
        },
    )
    return response


def prepared(api):
    response = install(api, plan(api))
    assert response.status_code == 202, response.text
    work()
    state = api.get("/api/setup/downloads/" + response.json()["id"]).json()
    assert state["run"]["status"] == "succeeded", state
    assert state["model_key"] is None and state["definition_id"]
    return state


def test_complete_video_source_install_native_verification_and_generation(video_bridge):
    with TestClient(app) as api:
        state = prepared(api)
        assert len(video_bridge["metadata_calls"]) == 1 and len(video_bridge["calls"]) == 1
        assert api.get("/api/video/models").json()["items"][0]["id"] == state["definition_id"]
        profile = api.get(f"/api/video/models/{state['definition_id']}/capabilities").json()
        assert profile["video_model"]["checkpoint"]["sha256"] == video_bridge["sha"]
        response = api.post(
            "/api/video/runs", json={"model_id": state["definition_id"], "prompt": "A quiet river"}
        )
        assert response.status_code == 202, response.text
        work()
        run = api.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "succeeded", run
        assert video_bridge["starts"][0]["checkpoint"]["sha256"] == video_bridge["sha"]
        assert run["requested_resources"]["ram_mib"] == 11264
        assert len(api.get("/api/artifacts?run_id=" + run["id"]).json()) == 1


def test_workload_offload_consent_is_separate_from_the_model_license(video_bridge):
    with TestClient(app) as api:
        response = install(api, plan(api), accepted=False)
        assert response.status_code == 422 and "CPU offload" in response.text
        assert not video_bridge["calls"]


def test_film_freezes_the_same_checkpoint_on_every_segment_and_resume(video_bridge):
    with TestClient(app) as api:
        state = prepared(api)
        response = api.post(
            "/api/media/jobs/video",
            json={
                "client_request_id": str(uuid4()),
                "model_id": state["definition_id"],
                "prompt": "River",
                "duration_seconds": 8,
            },
        )
        assert response.status_code == 202, response.text
        with control_session_factory()() as db:
            segments = list(
                db.scalars(
                    select(Run).where(
                        Run.task_id == response.json()["task_id"], Run.executor_type == "wan_video"
                    )
                )
            )
            assert len(segments) > 1
            assert all(
                v.parameters["checkpoint"]["sha256"] == video_bridge["sha"]
                and v.parameters["video_model"]["definition_id"] == state["definition_id"]
                for v in segments
            )
            assert (
                segments[0].task.metadata_json["media_plan"]["video_model"]["definition_id"]
                == state["definition_id"]
            )
        identity = response.json()["task_id"]
        assert api.post(f"/api/media/jobs/{identity}/cancel", json={}).status_code == 200
        assert (
            api.patch(
                f"/api/models/definitions/{state['definition_id']}", json={"name": "Renamed checkpoint"}
            ).status_code
            == 200
        )
        resumed = api.post(
            f"/api/media/jobs/{identity}/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        assert resumed.status_code == 202, resumed.text
        stages = api.get(f"/api/media/jobs/{identity}/stages").json()
        assert all(
            v["parameters"]["checkpoint"]["sha256"] == video_bridge["sha"]
            for v in stages
            if v["executor_type"] == "wan_video"
        )


def test_bad_native_video_graph_never_registers_a_definition(video_bridge):
    video_bridge["bad_proof"] = True
    with TestClient(app) as api:
        response = install(api, plan(api))
        work()
        state = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert state["run"]["status"] == "failed" and "differs" in state["run"]["error_message"]
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_video_engine_prerequisite_authority_and_stop_resume(video_bridge):
    from app.video_setup_job import VideoSetupExecutor

    video_bridge["ready"] = False
    with TestClient(app) as api:
        response = install(api, plan(api))
        assert response.status_code == 202, response.text
        value = response.json()
        assert value["progress"]["phase"] == "preparing_video_engine"
        with control_session_factory()() as db:
            engine = db.get(Run, value["progress"]["engine_run_id"])
            VideoSetupExecutor().validate(engine)
            dependency = db.get(RunDependency, (value["run"]["id"], engine.id))
            db.delete(dependency)
            db.flush()
            with pytest.raises(ValueError, match="identity changed"):
                VideoSetupExecutor().validate(engine)
            db.rollback()
        assert api.post(f"/api/setup/downloads/{value['id']}/cancel").status_code == 200
        resumed = api.post(
            f"/api/setup/downloads/{value['id']}/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": value["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["entry"] == value["entry"] and not video_bridge["calls"]


def test_shared_video_definition_keeps_source_and_download_history_private(accounts, video_bridge):
    owner, alice, bob = accounts
    state = prepared(owner)
    assert alice.get("/api/video/models").json()["items"][0]["id"] == state["definition_id"]
    assert alice.get("/api/setup/downloads/" + state["id"]).status_code == 404
    assert bob.get("/api/runs/" + state["run"]["id"]).status_code == 404


def test_video_hardware_requires_one_fitting_card_not_pooled_vram(video_bridge):
    from app.hub_candidates import download_candidate

    with TestClient(app) as api:
        reviewed = plan(api)
    entry = download_candidate(reviewed["metadata"]["source_inspection"]["candidate"])
    hardware = copy.deepcopy(video_bridge["hardware"])
    for gpu in hardware["gpus"]:
        gpu["memory_total_mib"] = 8192
    assert not hub_video_candidates.recommendation(entry, hardware)["fits"]
    hardware["gpus"][0]["memory_total_mib"] = 12288
    assert hub_video_candidates.recommendation(entry, hardware)["gpus"] == [7]
    hardware["memory"]["total_mib"] = 16384
    assert not hub_video_candidates.recommendation(entry, hardware)["fits"]


def test_checkpoint_without_a_model_card_is_identified_by_its_immutable_header(video_bridge):
    video_bridge["missing_card"] = True
    with TestClient(app) as api:
        value = prepared(api)
        assert value["entry"]["configuration_filename"] == "safetensors-header"
        assert value["entry"]["configuration_repository"] == "publisher/new-video"


def test_stopped_native_verification_cannot_publish_a_video_definition(video_bridge):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        response = install(api, plan(api))

        def stop():
            with control_session_factory()() as db:
                run = db.get(Run, response.json()["run"]["id"])
                cancel_task(db, run.task)
                db.commit()

        video_bridge["after_verify"] = stop
        work()
        value = api.get("/api/setup/downloads/" + response.json()["id"]).json()
        assert value["run"]["status"] == "canceled", value
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_recheck_installed_video_uses_native_graph_and_engine_without_another_download(video_bridge):
    with TestClient(app) as api:
        state = prepared(api)
        response = api.post(f"/api/models/definitions/{state['definition_id']}/install", json={})
        assert response.status_code == 202, response.text
        work()
        value = api.get("/api/runs/" + response.json()["id"]).json()
        assert value["status"] == "succeeded", value
        assert len(video_bridge["calls"]) == 1


def test_agent_keeps_the_explicit_installed_video_in_its_reviewed_film_scope(video_bridge, monkeypatch):
    from app.local_provider import LocalChatProvider
    from test_agent_media import create, no_text_model, start

    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        state = prepared(api)
        agent = create(
            api,
            kind="video",
            request={"model_id": state["definition_id"], "prompt": "Quiet river", "duration_seconds": 5},
        )
        parent = start(api, agent)
        work()
        work()
        with control_session_factory()() as db:
            children = list(
                db.scalars(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "wan_video")
                )
            )
            assert children and all(
                r.parameters["checkpoint"]["sha256"] == video_bridge["sha"] for r in children
            )
