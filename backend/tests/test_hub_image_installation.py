"""New source → private plan/download → real native header check → image Run.

Tiny synthetic weights, fake OCI/inference; no network, model or GPU integration.
"""

import copy
import hashlib
import struct
from uuid import uuid4

import pytest
from ai_station_runner import managed_image_job, media_checkpoints
from ai_station_runner.config import clear_settings_cache as clear_native
from ai_station_runner.model_verify import VerifyModel, verify_model
from app import hub_image_candidates, hub_sources, model_download_job, model_hub
from app.api import app
from app.config import get_settings
from app.db import control_session_factory
from app.engine import tick
from app.image_setup_client import ImageSetupClient
from app.model_setup import fingerprint
from app.models import ModelDefinition, ModelFile, Run
from app.runner_client import RunnerClient
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def work(executors=None):
    with control_session_factory()() as db:
        return tick(db, "new-image-test", **({"executors": executors} if executors else {}))


def string(text):
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


@pytest.fixture
def image_bridge(monkeypatch):
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_native()
    data = b"GGUF" + struct.pack("<IQQ", 3, 1, 0)
    data += string("weight") + struct.pack("<IQIQ", 1, 32, 30, 0)
    data += bytes((-len(data)) % 32) + bytes(64)
    sha = hashlib.sha256(data).hexdigest()
    from ai_station_runner.image_setup import recipe

    setup = recipe()
    slot = copy.deepcopy(media_checkpoints.recipe(media_checkpoints.PROFILE))
    slot.update(tensor_count=1, schema_sha256=fingerprint({"weight": [32]}))
    monkeypatch.setattr(media_checkpoints, "recipe", lambda profile: slot)
    hardware = {
        "host": {"system": "Linux"},
        "memory": {"total_mib": 32768, "available_mib": 30000},
        "gpus": [
            {"index": i, "uuid": f"GPU-test-{i}", "memory_total_mib": 12288, "memory_used_mib": 0}
            for i in (7, 19)
        ],
    }
    state = {
        "data": data,
        "sha": sha,
        "slot": slot,
        "setup": setup,
        "hardware": hardware,
        "calls": [],
        "metadata_calls": [],
        "ready": True,
        "native_starts": [],
        "bad_proof": False,
    }

    def catalog(_):
        return {
            "recipe": setup,
            "manifest_sha256": fingerprint(setup),
            "checkpoint_slots": [slot],
            "installation_available": True,
            "managed_images": {"available": state["ready"]},
            "hardware": hardware,
        }

    monkeypatch.setattr(ImageSetupClient, "runtime_setup_catalog", catalog)
    monkeypatch.setattr(
        model_hub, "storage_info", lambda h: {"free_bytes": 100 * 1024**3, "headroom_bytes": 1024**3}
    )

    async def metadata(url, check):
        check()
        state["metadata_calls"].append(url)
        if url.endswith("transformer/config.json"):
            return copy.deepcopy(hub_image_candidates.GEOMETRY)
        if "/publisher/base/" in url:
            return {"id": "publisher/base", "sha": "c" * 40}
        return {
            "id": "publisher/new-image",
            "sha": "a" * 40,
            "pipeline_tag": "text-to-image",
            "cardData": {"license": "apache-2.0", "base_model": "publisher/base"},
            "siblings": [
                {
                    "rfilename": "new-image.Q4_K_M.gguf",
                    "size": len(data),
                    "lfs": {"sha256": sha, "size": len(data)},
                }
            ],
        }

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)
    monkeypatch.setattr(hub_image_candidates, "metadata_json", metadata)

    async def obtain(root, spec, *, check, progress, source_recovered=lambda u: None):
        check()
        state["calls"].append(spec)
        target = root / "models/store" / spec.sha256
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
            target.chmod(0o444)
        progress(len(data), len(data))
        return target

    monkeypatch.setattr(model_download_job, "obtain", obtain)

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
        if path == "/v1/runs/managed-image":
            body = managed_image_job.Start.model_validate(json)
            assert media_checkpoints.resolve_source(body.diffusion).is_file()
            managed_image_job.check_checkpoint_devices(body, hardware)
            state["native_starts"].append(json)
            target = (
                get_settings().data_dir
                / f"artifacts/{str(body.run_id)[:2]}/{str(body.run_id)[2:4]}/{body.run_id}.png"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (body.command.width, body.command.height), "green").save(target)
            state["terminal"] = dict(
                run_id=str(body.run_id),
                runner_id="fake-native-image",
                executor="photo_pipe",
                execution_target="container",
                pid=12345,
                process_group_id=None,
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
        if path.startswith("/v1/images/jobs/"):
            return state["terminal"]
        raise AssertionError((method, path))

    monkeypatch.setattr(RunnerClient, "request", request)
    yield state
    clear_native()


def plan(api):
    created = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-image"},
    )
    assert created.status_code == 202, created.text
    work()
    source = api.get("/api/runs/" + created.json()["id"]).json()
    assert source["status"] == "succeeded", source
    observation = source["metadata"]["source_inspection"]
    assert (
        observation["image_profile"]
        and observation["files"][0]["assessment"]["profiles"][0]["capability"] == "image"
    )
    result = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": source["id"],
            "observation_sha256": observation["observation_sha256"],
            "filename": observation["files"][0]["filename"],
        },
    )
    assert result.status_code == 202, result.text
    work()
    result = api.get("/api/runs/" + result.json()["id"]).json()
    assert result["status"] == "succeeded", result
    return result


