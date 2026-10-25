import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import krea2_native as native
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.processes import ProcessManager
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "venv/bin").mkdir(parents=True)
    (runtime / "venv/bin/python").symlink_to(sys.executable)
    sources = {}
    for name, revision in native.REVISIONS.items():
        (runtime / name / ".git").mkdir(parents=True)
        (runtime / name / ".git/HEAD").write_text(revision + "\n")
        sources[name] = {"revision": revision}
    (runtime / "ai-station-runtime.json").write_text(
        json.dumps(
            {
                "owner": "ai-station",
                "profile": "gpu-only",
                "sources": sources,
            }
        )
    )
    models = tmp_path / "models"
    files = []
    for relative in (
        "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
        "vae/qwen_image_vae.safetensors",
        "loras/krea2_general_edit_v2_r64.safetensors",
        "loras/krea2_identity_edit_v2_r64.safetensors",
    ):
        target = models / relative
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_bytes(b"model")
        files.append({"path": relative, "size": 5, "sha256": hashlib.sha256(b"model").hexdigest()})
    (models / "ai-station-model.json").write_text(json.dumps({"files": files}))
    model = models / "lustify.gguf"
    model.write_bytes(b"base")
    settings = SimpleNamespace(
        krea_enabled=True,
        krea_runtime_dir=str(runtime),
        krea_companions_dir=str(models),
        model_roots=str(models),
        host_data_dir=lambda: root,
    )
    monkeypatch.setattr(native, "get_settings", lambda: settings)
    monkeypatch.setattr(
        native,
        "collect",
        lambda root: {
            "gpus": [
                {"index": 3, "uuid": "GPU-aaaa"},
                {"index": 7, "uuid": "GPU-bbbb"},
            ]
        },
    )
    return settings, model


def request(model, **values):
    return native.KreaRunRequest(
        **{
            "run_id": str(uuid4()),
            "options": {"mode": "t2i", "prompt": "A red bicycle"},
            "gpus": [7, 3],
            "permissions": ["filesystem_read", "workspace_write"],
            "profile_sha256": native.capabilities()["profile_sha256"],
            "model_file": {"path": str(model), "size": 4, "sha256": hashlib.sha256(b"base").hexdigest()},
            **values,
        }
    )


def test_default_adapter_is_unavailable_without_installation(monkeypatch):
    monkeypatch.delenv("AI_STATION_KREA_ENABLED", raising=False)
    clear_settings_cache()
    assert native.capabilities()["available"] is False


def test_native_dispatch_binds_devices_files_and_owned_output(installed):
    settings, model = installed
    calls = []
    manager = SimpleNamespace(start=lambda **kw: calls.append(kw) or {"pid": 42})
    body = request(model)
    assert native.start(manager, body) == {"pid": 42}
    call = calls[0]
    assert call["executor"] == "photo_pipe"
    assert call["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-bbbb,GPU-aaaa"
    assert call["env"]["HF_HUB_OFFLINE"] == "1"
    assert call["argv"][1:3] == ["-m", "ai_station_runner.krea2_job"]
    config = json.loads(Path(call["argv"][-1]).read_text())
    assert set(config["files"]) == {"model", "encoder", "vae"}
    assert config["gpu_count"] == 2
    assert Path(config["output"]).name == f"{body.run_id}.png"
    assert Path(config["work"]).is_relative_to(settings.host_data_dir() / "runs")
    with pytest.raises(HTTPException) as error:
        native.start(manager, body)
    assert error.value.status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize("operation,role", [("img2img", "general"), ("recompose", "identity")])
def test_edit_binds_verified_reference_and_exactly_one_lora(installed, operation, role):
    from PIL import Image

    settings, model = installed
    source = settings.host_data_dir() / "artifacts/input.png"
    source.parent.mkdir()
    Image.new("RGB", (64, 64), "red").save(source)
    observation = {
        "relative_path": "artifacts/input.png",
        "size_bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    body = request(
        model, options={"mode": operation, "prompt": "Change the bicycle to blue"}, inputs=[observation]
    )
    calls = []
    native.start(SimpleNamespace(start=lambda **kw: calls.append(kw)), body)
    config = json.loads(Path(calls[0]["argv"][-1]).read_text())
    assert set(config["files"]) == {"model", "encoder", "vae", role}
    assert config["inputs"][0]["sha256"] == observation["sha256"]


@pytest.mark.parametrize("change", ["permission", "gpu", "model", "profile"])
def test_invalid_dispatch_never_starts_a_process(installed, change):
    settings, model = installed
    body = request(model)
    if change == "permission":
        body.permissions = []
    elif change == "gpu":
        body.gpus = [8]
    elif change == "model":
        model.write_bytes(b"changed")
    else:
        body.profile_sha256 = "0" * 64
    with pytest.raises(HTTPException):
        native.start(SimpleNamespace(start=lambda **kw: pytest.fail("Unexpected launch")), body)
    assert not list(settings.host_data_dir().glob("runs/*"))


def test_runtime_inside_container_writable_data_is_rejected(installed):
    settings, _model = installed
    settings.krea_runtime_dir = str(settings.host_data_dir())
    assert native.capabilities()["available"] is False


@pytest.mark.parametrize("gpus", [[3, 3], [-1], [3, 7, 8], [True]])
def test_malformed_gpu_bundles_are_rejected(installed, gpus):
    with pytest.raises(ValidationError):
        request(installed[1], gpus=gpus)


def test_stop_and_restart_inspection_reuse_owned_process_journal(installed):
    settings, model = installed
    python = Path(settings.krea_runtime_dir) / "venv/bin/python"
    python.unlink()
    # Synthetic native executable: no model import, GPU work or network.
    python.write_text(
        f"#!{sys.executable}\nimport time\nprint('fake krea ready',flush=True)\ntime.sleep(60)\n"
    )
    python.chmod(0o700)
    manager = ProcessManager(settings.host_data_dir(), grace_seconds=0.1)
    body = request(model)
    record = native.start(manager, body)
    try:
        assert record["pid"] > 0
        recovered = ProcessManager(settings.host_data_dir(), grace_seconds=0.1)
        assert recovered.inspect(str(body.run_id))["alive"] is True
        recovered.cancel(str(body.run_id))
        until = time.monotonic() + 5
        while recovered.inspect(str(body.run_id))["alive"] and time.monotonic() < until:
            time.sleep(0.05)
        info = recovered.inspect(str(body.run_id))
        assert info["alive"] is False
        assert info["status"] == "canceled"
        assert os.getpid() != record["pid"]
    finally:
        manager.cancel(str(body.run_id))
