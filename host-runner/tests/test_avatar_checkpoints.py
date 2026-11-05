"""Closed avatar tensor admission and complete hardware budget; no inference."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import avatar_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.owned_models import owned_model, owned_safetensors
from fastapi import HTTPException
from test_torch_state_data import checkpoint


@pytest.fixture
def synthetic(monkeypatch):
    expected = {
        "tensor_count": 1,
        "schema_sha256": slots.fingerprint({"weight": [2]}),
        "module_metadata_sha256": slots.fingerprint({}),
        "allowed_dtypes": ["F32"],
        "runtime_profile": slots.RUNTIME,
        "role": "sonic_adapted_unet",
        "notice": "Structural inspection only, not inference",
    }
    monkeypatch.setattr(slots, "recipe", lambda profile: expected)
    return expected


@pytest.mark.parametrize("change", [None, "count", "graph", "precision", "versions"])
def test_slot_requires_complete_graph_precision_and_module_versions(tmp_path, synthetic, change):
    if change:
        field = {
            "count": "tensor_count",
            "graph": "schema_sha256",
            "precision": "allowed_dtypes",
            "versions": "module_metadata_sha256",
        }[change]
        synthetic[field] = 3 if change == "count" else ["F16"] if change == "precision" else "f" * 64
    path = tmp_path / "tensor-data.pth"
    path.write_bytes(checkpoint())
    before = path.stat()
    if change:
        with pytest.raises(ValueError, match="graph, precision or module-version"):
            slots.inspect_checkpoint(path, before.st_size, before.st_mtime, slots.PROFILE)
    else:
        report = slots.inspect_checkpoint(path, before.st_size, before.st_mtime, slots.PROFILE)
        assert report["source"] == "pytorch_zip_tensor_data"
        assert report["storage_layout_verified"] and not report["runtime_qualified"]
        assert report["role"] == "sonic_adapted_unet" and report["tensor_storage_bytes"] == 8
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize(
    "changed", [None, "runtime_manifest_sha256", "fixed_companions", "runtime_sdk_sha256"]
)
def test_slot_binds_actual_sonic_weight_role_and_complete_runtime(monkeypatch, changed):
    expected = slots.recipe(slots.PROFILE)
    assert expected["filename"] == "Sonic/unet.pth" and expected["tensor_count"] == 1492
    assert len(expected["fixed_companions"]) == 13 and expected["allowed_dtypes"] == ["F32"]
    assert "stable-video-diffusion-img2vid-xt/unet/config.json" in {
        v["filename"] for v in expected["fixed_companions"]
    }
    assert all(
        not v["filename"].endswith("unet/diffusion_pytorch_model.safetensors")
        for v in expected["fixed_companions"]
    )
    with pytest.raises(ValueError, match="supported avatar"):
        slots.recipe("../../other")
    if changed:
        original = Path.read_text

        def altered(path, *args, **kwargs):
            raw = original(path, *args, **kwargs)
            if path.name == slots.PROFILE + ".json":
                value = json.loads(raw)
                value[changed] = "changed"
                return json.dumps(value)
            return raw

        monkeypatch.setattr(Path, "read_text", altered)
        with pytest.raises(ValueError, match="runtime and companion"):
            slots.recipe(slots.PROFILE)


def test_typed_native_inspection_does_not_admit_generic_pickle_or_language_weights(
    tmp_path, synthetic, monkeypatch
):
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    content = checkpoint()
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "models/store" / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    path.chmod(0o400)
    body = VerifyModel(
        run_id=uuid4(),
        host_path="models/store/" + digest,
        model_sha256=digest,
        app_owned=True,
        size_bytes=len(content),
        mtime=path.stat().st_mtime,
        checkpoint_profile=slots.PROFILE,
        permissions=["filesystem_read", "manage_models"],
    )
    try:
        result = verify_model(body)
        assert result["host_path"] is None and result["image"] is None
        assert not result["checkpoint_profile"]["runtime_qualified"]
        for resolver in (owned_model, owned_safetensors):
            with pytest.raises(HTTPException):
                resolver(body.host_path, digest)
        with TestClient(app) as api:
            payload = body.model_dump(mode="json")
            assert api.post("/v1/models/verify", json=payload).status_code == 200
            assert api.post("/v1/models/verify", json={**payload, "permissions": []}).status_code == 403
            for extra in (
                {"check_image": True},
                {"check_context": True},
                {"app_owned": False},
                {"checkpoint_profile": "generic-pickle"},
                {"host_path": "/etc/passwd"},
                {"command": "anything"},
                {"expected_schema": "f" * 64},
            ):
                assert api.post("/v1/models/verify", json={**payload, **extra}).status_code == 422
            assert (
                api.post("/v1/models/verify", json={**payload, "mtime": payload["mtime"] + 10}).status_code
                == 409
            )
        path.chmod(0o600)
        path.write_bytes(b"\x80\x02cos\nsystem\n" + bytes(len(content) - 14))
        path.chmod(0o400)
        with pytest.raises(HTTPException):
            verify_model(body.model_copy(update={"mtime": path.stat().st_mtime}))
    finally:
        clear_settings_cache()


@pytest.mark.parametrize(
    "capacities,ram,driver,free,fits,available",
    [
        ([12288], 24576, True, 200 * 1024**3, True, True),
        ([6144, 6144], 32768, True, 200 * 1024**3, False, False),
        ([12288], 8192, True, 200 * 1024**3, False, False),
        ([12288], 32768, False, 200 * 1024**3, False, False),
        ([12288], 32768, True, 1, True, False),
    ],
)
def test_native_slot_requires_real_device_ram_driver_and_complete_disk_budget(
    tmp_path, monkeypatch, capacities, ram, driver, free, fits, available
):
    from ai_station_runner import avatar_prepare, sonic_runtime

    monkeypatch.setattr(
        avatar_prepare,
        "get_settings",
        lambda: SimpleNamespace(
            host_data_dir=lambda: tmp_path,
            sonic_python="",
            sonic_dir="",
            sonic_models="",
            sonic_whole_enabled=False,
        ),
    )
    monkeypatch.setattr(avatar_prepare, "QUALIFIED", True)
    monkeypatch.setattr(avatar_prepare, "available", lambda: True)
    monkeypatch.setattr(avatar_prepare, "driver_supported", lambda _: driver)
    monkeypatch.setattr(avatar_prepare.platform, "system", lambda: "Linux")
    monkeypatch.setattr(avatar_prepare.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(avatar_prepare.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(sonic_runtime, "capabilities", lambda: {"available": False})
    monkeypatch.setattr(avatar_prepare, "disk_usage", lambda _: SimpleNamespace(free=free))
    monkeypatch.setattr(
        avatar_prepare,
        "collect",
        lambda _: {
            "gpus": [{"index": 7 + i, "memory_total_mib": v} for i, v in enumerate(capacities)],
            "memory": {"total_mib": ram},
        },
    )
    result = avatar_prepare.catalog()
    assert result["checkpoint_slots"] == [slots.recipe(slots.PROFILE)]
    assert result["recommendation"]["fits"] is fits
    assert result["installation_available"] is available
    assert result["recommendation"]["cpu_offload"] and result["recommendation"]["ram_mib"] == 18432
    assert result["storage"]["download_bytes"] == sum(v["size_bytes"] for v in result["recipe"]["inputs"])
    assert not result["avatar_inference_tested_now"]


def test_metadata_profile_needs_no_inference_web_or_pickle_loader():
    code = """
import importlib.abc,sys,pickle
class NoHeavy(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','fastapi','uvicorn','sonic'}:
   raise ModuleNotFoundError('Metadata inspection cannot import inference or HTTP code')
sys.meta_path.insert(0,NoHeavy())
def forbidden(*args,**kwargs):raise AssertionError('No pickle loading')
pickle.load=pickle.loads=pickle.Unpickler=forbidden
from ai_station_runner.avatar_checkpoints import recipe,PROFILE
assert recipe(PROFILE)['tensor_count']==1492
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
