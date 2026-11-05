"""Avatar sources use ordinary private inspection/install Runs and native data admission."""

import copy
import io
from uuid import uuid4

import pytest
from ai_station_runner import avatar_checkpoints as slots
from ai_station_runner.avatar_environment import recipe
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.torch_state_zip import read_archive
from app import hub_avatar_candidates, hub_sources, model_download_job, model_hub
from app.api import app
from app.avatar_setup_client import AvatarSetupClient
from app.db import control_session_factory
from app.engine import tick
from app.model_setup import fingerprint
from app.models import ModelDefinition, Run, RunDependency
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_hub_tensor_headers import source as archive_source


def work():
    with control_session_factory()() as db:
        return tick(db, "avatar-import-test")


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    file, content = archive_source()
    header = read_archive(io.BytesIO(content), verify_local=False)["report"]
    setup = recipe()
    slot = copy.deepcopy(slots.recipe(slots.PROFILE))
    slot.update(
        tensor_count=1,
        schema_sha256=header["schema_sha256"],
        module_metadata_sha256=header["module_metadata_sha256"],
        reference={"sha256": file["sha256"], "size_bytes": len(content)},
    )
    monkeypatch.setattr(slots, "recipe", lambda profile: slot)
    runtime = {"profile": setup["profile"], "manifest_sha256": fingerprint(setup), "environment_id": "c" * 64}
    state = {
        "ready": True,
        "qualified": True,
        "fits": True,
        "headers": [],
        "downloads": [],
        "runtime": runtime,
        "hardware": {
            "memory": {"total_mib": 32768, "available_mib": 30000},
            "gpus": [{"index": 7, "memory_total_mib": 12288, "memory_used_mib": 0}],
        },
    }

    def catalog(self):
        return {
            "recipe": setup,
            "manifest_sha256": fingerprint(setup),
            "checkpoint_slots": [slot],
            "checkpoint_inference_available": state["qualified"],
            "installation_available": True,
            "managed_avatar": {
                "prepared": state["ready"],
                "available": state["ready"],
                "managed_runtime": runtime,
            },
            "recommendation": {"fits": state["fits"]},
            "storage": {"required_bytes": 12 * 1024**3},
            "licenses": [
                {"name": "Synthetic avatar model", "url": "https://huggingface.co/publisher/new-avatar"}
            ],
        }

    monkeypatch.setattr(AvatarSetupClient, "runtime_setup_catalog", catalog)
    monkeypatch.setattr(
        model_hub, "storage_info", lambda hardware: {"free_bytes": 100 * 1024**3, "headroom_bytes": 1024**3}
    )

    async def metadata(url, check):
        check()
        return {
            "id": "publisher/new-avatar",
            "sha": "a" * 40,
            "pipeline_tag": "",
            "cardData": {},
            "siblings": [
                {
                    "rfilename": "new-sonic.pth",
                    "size": len(content),
                    "lfs": {"sha256": file["sha256"], "size": len(content)},
                }
            ],
        }

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)

    async def inspect(file, check):
        check()
        state["headers"].append(file["filename"])
        return header

    monkeypatch.setattr(hub_avatar_candidates, "inspect_header", inspect)

    async def obtain(root, spec, *, check, progress, source_recovered=lambda value: None):
        check()
        state["downloads"].append(spec)
        path = root / "models/store" / spec.sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
            path.chmod(0o400)
        progress(len(content), len(content))
        return path

    monkeypatch.setattr(model_download_job, "obtain", obtain)

    def request(self, method, path, json=None):
        if path == "/v1/hardware":
            return state["hardware"]
        if path == "/v1/models/verify":
            report = verify_model(VerifyModel.model_validate(json))
            if state.get("bad_proof"):
                report["checkpoint_profile"]["module_metadata_sha256"] = "f" * 64
            if state.get("after_verify"):
                state["after_verify"]()
            return report
        raise AssertionError((method, path))

    monkeypatch.setattr(RunnerClient, "request", request)
    yield state
    clear_settings_cache()


def plan(api):
    response = api.post(
        "/api/model-hub/inspections",
        json={"client_request_id": str(uuid4()), "source": "publisher/new-avatar"},
    )
    assert response.status_code == 202, response.text
    work()
    source = api.get("/api/runs/" + response.json()["id"]).json()
    assert source["status"] == "succeeded", source
    report = source["metadata"]["source_inspection"]
    assert report["avatar_profile"] and report["files"][0]["unsafe_serialization"] is True
    response = api.post(
        "/api/model-hub/plans",
        json={
            "client_request_id": str(uuid4()),
            "inspection_run_id": source["id"],
            "observation_sha256": report["observation_sha256"],
            "filename": "new-sonic.pth",
        },
    )
    assert response.status_code == 202, response.text
    work()
    result = api.get("/api/runs/" + response.json()["id"]).json()
    assert result["status"] == "succeeded", result
    return result


def install(api, review, **changes):
    payload = {
        "client_request_id": str(uuid4()),
        "plan_run_id": review["id"],
        "manifest_sha256": review["metadata"]["source_inspection"]["manifest_sha256"],
        "license_accepted": True,
        "workload_accepted": True,
        **changes,
    }
    return api.post("/api/model-hub/downloads", json=payload)


