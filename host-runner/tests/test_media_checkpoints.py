"""Tiny synthetic GGUFs verify slot structure without real models/GPU work."""

import hashlib
import json
import struct
from uuid import uuid4

import pytest
from ai_station_runner import media_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.gguf_headers import HEADER_BUDGET, inspect_header
from ai_station_runner.model_verify import VerifyModel, verify_model
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def clean_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def string(text):
    data = text.encode()
    return struct.pack("<Q", len(data)) + data


def gguf(*, shape=(32, 2), kind=30, offset=0, alignment=32, duplicate=False, count=None, architecture=None):
    names = ["layer.weight", "layer.weight" if duplicate else "layer.bias"]
    fields = string("general.alignment") + struct.pack("<II", 4, alignment)
    if architecture is not None:
        fields += string("general.architecture") + struct.pack("<I", 8) + string(architecture)
    out = (
        b"GGUF"
        + struct.pack("<IQQ", 3, len(names) if count is None else count, 1 + int(architecture is not None))
        + fields
    )
    for index, name in enumerate(names):
        dims = shape if not index else (32,)
        out += string(name) + struct.pack("<I", len(dims))
        out += struct.pack("<" + "Q" * len(dims), *dims)
        out += struct.pack("<IQ", kind, offset if not index else 256)
    return out + bytes((-len(out)) % 32) + bytes(1024)


@pytest.fixture
def synthetic(monkeypatch):
    shapes = {"layer.weight": [32, 2], "layer.bias": [32]}
    recipe = {
        "tensor_count": 2,
        "schema_sha256": hashlib.sha256(
            json.dumps(shapes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "allowed_ggml_types": [0, 1, 2, 3, 6, 7, 8, 10, 11, 12, 13, 14, 30],
        "runtime_profile": "fixed-synthetic-runtime",
        "role": "diffusion",
    }
    monkeypatch.setattr(slots, "recipe", lambda profile: recipe)
    return recipe


def inspect(tmp_path, data):
    model = tmp_path / "model.gguf"
    model.write_bytes(data)
    return slots.inspect_checkpoint(model, len(data), model.stat().st_mtime, slots.PROFILE)


def test_layout_and_graph_are_independent_of_quantization_and_preserve_bytes(tmp_path, synthetic):
    floating = inspect(tmp_path, gguf())
    quantized = inspect(tmp_path, gguf(kind=8))
    assert floating["schema_sha256"] == quantized["schema_sha256"] == synthetic["schema_sha256"]
    assert floating["tensor_storage_bytes"] == 192
    assert quantized["tensor_storage_bytes"] == 102
    assert not quantized["runtime_qualified"]
    assert (tmp_path / "model.gguf").read_bytes() == gguf(kind=8)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"shape": (64, 2)}, "dimensions differ"),
        ({"kind": 999}, "storage type"),
        ({"offset": 1}, "offset or extent"),
        ({"offset": 1024}, "offset or extent"),
        ({"offset": 256}, "overlap"),
        ({"alignment": 7}, "alignment"),
        ({"duplicate": True}, "Duplicate"),
        ({"count": 100001}, "descriptor budget"),
    ],
)
def test_incompatible_or_malformed_checkpoints_are_rejected(tmp_path, synthetic, changes, reason):
    with pytest.raises(ValueError, match=reason):
        inspect(tmp_path, gguf(**changes))


