"""Real owned native dispatch/Stop and offline model views with tiny fake weights."""

import hashlib
import json
import os
import struct
import sys
import time
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import (
    audio,
    fish_runtime,
    memory_scope,
    speech_checkpoints,
    speech_environment,
    speech_runtime,
)
from ai_station_runner import speech_checkpoint_view as view
from ai_station_runner.config import clear_settings_cache
from fastapi.testclient import TestClient


@pytest.fixture
def selected(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()
    raw = json.dumps({"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
    content = struct.pack("<Q", len(raw)) + raw + bytes(4)
    sha = hashlib.sha256(content).hexdigest()
    path = tmp_path / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    path.chmod(0o400)
    folder = tmp_path / "runtime/fake-speech"
    models = folder / "models"
    models.mkdir(parents=True)
    (folder / "cache").mkdir()
    (models / speech_checkpoints.FILENAME).write_bytes(b"original")
    (models / "ve.pt").write_bytes(b"fixed-voice-encoder")
    script = folder / "fake_inference.py"
    script.write_text("import time; time.sleep(30)\n")
    private = {
        "profile": speech_checkpoints.RUNTIME,
        "manifest_sha256": "b" * 64,
        "operation_id": str(uuid4()),
    }
    runtime = speech_runtime.public_observation(private)
    chosen = {
        "python": Path(sys.executable),
        "script": script,
        "cache": folder / "cache",
        "models": models,
        "environment": folder,
        "managed": True,
        "observation": private,
    }

    def resolve(root, observation):
        if Path(root) != tmp_path or observation != runtime:
            raise ValueError("The selected engine changed")
        return chosen

    monkeypatch.setattr(speech_runtime, "resolve_public", resolve)
    monkeypatch.setattr(
        speech_checkpoints,
        "recipe",
        lambda profile: {
            "runtime_manifest_sha256": private["manifest_sha256"],
            "runtime_profile": private["profile"],
            "tensor_count": 1,
            "schema_sha256": speech_checkpoints.fingerprint({"weight": [1]}),
            "allowed_dtypes": ["F32"],
            "role": "chatterbox_t3",
            "notice": "Structural test fixture",
        },
    )
    monkeypatch.setattr(
        speech_environment,
        "recipe",
        lambda: {
            "inputs": [
                {"kind": "model", "filename": speech_checkpoints.FILENAME},
                {"kind": "model", "filename": "ve.pt"},
            ]
        },
    )
    monkeypatch.setattr(speech_environment, "fingerprint", lambda recipe: private["manifest_sha256"])
    hardware = {"memory": {"total_mib": 32768}, "gpus": [{"index": 7, "memory_total_mib": 12288}]}
    monkeypatch.setattr(audio, "collect", lambda root: hardware)
    monkeypatch.setattr(audio, "selection", lambda settings: None)
    monkeypatch.setattr(fish_runtime, "capabilities", lambda: {"available": False})
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    monkeypatch.setattr(memory_scope, "scope_environment", lambda: {})
    scopes = []
    monkeypatch.setattr(
        memory_scope, "scope_prefix", lambda identity, maximum: scopes.append((identity, maximum)) or []
    )
    voice = tmp_path / "artifacts/reference.wav"
    voice.parent.mkdir()
    with wave.open(str(voice), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))
    source = {
        "profile": speech_checkpoints.PROFILE,
        "relative_path": "models/store/" + sha,
        "sha256": sha,
        "size_bytes": len(content),
        "mtime": path.stat().st_mtime,
        "schema_sha256": speech_checkpoints.fingerprint({"weight": [1]}),
    }
    fixture = {
        "root": tmp_path,
        "path": path,
        "source": source,
        "runtime": runtime,
        "folder": folder,
        "models": models,
        "hardware": hardware,
        "scopes": scopes,
    }
    try:
        yield fixture
    finally:
        host_app.manager().shutdown()
        host_app.reset_manager()
        clear_settings_cache()


def request(selected, **extra):
    return {
        "run_id": str(uuid4()),
        "deadline_at": time.time() + 60,
        "text": "wait",
        "reference_relative": "artifacts/reference.wav",
        "gpu": 7,
        "permissions": ["filesystem_read", "workspace_write"],
        "checkpoint": selected["source"],
        "managed_runtime": selected["runtime"],
        "runtime_manifest_sha256": selected["runtime"]["manifest_sha256"],
        **extra,
    }


def test_selected_checkpoint_dispatch_retains_owned_process_stop_and_only_generation_permissions(selected):
    body = request(selected)
    with TestClient(host_app.app) as api:
        started = api.post("/v1/runs/audio", json=body)
        assert started.status_code == 200 and started.json()["pid"] > 0, started.text
        assert selected["scopes"] == [(body["run_id"], 11264)]
        assert api.get("/v1/process/" + body["run_id"]).json()["alive"]
        config = selected["root"] / "runs" / body["run_id"] / "speech/checkpoint.json"
        assert json.loads(config.read_text())["checkpoint"] == selected["source"]
        assert api.post("/v1/runs/audio", json=body).status_code == 409
        assert api.get("/v1/process/" + body["run_id"]).json()["pid"] == started.json()["pid"]
        stopped = api.post("/v1/process/cancel", json={"run_id": body["run_id"]})
        assert stopped.status_code == 200 and not stopped.json()["alive"]


def test_selected_readiness_bypasses_missing_default_without_starting_any_process(selected):
    with TestClient(host_app.app) as api:
        assert not api.get("/v1/audio/capabilities").json()["available"]
        payload = {
            "checkpoint": selected["source"],
            "managed_runtime": selected["runtime"],
            "permissions": ["filesystem_read"],
        }
        response = api.post("/v1/audio/model-capabilities", json=payload)
        assert response.status_code == 200 and response.json()["available"], response.text
        assert response.json()["managed_runtime"] == selected["runtime"]
        assert (
            api.post("/v1/audio/model-capabilities", json={**payload, "permissions": []}).status_code == 403
        )
        assert not selected["scopes"]


@pytest.mark.parametrize(
    "change",
    [
        {"deadline_at": None},
        {"managed_runtime": None},
        {"checkpoint": {"relative_path": "/etc/passwd"}},
        {"runtime_manifest_sha256": "f" * 64},
    ],
)
def test_unfrozen_or_untrusted_speech_coordinates_never_reach_a_process(selected, change):
    with TestClient(host_app.app) as api:
        assert api.post("/v1/runs/audio", json=request(selected, **change)).status_code == 422
    assert not selected["scopes"]


@pytest.mark.parametrize("change", ["ram", "gpu", "writable"])
def test_changed_resource_or_object_refuses_before_start(selected, change):
    if change == "ram":
        selected["hardware"]["memory"]["total_mib"] = 8192
    elif change == "gpu":
        selected["hardware"]["gpus"][0]["memory_total_mib"] = 4096
    else:
        selected["path"].chmod(0o600)
    with TestClient(host_app.app) as api:
        response = api.post("/v1/runs/audio", json=request(selected))
        assert response.status_code == 409, response.text
    assert not selected["scopes"]


def job(selected, monkeypatch):
    identity = str(uuid4())
    path = selected["root"] / "runs" / identity / "speech/checkpoint.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": identity,
                "deadline_at": time.time() + 60,
                "checkpoint": selected["source"],
                "managed_runtime": selected["runtime"],
            }
        )
    )
    path.chmod(0o600)
    monkeypatch.setattr(view.sys, "base_prefix", str(selected["folder"] / "python"))
    monkeypatch.setattr(view, "deadline_at", lambda value: None)
    return identity, path