def test_closed_source_plan_native_admission_and_shared_binding(bridge):
    with TestClient(app) as api:
        review = plan(api)
        assert not bridge["downloads"]
        row = review["metadata"]["source_inspection"]["files"][0]
        assert row["assessment"]["requires_cpu_offload_consent"]
        response = install(api, review)
        assert response.status_code == 202, response.text
        queued = response.json()
        work()
        result = api.get("/api/setup/downloads/" + queued["id"]).json()
        assert result["run"]["status"] == "succeeded", result
    with control_session_factory()() as db:
        definition = db.get(ModelDefinition, result["definition_id"])
        assert definition.category == "video" and definition.capabilities == ["avatar"]
        binding = definition.metadata_json["avatar"]["binding"]
        assert binding["managed_runtime"] == bridge["runtime"]
        assert binding["checkpoint_profile"] == "sonic-whole-unet-v1" and binding["module_metadata_sha256"]
        assert "operation_id" not in str(binding) and "runtime/avatar-environments/" not in str(binding)


@pytest.mark.parametrize("field", ["license_accepted", "workload_accepted"])
def test_explicit_complete_component_and_offload_consent_is_required(bridge, field):
    with TestClient(app) as api:
        response = install(api, plan(api), **{field: False})
        assert response.status_code == 422, response.text
    assert not bridge["downloads"]


@pytest.mark.parametrize("fault", ["proof", "stop", "private_engine"])
def test_native_drift_or_cancellation_cannot_publish_a_model(bridge, fault):
    from app.task_control import cancel_task

    with TestClient(app) as api:
        queued = install(api, plan(api)).json()
        if fault == "proof":
            bridge["bad_proof"] = True
        elif fault == "private_engine":
            bridge["runtime"]["operation_id"] = "11111111-2222-4333-8444-555555555555"
        else:

            def stop():
                with control_session_factory()() as db:
                    cancel_task(db, db.get(Run, queued["run"]["id"]).task)
                    db.commit()

            bridge["after_verify"] = stop
        work()
        result = api.get("/api/setup/downloads/" + queued["id"]).json()
        assert result["run"]["status"] == ("canceled" if fault == "stop" else "failed"), result
    with control_session_factory()() as db:
        assert not list(db.scalars(select(ModelDefinition)))


def test_preparation_requires_exact_parent_ownership_and_dependency(bridge):
    from app.avatar_setup_job import AvatarSetupExecutor

    bridge["ready"] = False
    with TestClient(app) as api:
        response = install(api, plan(api))
        assert response.status_code == 202, response.text
        queued = response.json()
        assert queued["progress"]["phase"] == "preparing_avatar_engine"
        with control_session_factory()() as db:
            engine = db.get(Run, queued["progress"]["engine_run_id"])
            AvatarSetupExecutor().validate(engine)
            db.delete(db.get(RunDependency, (queued["run"]["id"], engine.id)))
            db.flush()
            with pytest.raises(ValueError):
                AvatarSetupExecutor().validate(engine)
            db.rollback()
    assert not bridge["downloads"]


@pytest.mark.parametrize("stage", ["engine", "weights"])
def test_stale_hardware_stops_before_any_model_or_engine_transfer(bridge, stage):
    bridge["ready"] = stage != "engine"
    with TestClient(app) as api:
        queued = install(api, plan(api)).json()
        bridge["hardware"]["memory"]["total_mib"] = 8192
        work()
        run_id = queued["progress"]["engine_run_id"] if stage == "engine" else queued["run"]["id"]
        run = api.get("/api/runs/" + run_id).json()
        assert run["status"] == "failed", run
        assert "hardware" in run["error_message"], run
    assert not bridge["downloads"]


def test_unqualified_runtime_cannot_get_recommended_or_installable(bridge):
    bridge["qualified"] = False
    with TestClient(app) as api:
        review = plan(api)
        row = review["metadata"]["source_inspection"]["files"][0]
        assert row["assessment"]["runtime_status"] == "runtime_unavailable"
        assert row["assessment"]["variant_advice"]["recommended"] is False
        response = install(api, review)
        assert response.status_code == 409, response.text
    assert not bridge["downloads"]


def test_shared_definition_does_not_reveal_private_import_runs(accounts, bridge):
    owner, alice, bob = accounts
    review = plan(owner)
    response = install(owner, review)
    assert response.status_code == 202, response.text
    queued = response.json()
    work()
    result = owner.get("/api/setup/downloads/" + queued["id"]).json()
    assert result["run"]["status"] == "succeeded", result
    shared = alice.get("/api/models/definitions/" + result["definition_id"])
    assert shared.status_code == 200
    assert shared.json()["last_verify_run_id"] is None
    assert bob.get("/api/setup/downloads/" + queued["id"]).status_code == 404
    assert bob.get("/api/runs/" + review["id"]).status_code == 404
    assert bob.get("/api/runs/" + result["run"]["id"]).status_code == 404


def test_hardware_choice_uses_real_per_device_capacity_and_known_ram(bridge):
    from app.hub_candidates import download_candidate

    with TestClient(app) as api:
        entry = download_candidate(plan(api)["metadata"]["source_inspection"]["candidate"])
    hardware = copy.deepcopy(bridge["hardware"])
    hardware["gpus"] = [{"index": 3, "memory_total_mib": 6144}, {"index": 9, "memory_total_mib": 6144}]
    assert not hub_avatar_candidates.recommendation(entry, hardware)["fits"]
    hardware["gpus"][1]["memory_total_mib"] = 12288
    assert hub_avatar_candidates.recommendation(entry, hardware)["gpus"] == [9]
    hardware["memory"]["total_mib"] = float("nan")
    assert not hub_avatar_candidates.recommendation(entry, hardware)["fits"]
