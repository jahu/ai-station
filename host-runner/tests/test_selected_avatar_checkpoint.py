"""Frozen avatar weights, exact engines, bounded dispatch and replay; no GPU."""

import hashlib
import json
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_station_runner import avatar_checkpoints as slots
from ai_station_runner import (
    avatar_environment,
    avatar_prepare,
    avatar_selection,
    sonic_inference,
    sonic_jobs,
    sonic_runtime,
)
from ai_station_runner.sonic_contract import IMPLEMENTATION_FILES, checked_request
from ai_station_runner.torch_state_zip import inspect_archive
from pydantic import ValidationError
from test_sonic_jobs import prepared as prepared
from test_torch_state_data import checkpoint


@pytest.fixture
def selected(prepared, monkeypatch):
    body, manager, arguments = prepared
    raw = checkpoint()
    digest = hashlib.sha256(raw).hexdigest()
    path = manager.data_dir / "models/store" / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    path.chmod(0o400)
    report = inspect_archive(path, len(raw), path.stat().st_mtime)
    expected = {
        **report,
        "profile": slots.PROFILE,
        "runtime_profile": slots.RUNTIME,
        "allowed_dtypes": ["F32"],
        "runtime_manifest_sha256": "a" * 64,
        "role": "sonic_adapted_unet",
        "notice": "Synthetic graph, never inference",
    }

    def recipe(profile):
        if profile != slots.PROFILE:
            raise ValueError("Unsupported avatar profile")
        return expected

    monkeypatch.setattr(slots, "recipe", recipe)
    source = {
        "profile": slots.PROFILE,
        "relative_path": "models/store/" + digest,
        "sha256": digest,
        "size_bytes": len(raw),
        "mtime": path.stat().st_mtime,
        "schema_sha256": report["schema_sha256"],
        "module_metadata_sha256": report["module_metadata_sha256"],
    }
    managed = {
        "sonic_python": Path(arguments["python"]).absolute(),
        "sonic_dir": arguments["runtime"],
        "sonic_models": arguments["models"],
        "environment": manager.data_dir / "engine",
        "managed": True,
        "observation": {
            "profile": slots.RUNTIME,
            "manifest_sha256": "a" * 64,
            "operation_id": "11111111-2222-4333-8444-555555555555",
        },
    }

    def resolve(root, identity):
        if identity != "b" * 64:
            raise ValueError("Missing exact engine")
        return managed

    monkeypatch.setattr(avatar_environment, "resolve_id", resolve)
    monkeypatch.setattr(avatar_prepare, "driver_supported", lambda _: True)
    body = sonic_jobs.WholeAvatarRequest.model_validate(
        {
            **body.model_dump(mode="json"),
            "checkpoint": source,
            "recipe": {**body.recipe, "environment_id": "b" * 64},
            "gpus": [7],
        }
    )
    arguments["hardware"] = {
        "gpus": [{"index": 7, "uuid": "GPU-first", "memory_total_mib": 12288}],
        "memory": {"total_mib": 24576},
    }
    return body, manager, arguments, path, managed


def test_legacy_request_wire_is_unchanged_and_selected_request_freezes_new_version(prepared, selected):
    original, _, _ = prepared
    body, _, _, _, _ = selected
    assert original.native_request()["version"] == 1 and "checkpoint" not in original.native_request()
    assert "checkpoint" not in original.model_dump(mode="json")
    request = body.native_request()
    assert request["version"] == 2 and request["checkpoint"] == body.checkpoint
    assert checked_request(request) == request
    with pytest.raises(ValueError):
        checked_request({**request, "version": 1})


@pytest.mark.parametrize(
    "change",
    [
        {"relative_path": "/etc/passwd"},
        {"sha256": "f" * 64},
        {"schema_sha256": "f" * 64},
        {"module_metadata_sha256": "f" * 64},
        {"profile": "unknown"},
        {"size_bytes": True},
        {"mtime": float("nan")},
        {"command": "anything"},
    ],
)
def test_selected_source_coordinates_are_closed_and_not_execution_parameters(selected, change):
    body, _, _, _, _ = selected
    with pytest.raises(ValidationError):
        sonic_jobs.WholeAvatarRequest.model_validate(
            {**body.model_dump(mode="json"), "checkpoint": {**body.checkpoint, **change}}
        )


@pytest.mark.parametrize("change", [{"recipe": {"id": "sonic_whole_768_v1", "observation": "c" * 64}}])
def test_new_checkpoint_requires_exact_managed_profile(selected, change):
    body, _, _, _, _ = selected
    with pytest.raises(ValidationError):
        sonic_jobs.WholeAvatarRequest.model_validate({**body.model_dump(mode="json"), **change})