def test_quantized_row_divisibility_is_checked_independently_of_graph_match(tmp_path, synthetic):
    synthetic["schema_sha256"] = hashlib.sha256(
        json.dumps(
            {"layer.weight": [33, 2], "layer.bias": [32]}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="block size"):
        inspect(tmp_path, gguf(shape=(33, 2), kind=8))


def test_truncated_payload_and_descriptor_budget_refuse_without_tensor_reads(tmp_path, synthetic):
    data = gguf()[:100]
    with pytest.raises(ValueError):
        inspect(tmp_path, data)
    model = tmp_path / "bad.gguf"
    model.write_bytes(b"GGUF" + struct.pack("<IQQQ", 3, 1, 0, HEADER_BUDGET + 1))
    with pytest.raises(ValueError):
        inspect_header(
            model, model.stat().st_size, model.stat().st_mtime, keep_field=lambda k: False, tensors=True
        )


def test_false_qwen_architecture_tag_does_not_override_tensor_schema(tmp_path):
    # A model card/header claim cannot select a different image graph.
    with pytest.raises(ValueError, match="tensor count differs"):
        inspect(tmp_path, gguf(architecture="qwen_image"))


def test_typed_native_inspection_requires_private_verified_owned_source(tmp_path, monkeypatch, synthetic):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", "")
    clear_settings_cache()
    data = gguf()
    sha = hashlib.sha256(data).hexdigest()
    path = tmp_path / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    path.chmod(0o444)
    body = VerifyModel(
        run_id=uuid4(),
        host_path="models/store/" + sha,
        model_sha256=sha,
        app_owned=True,
        size_bytes=len(data),
        mtime=path.stat().st_mtime,
        checkpoint_profile=slots.PROFILE,
        permissions=["filesystem_read", "manage_models"],
    )
    try:
        result = verify_model(body)
        assert result["checkpoint_profile"]["source"] == "gguf_tensor_descriptors"
        assert result["host_path"] is None and result["relative_path"] == "models/store/" + sha
        assert result["image"] is None and not result["checkpoint_profile"]["runtime_qualified"]
        with pytest.raises(HTTPException) as denied:
            verify_model(body.model_copy(update={"permissions": []}))
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as changed:
            verify_model(body.model_copy(update={"size_bytes": 1}))
        assert changed.value.status_code == 409
        for update in (
            {"host_path": "/etc/passwd"},
            {"app_owned": False},
            {"check_context": True},
            {"check_image": True},
            {"runtime_profile": "llamacpp-cpu-linux-amd64-v1"},
        ):
            with pytest.raises(ValueError):
                VerifyModel.model_validate({**body.model_dump(), **update})
        path.chmod(0o644)
        with pytest.raises(HTTPException):
            verify_model(body)
    finally:
        clear_settings_cache()


def test_legacy_model_inspection_serialization_omits_new_coordinates():
    body = VerifyModel(run_id=uuid4(), host_path="/models/model.gguf", size_bytes=1, mtime=1, permissions=[])
    assert "checkpoint_profile" not in body.model_dump(mode="json")


def test_unknown_slot_and_changed_runtime_reference_are_not_admitted(monkeypatch):
    with pytest.raises(ValueError, match="supported runtime slot"):
        slots.recipe("../../unknown")
    original = slots.recipe(slots.PROFILE)
    assert original["tensor_count"] == 297 and original["role"] == "diffusion"
    from pathlib import Path

    read = Path.read_text

    def changed(path, *args, **kwargs):
        value = read(path, *args, **kwargs)
        if path.name == slots.PROFILE + ".json":
            data = json.loads(value)
            data["runtime_image_reference"] = "unknown-image"
            return json.dumps(data)
        return value

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(ValueError, match="requires review"):
        slots.recipe(slots.PROFILE)


def test_nonregular_and_symlink_sources_are_never_parsed(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(gguf())
    alias = tmp_path / "alias.gguf"
    alias.symlink_to(model)
    with pytest.raises(OSError):
        inspect_header(
            alias, model.stat().st_size, model.stat().st_mtime, keep_field=lambda k: False, tensors=True
        )
    with pytest.raises(ValueError, match="changed since discovery"):
        inspect_header(model, 1, model.stat().st_mtime, keep_field=lambda k: False, tensors=True)


def test_http_schema_rejects_runtime_or_source_overrides_before_inspection(tmp_path, monkeypatch, synthetic):
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    with TestClient(app) as api:
        body = {
            "run_id": str(uuid4()),
            "host_path": "models/store/" + "a" * 64,
            "model_sha256": "a" * 64,
            "app_owned": True,
            "size_bytes": 1000,
            "mtime": 1,
            "checkpoint_profile": slots.PROFILE,
            "permissions": [],
        }
        assert api.post("/v1/models/verify", json=body).status_code == 403
        for extra in (
            {"checkpoint_profile": "unreviewed"},
            {"command": "anything"},
            {"expected_schema": "b" * 64},
            {"host_path": "../private"},
            {"check_image": True},
        ):
            assert api.post("/v1/models/verify", json={**body, **extra}).status_code == 422
