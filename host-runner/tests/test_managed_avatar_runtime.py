"""Shared readiness must never reveal another account's private setup coordinates."""

import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_station_runner import avatar_environment, avatar_prepare, avatar_selection, sonic_jobs, sonic_runtime
from test_sonic_jobs import prepared as prepared


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sonic_runtime,
        "get_settings",
        lambda: SimpleNamespace(sonic_whole_enabled=False, host_data_dir=lambda: tmp_path),
    )
    monkeypatch.setattr(avatar_selection, "selection", lambda *a: {"managed": True})
    monkeypatch.setattr(
        sonic_runtime, "installation", lambda: (tmp_path / "python", tmp_path / "source", tmp_path / "models")
    )


def test_shared_readiness_does_not_include_private_setup_path_or_uuid(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    secret = "11111111-2222-4333-8444-555555555555"

    def changed(*args):
        raise OSError("Missing /private/avatar-environments/" + secret + "/source/file.py")

    monkeypatch.setattr(sonic_runtime, "ready_recipe", changed)
    value = sonic_runtime.capabilities()
    assert not value["available"] and value["readiness"] == "unavailable"
    assert secret not in json.dumps(value) and "/private" not in json.dumps(value)


def test_managed_readiness_counts_only_compatible_gpus(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        sonic_runtime,
        "ready_recipe",
        lambda *a: {"id": "sonic_whole_768_v1", "observation": "a" * 64, "environment_id": "b" * 64},
    )
    monkeypatch.setattr(avatar_prepare, "driver_supported", lambda *a: True)
    monkeypatch.setattr(
        sonic_runtime,
        "collect",
        lambda *a: {
            "gpus": [{"index": 7, "memory_total_mib": 12288}, {"index": 11, "memory_total_mib": 4096}]
        },
    )
    value = sonic_runtime.capabilities()
    assert value["available"] and value["configuration_source"] == "managed"
    assert value["detected_gpu_count"] == 1 and value["eligible_gpu_indices"] == [7]


def test_ready_identity_binds_observed_environment_when_active_pointer_changes(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    runtime, models = tmp_path / "old/source", tmp_path / "old/models"
    observed = {
        "profile": avatar_environment.PROFILE,
        "manifest_sha256": "b" * 64,
        "operation_id": "11111111-2222-4333-8444-555555555555",
    }
    done = Future()
    done.set_result("c" * 64)
    monkeypatch.setattr(sonic_runtime, "_signature", lambda *a: ())
    monkeypatch.setattr(sonic_runtime, "_readiness", {(runtime, models, ()): done})
    monkeypatch.setattr(
        avatar_selection, "selection", lambda *a: {"managed": True, "sonic_models": tmp_path / "new/models"}
    )
    monkeypatch.setattr(avatar_environment, "read_json", lambda *a: observed)
    monkeypatch.setattr(
        avatar_environment, "resolve", lambda *a: {"sonic_models": models, "sonic_dir": runtime}
    )
    assert sonic_runtime.ready_recipe(runtime, models)["environment_id"] == avatar_environment.environment_id(
        observed
    )


def test_incompatible_driver_does_not_leave_a_false_launch_receipt(prepared, monkeypatch):
    body, manager, arguments = prepared
    body.recipe = {**body.recipe, "environment_id": "b" * 64}
    monkeypatch.setattr(
        avatar_environment,
        "resolve_id",
        lambda *a: {
            "sonic_python": Path(arguments["python"]).absolute(),
            "sonic_dir": arguments["runtime"],
            "sonic_models": arguments["models"],
            "environment": manager.data_dir / "prepared",
        },
    )
    monkeypatch.setattr(avatar_prepare, "driver_supported", lambda *a: False)
    with pytest.raises(ValueError, match="GPU or driver"):
        sonic_jobs.start_qualification(manager, body, **arguments)
    assert not manager.calls
    assert not (manager.data_dir / "runs" / str(body.run_id) / "whole-avatar-launch").exists()