def install(api, review):
    request = {
        "client_request_id": str(uuid4()),
        "plan_run_id": review["id"],
        "manifest_sha256": review["metadata"]["source_inspection"]["manifest_sha256"],
        "license_accepted": True,
    }
    response = api.post("/api/model-hub/downloads", json=request)
    assert response.status_code == 202, response.text
    assert api.post("/api/model-hub/downloads", json=request).json()["id"] == response.json()["id"]
    return response.json()


def test_new_image_is_verified_registered_and_executes_through_the_same_image_run(image_bridge):
    with TestClient(app) as api:
        reviewed = plan(api)
        assert len(image_bridge["metadata_calls"]) == 3 and not image_bridge["calls"]
        original_defaults = api.get("/api/images/models").json()["defaults"]
        prepared = install(api, reviewed)
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        assert saved["run"]["status"] == "succeeded", saved
        assert saved["model_key"] is None and saved["definition_id"]
        assert len(image_bridge["calls"]) == 1
        catalog = api.get("/api/images/models").json()
        assert catalog["defaults"] == original_defaults
        assert any(v["id"] == saved["definition_id"] and v["available"] for v in catalog["items"])
        assert api.get("/api/images/capabilities?model_id=" + saved["definition_id"]).json()["available"]
        queued = api.post(
            "/api/images/runs",
            json={
                "mode": "t2i",
                "prompt": "A quiet landscape",
                "width": 512,
                "height": 512,
                "model_id": saved["definition_id"],
            },
        )
        assert queued.status_code == 202, queued.text
        work()
        completed = api.get("/api/runs/" + queued.json()["id"]).json()
        assert completed["status"] == "succeeded", completed
        native = image_bridge["native_starts"][0]
        assert (
            native["gpus"] == [7, 19]
            and native["diffusion"]["relative_path"] == "models/store/" + image_bridge["sha"]
        )
        assert native["command"]["mode"] == "t2i" and native["references"] == []
        assert len(image_bridge["calls"]) == 1


def test_native_graph_disagreement_prevents_image_registry_publication(image_bridge):
    image_bridge["bad_proof"] = True
    with TestClient(app) as api:
        prepared = install(api, plan(api))
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        assert saved["run"]["status"] == "failed"
        assert "differs" in saved["run"]["error_message"]
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition))) and not list(db.scalars(select(ModelFile)))