def test_selected_weights_preserve_the_existing_two_gpu_guidance_path(selected):
    body, manager, arguments, _, _ = selected
    body = sonic_jobs.WholeAvatarRequest.model_validate({**body.model_dump(mode="json"), "gpus": [7, 11]})
    arguments["hardware"]["gpus"].append({"index": 11, "uuid": "GPU-second", "memory_total_mib": 12288})
    sonic_jobs.start_qualification(manager, body, **arguments)
    assert manager.calls[0]["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-first,GPU-second"
    assert body.native_request()["device_count"] == 2


def test_normal_dispatch_keeps_unqualified_adapter_unavailable(selected):
    body, manager, arguments, _, _ = selected
    with pytest.raises(ValueError, match="still being qualified"):
        sonic_jobs._start_owned(manager, body, **arguments)
    assert not manager.calls and not (manager.data_dir / "runs").exists()


def test_opted_in_launch_freezes_source_and_replay_never_reloads_a_changed_default(selected, monkeypatch):
    body, manager, arguments, path, _ = selected
    sonic_jobs.start_qualification(manager, body, **arguments)
    assert len(manager.calls) == 1
    call = manager.calls[0]
    frozen = json.loads((call["cwd"] / "request.json").read_text())
    assert frozen["checkpoint"] == body.checkpoint and frozen["version"] == 2
    assert call["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-first"
    assert call["deadline_at"] == body.deadline_at
    path.unlink()  # The already-owned process remains inspectable; no new start.
    monkeypatch.setattr(
        slots, "selected_environment", lambda *a: pytest.fail("Replay cannot choose/reload current weights")
    )
    result = sonic_jobs.start_qualification(manager, body, **arguments)
    assert result["pid"] == 77 and len(manager.calls) == 1


@pytest.mark.parametrize("change", ["engine", "writable", "mtime", "ram", "gpu"])
def test_changed_engine_source_or_hardware_fails_before_creating_launch_receipts(selected, change):
    body, manager, arguments, path, managed = selected
    if change == "engine":
        managed["observation"]["manifest_sha256"] = "f" * 64
    elif change == "writable":
        path.chmod(0o600)
    elif change == "mtime":
        body.checkpoint = {**body.checkpoint, "mtime": 0}
    elif change == "ram":
        arguments["hardware"]["memory"]["total_mib"] = 8192
    elif change == "gpu":
        arguments["hardware"]["gpus"][0]["memory_total_mib"] = 6144
    with pytest.raises(ValueError):
        sonic_jobs.start_qualification(manager, body, **arguments)
    assert not manager.calls and not (manager.data_dir / "runs").exists()


def test_selected_content_hash_fails_before_importing_torch(selected, monkeypatch):
    body, manager, _, path, _ = selected
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o400)
    source = {**body.checkpoint, "mtime": path.stat().st_mtime}
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(ValueError, match="SHA-256"):
        slots.load_selected(manager.data_dir, source)


def test_inference_validates_selected_weights_before_any_framework_or_upstream_import(selected, monkeypatch):
    body, manager, _, _, _ = selected

    def rejected(root, source):
        assert root == manager.data_dir and source == body.checkpoint
        raise ValueError("Selected hash rejected before frameworks")

    monkeypatch.setattr(slots, "load_selected", rejected)
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "sonic", None)
    with pytest.raises(ValueError, match="before frameworks"):
        sonic_inference.generate(
            None,
            None,
            None,
            None,
            None,
            192,
            192,
            43,
            1,
            checkpoint=body.checkpoint,
            data_root=manager.data_dir,
        )


def test_explicit_engine_selection_wins_while_no_choice_keeps_configured_default(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        host_data_dir=lambda: tmp_path,
        sonic_whole_enabled=True,
        sonic_python="/legacy/python",
        sonic_dir="/legacy/source",
        sonic_models="/legacy/models",
    )
    selected = {"managed": True, "sentinel": "exact engine"}

    def resolve(root, identity):
        if identity != "b" * 64:
            raise ValueError("missing")
        return selected

    monkeypatch.setattr(avatar_environment, "resolve_id", resolve)
    monkeypatch.setattr(avatar_prepare, "QUALIFIED", True)
    assert avatar_selection.selection(settings, "b" * 64) == selected
    assert avatar_selection.selection(settings)["sonic_dir"] == Path("/legacy/source")
    assert avatar_selection.selection(settings, "f" * 64) is None
    assert avatar_selection.selection(settings, {"environment_id": "b" * 64}) is None


def test_ready_recipe_binds_explicit_engine_without_consulting_current_default(tmp_path, monkeypatch):
    runtime, models = tmp_path / "old/source", tmp_path / "old/models"
    observed = {
        "profile": avatar_environment.PROFILE,
        "manifest_sha256": "a" * 64,
        "operation_id": "11111111-2222-4333-8444-555555555555",
    }
    done = Future()
    done.set_result("c" * 64)
    monkeypatch.setattr(sonic_runtime, "_signature", lambda *a: ())
    monkeypatch.setattr(sonic_runtime, "_readiness", {(runtime, models, ()): done})
    monkeypatch.setattr(
        sonic_runtime, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: tmp_path)
    )

    def select(settings, identity):
        assert identity == "b" * 64
        return {"managed": True}

    monkeypatch.setattr(avatar_selection, "selection", select)
    monkeypatch.setattr(avatar_environment, "read_json", lambda *a: observed)
    monkeypatch.setattr(
        avatar_environment, "resolve", lambda *a: {"sonic_dir": runtime, "sonic_models": models}
    )
    result = sonic_runtime.ready_recipe(runtime, models, environment_identity="b" * 64)
    assert result["environment_id"] == avatar_environment.environment_id(observed)


def test_all_selected_loader_code_and_recipe_participate_in_native_observation():
    assert {
        "avatar_checkpoints.py",
        "torch_state_data.py",
        "torch_state_zip.py",
        "torch_state_loader.py",
        "owned_model_files.py",
        "recipes/sonic-whole-unet-v1.json",
    } <= set(IMPLEMENTATION_FILES)