def test_offline_child_replaces_only_t3_and_keeps_original_companions_and_environment(selected, monkeypatch):
    identity, path = job(selected, monkeypatch)
    models = view.selected_models(path, identity, selected["folder"])
    assert (models / speech_checkpoints.FILENAME).resolve() == selected["path"]
    assert (models / "ve.pt").resolve() == selected["models"] / "ve.pt"
    assert (selected["models"] / speech_checkpoints.FILENAME).read_bytes() == b"original"
    with pytest.raises(ValueError, match="existing selected"):
        view.selected_models(path, identity, selected["folder"])


def test_child_rehashes_weights_even_if_filename_header_size_and_mtime_are_unchanged(selected, monkeypatch):
    identity, path = job(selected, monkeypatch)
    info = selected["path"].stat()
    content = selected["path"].read_bytes()
    selected["path"].chmod(0o600)
    selected["path"].write_bytes(content[:-4] + b"evil")
    os.utime(selected["path"], ns=(info.st_atime_ns, info.st_mtime_ns))
    selected["path"].chmod(0o400)
    with pytest.raises(ValueError, match="content changed"):
        view.selected_models(path, identity, selected["folder"])
    assert not (path.parent / "models").exists()


@pytest.mark.parametrize("change", ["run", "interpreter", "environment"])
def test_child_will_not_borrow_another_run_interpreter_or_environment(selected, monkeypatch, change):
    identity, path = job(selected, monkeypatch)
    if change == "run":
        identity = str(uuid4())
    elif change == "interpreter":
        monkeypatch.setattr(view.sys, "base_prefix", str(selected["root"] / "other-python"))
    environment = selected["root"] if change == "environment" else selected["folder"]
    with pytest.raises(ValueError):
        view.selected_models(path, identity, environment)
    assert not (path.parent / "models").exists()


def test_child_deadline_is_absolute_and_independent_of_parent_polling(monkeypatch):
    calls = []
    monkeypatch.setattr(view.time, "time", lambda: 100)
    monkeypatch.setattr(view.signal, "signal", lambda *args: None)
    monkeypatch.setattr(view.signal, "setitimer", lambda *args: calls.append(args))
    with pytest.raises(TimeoutError):
        view.deadline_at(99)
    view.deadline_at(125)
    assert calls == [(view.signal.ITIMER_REAL, 25)]