def test_missing_engine_is_an_owned_prerequisite_and_stop_cancels_both_runs(image_bridge):
    image_bridge["ready"] = False
    with TestClient(app) as api:
        prepared = install(api, plan(api))
        assert prepared["progress"]["phase"] == "preparing_image_engine"
        with control_session_factory()() as db:
            engine = db.get(Run, prepared["progress"]["engine_run_id"])
            assert engine.executor_type == "image_setup" and engine.task_id == prepared["id"]
        stopped = api.post("/api/setup/downloads/" + prepared["id"] + "/cancel")
        assert stopped.status_code == 200
        with control_session_factory()() as db:
            assert db.get(Run, prepared["progress"]["engine_run_id"]).status == "canceled"
        assert not image_bridge["calls"]


def test_image_prerequisite_finishes_before_checkpoint_download(image_bridge):
    image_bridge["ready"] = False

    class Prepared:
        def execute(self, db, run):
            from app.image_setup_job import ImageSetupExecutor

            ImageSetupExecutor().validate(run)
            assert not image_bridge["calls"] and run.executor_type == "image_setup"
            transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(db, run, RunStatus.RUNNING, event_type="executor.started")
            transition(db, run, RunStatus.SUCCEEDED, event_type="run.completed")
            image_bridge["ready"] = True
            return "done"

    with TestClient(app) as api:
        prepared = install(api, plan(api))
        work({"image_setup": Prepared()})
        assert not image_bridge["calls"]
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        assert saved["run"]["status"] == "succeeded", saved


@pytest.mark.parametrize("mode,count", [("img2img", 1), ("recompose", 2)])
def test_new_image_model_keeps_edit_and_recompose_on_the_shared_artifact_path(image_bridge, mode, count):
    import io

    with TestClient(app) as api:
        prepared = install(api, plan(api))
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        parents = []
        for _ in range(count):
            buffer = io.BytesIO()
            Image.new("RGB", (512, 512), "blue").save(buffer, "PNG")
            uploaded = api.post(
                "/api/images/uploads", files={"file": ("input.png", buffer.getvalue(), "image/png")}
            )
            assert uploaded.status_code == 201, uploaded.text
            parents.append(uploaded.json()["id"])
        created = api.post(
            "/api/images/runs",
            json={
                "mode": mode,
                "prompt": "A quiet landscape",
                "edit_prompt": "Replace the background",
                "model_id": saved["definition_id"],
                "input_artifact_ids": parents,
            },
        )
        assert created.status_code == 202, created.text
        work()
        result = api.get("/api/runs/" + created.json()["id"]).json()
        assert result["status"] == "succeeded", result
        native = image_bridge["native_starts"][0]
        assert native["command"]["mode"] == mode and len(native["references"]) == count
        artifacts = api.get("/api/artifacts?run_id=" + created.json()["id"]).json()
        assert artifacts[0]["parent_artifact_ids"] == parents


