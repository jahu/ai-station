"""Music diffusion metadata admission, closed runtime binding and typed API; no model inference."""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import music_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.owned_models import owned_model
from fastapi import HTTPException


def checkpoint(*, changed=None, dtype="BF16"):
    width = 2 if dtype == "BF16" else 4
    header = {"diffusion.weight": {"dtype": dtype, "shape": [2, 2], "data_offsets": [0, 4 * width]}}
    header["diffusion.bias"] = {"dtype": dtype, "shape": [2], "data_offsets": [4 * width, 6 * width]}
    if changed:
        changed(header)
    raw = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack("<Q", len(raw)) + raw + bytes(6 * width)


@pytest.fixture
def synthetic(monkeypatch):
    expected = {
        "tensor_count": 2,
        "schema_sha256": slots.fingerprint({"diffusion.weight": [2, 2], "diffusion.bias": [2]}),
        "allowed_dtypes": ["BF16"],
        "runtime_profile": slots.RUNTIME,
        "role": "ace_step15_turbo_diffusion",
        "notice": "Structural inspection only, not inference",
    }
    monkeypatch.setattr(slots, "recipe", lambda profile: expected)
    return expected


def test_fixed_graph_reads_only_metadata_and_does_not_grant_runtime_authority(
    tmp_path, synthetic, monkeypatch
):
    from ai_station_runner import safetensors_headers as headers

    content = checkpoint()
    path = tmp_path / "new-diffusion.safetensors"
    path.write_bytes(content)
    fdopen = headers.os.fdopen
    reads = []

    class HeaderOnly:
        def __init__(self, fd, *args):
            self.handle = fdopen(fd, *args)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, count):
            assert self.handle.tell() + count <= len(content) - 12
            reads.append(count)
            return self.handle.read(count)

    monkeypatch.setattr(headers.os, "fdopen", HeaderOnly)
    before = path.stat()
    report = slots.inspect_checkpoint(path, before.st_size, before.st_mtime, slots.PROFILE)
    assert report["tensor_count"] == 2 and report["dtypes"] == ["BF16"]
    assert report["schema_sha256"] == synthetic["schema_sha256"]
    assert report["source"] == "safetensors_descriptors" and not report["runtime_qualified"]
    assert report["tensor_storage_bytes"] == 12 and sum(reads) == len(content) - 12
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("change", ["shape", "name", "count", "precision", "payload"])
def test_other_graph_precision_or_layout_cannot_use_this_music_slot(tmp_path, synthetic, change):
    def alter(header):
        if change == "shape":
            header["diffusion.weight"]["shape"] = [4]
        elif change == "name":
            header["not-diffusion.weight"] = header.pop("diffusion.weight")
        elif change == "count":
            header.pop("diffusion.bias")
        elif change == "payload":
            header["diffusion.bias"]["data_offsets"] = [8, 16]

    content = checkpoint(changed=alter, dtype="F32" if change == "precision" else "BF16")
    path = tmp_path / "unqualified.safetensors"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        slots.inspect_checkpoint(path, path.stat().st_size, path.stat().st_mtime, slots.PROFILE)


def test_slot_is_bound_to_the_complete_existing_runtime_and_companions(monkeypatch):
    expected = slots.recipe(slots.PROFILE)
    assert expected["tensor_count"] == 677 and expected["allowed_dtypes"] == ["BF16"]
    assert expected["role"] == "ace_step15_turbo_diffusion" and len(expected["fixed_companions"]) == 15
    with pytest.raises(ValueError, match="supported music"):
        slots.recipe("../../other")
    original = Path.read_text

    def changed(path, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        if path.name == slots.PROFILE + ".json":
            value = json.loads(raw)
            value["fixed_companions"][0]["sha256"] = "f" * 64
            return json.dumps(value)
        return raw

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(ValueError, match="runtime and companion"):
        slots.recipe(slots.PROFILE)


def test_typed_native_api_keeps_owned_permission_and_legacy_gguf_boundaries(tmp_path, synthetic, monkeypatch):
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
        assert result["checkpoint_profile"]["role"] == "ace_step15_turbo_diffusion"
        with pytest.raises(HTTPException):
            owned_model(body.host_path, digest)
        with TestClient(app) as api:
            payload = body.model_dump(mode="json")
            assert api.post("/v1/models/verify", json=payload).status_code == 200
            assert api.post("/v1/models/verify", json={**payload, "permissions": []}).status_code == 403
            for extra in (
                {"check_image": True},
                {"check_context": True},
                {"app_owned": False},
                {"checkpoint_profile": "other"},
                {"host_path": "/etc/passwd"},
                {"command": "anything"},
                {"expected_schema": "a" * 64},
            ):
                assert api.post("/v1/models/verify", json={**payload, **extra}).status_code == 422
            assert (
                api.post("/v1/models/verify", json={**payload, "mtime": payload["mtime"] + 10}).status_code
                == 409
            )
        path.chmod(0o600)
        with pytest.raises(HTTPException):
            verify_model(body)
    finally:
        clear_settings_cache()


def test_music_descriptor_inspection_needs_no_inference_or_web_packages():
    code = """
import importlib.abc,sys
class NoHeavy(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','fastapi','uvicorn','acestep'}:
   raise ModuleNotFoundError('Metadata inspection cannot load an inference or HTTP stack')
sys.meta_path.insert(0,NoHeavy())
from ai_station_runner.music_checkpoints import recipe,PROFILE
assert recipe(PROFILE)['tensor_count']==677
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)


@pytest.mark.parametrize(
    ("capacities", "ram", "fits"),
    [([12288], 24576, True), ([6144, 6144], 32768, False), ([12288], 8192, False)],
)
def test_slot_metadata_does_not_bypass_the_existing_complete_music_hardware_gate(
    tmp_path, monkeypatch, capacities, ram, fits
):
    from types import SimpleNamespace

    from ai_station_runner import music, music_prepare

    monkeypatch.setattr(
        music_prepare,
        "get_settings",
        lambda: SimpleNamespace(
            host_data_dir=lambda: tmp_path,
            music_python=None,
            music_source_dir=None,
            music_model_dir=None,
        ),
    )
    monkeypatch.setattr(music_prepare, "QUALIFIED", True)
    monkeypatch.setattr(music_prepare, "available", lambda: True)
    monkeypatch.setattr(music_prepare.platform, "system", lambda: "Linux")
    monkeypatch.setattr(music_prepare.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(music_prepare.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(music, "capabilities", lambda: {"available": False})
    monkeypatch.setattr(music_prepare, "disk_usage", lambda root: SimpleNamespace(free=200 * 1024**3))
    monkeypatch.setattr(
        music_prepare,
        "collect",
        lambda root: {
            "gpus": [{"index": 7 + i, "memory_total_mib": value} for i, value in enumerate(capacities)],
            "memory": {"total_mib": ram},
        },
    )
    result = music_prepare.catalog()
    assert result["checkpoint_slots"] == [slots.recipe(slots.PROFILE)]
    assert result["recommendation"]["fits"] is fits
    assert result["installation_available"] is fits
    assert result["recommendation"]["cpu_offload"] is True
    assert result["music_inference_tested_now"] is False
