"""Actual native dispatch/owned cancellation with a fake inference executable."""

import hashlib
import json
import struct
import time
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import memory_scope, video, video_checkpoints, video_environment, video_prepare
from ai_station_runner.config import get_settings
from test_video import bridge as bridge


@pytest.fixture
def selected(bridge, monkeypatch):
    settings = get_settings()
    root = settings.host_data_dir().resolve()
    header = json.dumps({"weight": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
    data = struct.pack("<Q", len(header)) + header + bytes(4)
    sha = hashlib.sha256(data).hexdigest()
    path = root / "models/store" / sha
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o400)
    schema = video_checkpoints.fingerprint({"weight": [2]})
    private = {
        "profile": video_environment.PROFILE,
        "manifest_sha256": "b" * 64,
        "operation_id": str(uuid4()),
    }
    public = video_environment.public_observation(private)
    paths = {
        key: Path(getattr(settings, key))
        for key in ("video_python", "comfy_dir", "wan_model", "wan_text_encoder", "wan_vae")
    }
    chosen = {**paths, "managed": True, "observation": private, "environment": root / "runtime/fake-video"}

    def environment(root, runtime=None):
        assert runtime in (None, public)
        return chosen

    monkeypatch.setattr(video_checkpoints, "managed_environment", environment)
    monkeypatch.setattr(
        video_checkpoints,
        "recipe",
        lambda p: {
            "runtime_manifest_sha256": private["manifest_sha256"],
            "runtime_profile": private["profile"],
            "tensor_count": 1,
            "schema_sha256": schema,
            "allowed_dtypes": ["F16"],
            "role": "wan_model",
        },
    )
    hardware = {"memory": {"total_mib": 32768}, "gpus": [{"index": 7, "memory_total_mib": 12288}]}
    monkeypatch.setattr(video, "collect", lambda root: hardware)
    monkeypatch.setattr(video_prepare, "driver_supported", lambda minimum: True)
    monkeypatch.setattr(video, "apg_observation", lambda p: None)
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    scopes = []

    def prefix(identity, memory):
        scopes.append((identity, memory))
        return []  # Test executable only; never opens a real model/GPU.

    monkeypatch.setattr(memory_scope, "scope_prefix", prefix)
    monkeypatch.setattr(memory_scope, "scope_environment", lambda: {})
    source = {
        "profile": video_checkpoints.PROFILE,
        "relative_path": "models/store/" + sha,
        "sha256": sha,
        "size_bytes": len(data),
        "mtime": path.stat().st_mtime,
        "schema_sha256": schema,
    }
    return {
        "source": source,
        "runtime": public,
        "path": path,
        "root": root,
        "paths": paths,
        "hardware": hardware,
        "scopes": scopes,
    }


def request(selected, **extra):
    return {
        "run_id": str(uuid4()),
        "prompt": "wait",
        "deadline_at": time.time() + 30,
        "gpu": 7,
        "permissions": ["filesystem_read", "workspace_write"],
        "checkpoint": selected["source"],
        "managed_runtime": selected["runtime"],
        "memory_profile": "bounded_11g",
        **extra,
    }


def test_explicit_model_uses_only_selected_diffusion_and_keeps_owned_stop(bridge, selected):
    body = request(selected)
    response = bridge.post("/v1/runs/video", json=body)
    assert response.status_code == 200 and response.json()["pid"] > 0, response.text
    assert selected["scopes"] == [(body["run_id"], 11264)]
    config = json.loads((selected["root"] / "runs" / body["run_id"] / "video/request.json").read_text())
    assert config["paths"]["wan_model"] == str(selected["path"])
    assert config["request"]["checkpoint"] == selected["source"]
    assert all(
        config["paths"][key] == str(value) for key, value in selected["paths"].items() if key != "wan_model"
    )
    assert bridge.get("/v1/process/" + body["run_id"]).json()["alive"]
    stopped = bridge.post("/v1/process/cancel", json={"run_id": body["run_id"]})
    assert stopped.status_code == 200 and not stopped.json()["alive"]
    assert not host_app.manager().inspect(body["run_id"])["alive"]


def test_model_readiness_uses_managed_engine_despite_configured_paths_and_requires_read(bridge, selected):
    payload = {
        "checkpoint": selected["source"],
        "managed_runtime": selected["runtime"],
        "permissions": ["filesystem_read"],
    }
    response = bridge.post("/v1/video/model-capabilities", json=payload)
    assert response.status_code == 200 and response.json()["available"], response.text
    assert response.json()["managed_runtime"] == selected["runtime"]
    assert response.json()["configuration_source"] == "managed"
    assert bridge.post("/v1/video/model-capabilities", json={**payload, "permissions": []}).status_code == 403
    assert not selected["scopes"]


@pytest.mark.parametrize(
    "change",
    [
        {"memory_profile": "default"},
        {"managed_runtime": None},
        {"width": 512},
        {"checkpoint": {"profile": "other"}},
        {"checkpoint": {"relative_path": "/etc/passwd"}},
    ],
)
def test_unreviewed_workload_or_source_cannot_reach_dispatch(bridge, selected, change):
    response = bridge.post("/v1/runs/video", json=request(selected, **change))
    assert response.status_code == 422 and not selected["scopes"]


def test_changed_checkpoint_or_physical_ram_refuses_before_an_owned_process(bridge, selected):
    body = request(selected)
    selected["hardware"]["memory"]["total_mib"] = 16384
    response = bridge.post("/v1/runs/video", json=body)
    assert response.status_code == 409 and "physical RAM" in response.text
    assert not (selected["root"] / "runs" / body["run_id"] / "video").exists()

    selected["hardware"]["memory"]["total_mib"] = 32768
    selected["path"].chmod(0o600)
    assert bridge.post("/v1/runs/video", json=body).status_code == 422
    assert not (selected["root"] / "runs" / body["run_id"] / "video").exists()


def test_native_checkpoint_validation_does_not_import_the_runner_web_stack(selected):
    import subprocess
    import sys

    code = """
import importlib.abc,sys
class NoWeb(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'fastapi','uvicorn'}:
   raise ModuleNotFoundError('The inference environment has no web stack')
sys.meta_path.insert(0,NoWeb())
from ai_station_runner.owned_model_files import verify_owned_model
from ai_station_runner.video_checkpoints import CheckpointSource,recipe,PROFILE
from ai_station_runner.video_environment import resolve_public
assert recipe(PROFILE)['tensor_count']==825
assert 'fastapi' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