def test_stop_and_resume_keep_the_pinned_image_plan_and_engine_prerequisite(image_bridge):
    image_bridge["ready"] = False
    with TestClient(app) as api:
        prepared = install(api, plan(api))
        api.post("/api/setup/downloads/" + prepared["id"] + "/cancel")
        resumed = api.post(
            "/api/setup/downloads/" + prepared["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": prepared["run"]["id"]},
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["entry"] == prepared["entry"]
        assert resumed.json()["progress"]["engine_run_id"] != prepared["progress"]["engine_run_id"]
        with control_session_factory()() as db:
            assert db.get(Run, resumed.json()["run"]["id"]).parent_run_id == prepared["run"]["id"]
        assert not image_bridge["calls"]


def test_uncertain_engine_cleanup_cannot_be_replaced_by_another_attempt(image_bridge):
    image_bridge["ready"] = False
    with TestClient(app) as api:
        prepared = install(api, plan(api))
        api.post("/api/setup/downloads/" + prepared["id"] + "/cancel")
        with control_session_factory()() as db:
            engine = db.get(Run, prepared["progress"]["engine_run_id"])
            engine.metadata_json = {**engine.metadata_json, "cleanup_requires_inspection": True}
            db.commit()
        response = api.post(
            "/api/setup/downloads/" + prepared["id"] + "/resume",
            json={"client_request_id": str(uuid4()), "expected_run_id": prepared["run"]["id"]},
        )
        assert response.status_code == 409 and "earlier image engine" in response.text
        assert not image_bridge["calls"]


def test_image_hardware_does_not_pool_two_small_gpus_into_one_component_budget(image_bridge):
    from app.hub_candidates import download_candidate

    with TestClient(app) as api:
        reviewed = plan(api)
    payload = reviewed["metadata"]["source_inspection"]["candidate"]
    payload["file"]["size_bytes"] = payload["slot"]["reference"]["size_bytes"] + 4 * 1024**3
    entry = download_candidate(payload)
    assert not hub_image_candidates.recommendation(entry, image_bridge["hardware"])["fits"]
    bigger = copy.deepcopy(image_bridge["hardware"])
    bigger["gpus"][0]["memory_total_mib"] = 24576
    fitted = hub_image_candidates.recommendation(entry, bigger)
    assert fitted["fits"] and fitted["gpus"] == [7, 19] and fitted["cpu_offload"] is False


def test_recheck_keeps_the_native_image_binding_and_never_downloads_again(image_bridge):
    with TestClient(app) as api:
        prepared = install(api, plan(api))
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        checked = api.post("/api/models/definitions/" + saved["definition_id"] + "/install", json={})
        assert checked.status_code == 202, checked.text
        work()
        result = api.get("/api/runs/" + checked.json()["id"]).json()
        assert result["status"] == "succeeded", result
        assert len(image_bridge["calls"]) == 1
        detail = api.get("/api/models/definitions/" + saved["definition_id"]).json()
        assert detail["compatibility"]["adapter"] == "managed-container"


def test_runtime_preparation_authority_requires_its_exact_licensed_dependency(image_bridge):
    from app.image_setup_job import ImageSetupExecutor
    from app.models import RunDependency

    image_bridge["ready"] = False
    with TestClient(app) as api:
        prepared = install(api, plan(api))
    with control_session_factory()() as db:
        engine = db.get(Run, prepared["progress"]["engine_run_id"])
        ImageSetupExecutor().validate(engine)
        dependency = db.get(RunDependency, (prepared["run"]["id"], engine.id))
        db.delete(dependency)
        db.flush()
        with pytest.raises(ValueError, match="identity changed"):
            ImageSetupExecutor().validate(engine)


def test_shared_image_model_does_not_share_its_installation_history(accounts, image_bridge):
    owner, alice, bob = accounts
    prepared = install(owner, plan(owner))
    work()
    saved = owner.get("/api/setup/downloads/" + prepared["id"]).json()
    assert saved["run"]["status"] == "succeeded", saved
    assert any(v["id"] == saved["definition_id"] for v in alice.get("/api/images/models").json()["items"])
    assert alice.get("/api/setup/downloads/" + prepared["id"]).status_code == 404
    assert bob.get("/api/runs/" + saved["run"]["id"]).status_code == 404


def test_disk_budget_reuses_cached_components_and_reserves_unpacked_engine_space():
    GiB = 1024**3
    report = {
        "recipe": {
            "inputs": [{"size_bytes": 5 * GiB}],
            "download_bytes": 2 * GiB,
            "minimum_free_bytes": 12 * GiB,
        },
        "storage": {"cached_model_bytes_estimate": 3 * GiB},
        "image": {"present": False},
        "managed_images": {"available": False},
    }
    assert hub_image_candidates.prerequisite_budget(report) == 14 * GiB
    report["image"]["present"] = True
    assert hub_image_candidates.prerequisite_budget(report) == 2 * GiB
    report["managed_images"]["available"] = True
    assert hub_image_candidates.prerequisite_budget(report) == 0


def test_stop_during_native_image_verification_never_publishes_the_model(image_bridge):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        prepared = install(api, plan(api))

        def stop():
            with control_session_factory()() as db:
                run = db.get(Run, prepared["run"]["id"])
                cancel_task(db, run.task)
                db.commit()

        image_bridge["after_verify"] = stop
        work()
        saved = api.get("/api/setup/downloads/" + prepared["id"]).json()
        assert saved["run"]["status"] == "canceled"
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))
