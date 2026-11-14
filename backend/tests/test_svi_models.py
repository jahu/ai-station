"""A recurrent choice binds six actual registry files and one opaque engine."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import video_models
from app.model_setup import fingerprint
from app.models import ModelDefinition, ModelFile
from app.svi_executor import GEOMETRY, NAME, PROFILE, RAM_MIB, SviExecutor
from app.svi_models import ROLES, register_prepared
from fastapi import HTTPException
from sqlalchemy import select


@pytest.fixture
def prepared(session):
    files, inputs = [], []
    for index, role in enumerate(sorted(ROLES)):
        sha = f"{index + 1:064x}"
        row = ModelFile(
            relative_path="models/store/" + sha,
            sha256=sha,
            filename=role + ".bin",
            size_bytes=100 + index,
            mtime=1000.0,
            category="video",
            availability="present",
        )
        session.add(row)
        session.flush()
        files.append({"model_file_id": row.id, "sha256": sha, "size_bytes": row.size_bytes})
        inputs.append(
            {
                "role": role,
                "kind": "model",
                "filename": row.filename,
                "size_bytes": row.size_bytes,
                "sha256": sha,
            }
        )
    recipe = {"profile": PROFILE, "name": "SVI Pro", "inputs": inputs}
    digest = fingerprint(recipe)
    run = SimpleNamespace(
        id=str(uuid4()),
        parameters={"recipe": recipe, "manifest_sha256": digest},
        task=SimpleNamespace(metadata_json={"runtime_preparation": {"workload_accepted": True}}),
    )
    receipt = {
        "profile": PROFILE,
        "manifest_sha256": digest,
        "operation_id": run.id,
        "environment_prepared": True,
    }
    return run, receipt, files


def install(session, prepared):
    result = register_prepared(session, *prepared)
    return session.get(ModelDefinition, result["definition_id"]), result


def test_complete_svi_setup_registers_one_opaque_model_without_private_run_ids(session, prepared):
    row, result = install(session, prepared)
    run, _, _ = prepared
    assert row.status == "registered" and row.capabilities == ["animate", "film"]
    model = video_models.frozen_model(session, row.id)
    assert model["binding"]["managed_runtime"] == result["managed_runtime"]
    assert len(model["binding"]["components"]) == 6
    assert model["binding"]["continuation_frames"] == 4
    assert model["binding"]["ram_mib"] == RAM_MIB
    assert run.id not in str(row.metadata_json) and run.id not in str(result)
    assert register_prepared(session, *prepared) == result
    assert len(list(session.scalars(select(ModelDefinition)))) == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing_component",
        "wrong_primary",
        "changed_size",
        "missing_consent",
        "changed_runtime",
        "changed_geometry",
        "missing_component_role",
    ],
)
def test_unavailable_or_modified_component_bundle_cannot_be_selected(session, prepared, change):
    row, _ = install(session, prepared)
    binding = deepcopy(row.metadata_json["video"]["binding"])
    if change == "missing_component":
        session.get(ModelFile, binding["components"][-1]["id"]).availability = "missing"
    elif change == "wrong_primary":
        row.file_id = binding["components"][0]["id"]
        # Choose a different valid file deliberately, not an accidentally unchanged primary.
        row.file_id = next(v["id"] for v in binding["components"] if v["role"] != "wan_high_noise")
    elif change == "changed_size":
        session.get(ModelFile, binding["components"][-1]["id"]).size_bytes += 1
    elif change == "missing_consent":
        binding["workload_accepted"] = False
    elif change == "changed_runtime":
        binding["managed_runtime"]["profile"] = "foreign"
    elif change == "changed_geometry":
        binding["fps"] = 24
    else:
        binding["components"][-1]["role"] = binding["components"][0]["role"]
        binding["schema_sha256"] = fingerprint(binding["components"])
    row.metadata_json = {**row.metadata_json, "video": {**row.metadata_json["video"], "binding": binding}}
    with pytest.raises(HTTPException) as exc:
        video_models.frozen_model(session, row.id)
    assert exc.value.status_code == 409


def test_selection_snapshot_does_not_mutate_shared_definition(session, prepared):
    row, _ = install(session, prepared)
    frozen = video_models.frozen_model(session, row.id)
    frozen["binding"]["components"][0]["size_bytes"] += 1
    assert frozen != video_models.frozen_model(session, row.id)


@pytest.mark.parametrize(
    "change", ["profile", "operation_id", "manifest_sha256", "environment_prepared", "consent"]
)
def test_registration_requires_the_exact_accepted_activation_receipt(session, prepared, change):
    run, receipt, files = prepared
    if change == "consent":
        run.task.metadata_json["runtime_preparation"]["workload_accepted"] = False
    else:
        receipt[change] = False if change == "environment_prepared" else "changed"
    with pytest.raises(ValueError):
        register_prepared(session, run, receipt, files)
    assert not list(session.scalars(select(ModelDefinition)))


def test_unregistered_recurrent_executor_cannot_be_advertised_as_available(session, prepared, monkeypatch):
    from app.executors import EXECUTORS

    monkeypatch.delitem(EXECUTORS, NAME, raising=False)
    row, _ = install(session, prepared)
    monkeypatch.setattr(
        video_models.RunnerClient,
        "request",
        lambda *a: pytest.fail("Unavailable adapter queried native inference"),
    )
    assert video_models.choices(session)["items"][0]["available"] is False
    with pytest.raises(HTTPException, match="qualified"):
        video_models.profile_for(session, row.id)


def test_model_capabilities_use_only_the_recurrent_typed_engine_selection(session, prepared, monkeypatch):
    from app.executors import EXECUTORS

    monkeypatch.setitem(EXECUTORS, NAME, SviExecutor())
    row, result = install(session, prepared)
    calls = []

    def observe(_client, method, path, payload):
        calls.append((method, path, payload))
        return {
            "available": True,
            "backend": "wan22-svi-pro-q4",
            "managed_runtime": result["managed_runtime"],
            **GEOMETRY,
            "native_window_frames": 81,
            "continuation_frames": 4,
            "memory_estimate_mib": RAM_MIB,
            "eligible_gpu_indices": [7],
        }

    monkeypatch.setattr(video_models.RunnerClient, "request", observe)
    result = video_models.profile_for(session, row.id)
    assert result["recommended_memory_profile"] == "default"
    assert calls == [
        (
            "POST",
            "/v1/video/svi/model-capabilities",
            {"managed_runtime": result["managed_runtime"], "permissions": ["filesystem_read"]},
        )
    ]
    assert "15 fps" in video_models.choices(session)["items"][0]["profile"]


@pytest.mark.parametrize("stop", [False, True])
def test_existing_model_install_run_rechecks_bundle_without_single_checkpoint_verification(
    session, prepared, monkeypatch, stop
):
    from app.engine import tick
    from app.executors import EXECUTORS
    from app.model_definitions import EmptyBody
    from app.model_definitions import install as enqueue
    from app.models import Artifact, Run
    from app.runs import request_cancel

    monkeypatch.setitem(EXECUTORS, NAME, SviExecutor())
    row, result = install(session, prepared)
    session.commit()
    pending = enqueue(__import__("uuid").UUID(row.id), EmptyBody(), session)
    run = session.get(Run, pending["id"])
    assert "svi_model" in run.parameters
    assert "video_checkpoint_binding" not in run.parameters

    def observe(_client, method, path, payload):
        assert path == "/v1/video/svi/model-capabilities"
        if stop:
            request_cancel(session, run)
            session.commit()
        return {
            "available": True,
            "backend": "wan22-svi-pro-q4",
            "managed_runtime": result["managed_runtime"],
            **GEOMETRY,
            "native_window_frames": 81,
            "continuation_frames": 4,
            "memory_estimate_mib": RAM_MIB,
            "eligible_gpu_indices": [7],
        }

    monkeypatch.setattr(video_models.RunnerClient, "request", observe)
    monkeypatch.setattr(
        video_models.RunnerClient,
        "verify_model",
        lambda *a: pytest.fail("Recurrent model used single-checkpoint verification"),
    )
    assert tick(session, "model-recheck-worker") == run.id
    session.refresh(run)
    assert run.status == ("canceled" if stop else "succeeded"), run.error_message
    artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))
    assert len(artifacts) == (0 if stop else 1)
    if artifacts:
        assert artifacts[0].metadata_json["metadata_only"] is True


@pytest.mark.parametrize(
    "change",
    [
        "unavailable",
        "wrong_backend",
        "wrong_runtime",
        "wrong_fps",
        "wrong_overlap",
        "missing_gpu",
        "small_memory",
    ],
)
def test_selected_recurrent_model_rejects_incompatible_native_capabilities(
    session, prepared, monkeypatch, change
):
    from app.executors import EXECUTORS

    monkeypatch.setitem(EXECUTORS, NAME, SviExecutor())
    row, result = install(session, prepared)
    report = {
        "available": True,
        "backend": "wan22-svi-pro-q4",
        "managed_runtime": result["managed_runtime"],
        **GEOMETRY,
        "native_window_frames": 81,
        "continuation_frames": 4,
        "memory_estimate_mib": RAM_MIB,
        "eligible_gpu_indices": [7],
    }
    if change == "unavailable":
        report["available"] = False
    elif change == "wrong_backend":
        report["backend"] = "wan2.2-5b"
    elif change == "wrong_runtime":
        report["managed_runtime"] = {**report["managed_runtime"], "environment_id": "c" * 64}
    elif change == "wrong_fps":
        report["fps"] = 24
    elif change == "wrong_overlap":
        report["continuation_frames"] = 17
    elif change == "missing_gpu":
        report["eligible_gpu_indices"] = []
    else:
        report["memory_estimate_mib"] = 11264
    monkeypatch.setattr(video_models.RunnerClient, "request", lambda *a: report)
    with pytest.raises(HTTPException) as exc:
        video_models.profile_for(session, row.id)
    assert exc.value.status_code == 409


def test_stale_model_recheck_cannot_publish_a_receipt(session, prepared, monkeypatch):
    from datetime import timedelta
    from uuid import UUID

    from app.engine import tick
    from app.executors import EXECUTORS
    from app.model_definitions import EmptyBody
    from app.model_definitions import install as enqueue
    from app.models import Artifact, Run

    monkeypatch.setitem(EXECUTORS, NAME, SviExecutor())
    row, result = install(session, prepared)
    session.commit()
    pending = enqueue(UUID(row.id), EmptyBody(), session)
    run = session.get(Run, pending["id"])

    def observe(_client, method, path, payload):
        run.worker_id = "replacement-worker"
        run.claimed_at += timedelta(seconds=1)
        session.commit()
        return {
            "available": True,
            "backend": "wan22-svi-pro-q4",
            "managed_runtime": result["managed_runtime"],
            **GEOMETRY,
            "native_window_frames": 81,
            "continuation_frames": 4,
            "memory_estimate_mib": RAM_MIB,
            "eligible_gpu_indices": [7],
        }

    monkeypatch.setattr(video_models.RunnerClient, "request", observe)
    assert tick(session, "stale-recheck-worker") == run.id
    session.refresh(run)
    assert run.worker_id == "replacement-worker" and run.status == "running"
    assert not list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))
