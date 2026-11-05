"""SafeTensors graph admission with tiny owned files; no Torch, SDK or GPU."""

import hashlib
import json
import struct
from uuid import uuid4

import pytest
from ai_station_runner import safetensors_headers as headers
from ai_station_runner import video_checkpoints as slots
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.owned_models import owned_model
from fastapi import HTTPException


def checkpoint(header=None, payload=bytes(12)):
    header = header or {
        "layer.weight": {"dtype": "F16", "shape": [2, 2], "data_offsets": [0, 8]},
        "layer.bias": {"dtype": "F16", "shape": [2], "data_offsets": [8, 12]},
    }
    raw = json.dumps(header, separators=(",", ":")).encode() if isinstance(header, dict) else header
    return struct.pack("<Q", len(raw)) + raw + payload


@pytest.fixture
def synthetic(monkeypatch):
    recipe = {
        "tensor_count": 2,
        "schema_sha256": slots.fingerprint({"layer.weight": [2, 2], "layer.bias": [2]}),
        "allowed_dtypes": ["F16"],
        "runtime_profile": "fixed-video-test-runtime",
        "role": "wan_model",
    }
    monkeypatch.setattr(slots, "recipe", lambda profile: recipe)
    return recipe


def inspect(tmp_path, content):
    path = tmp_path / "model.safetensors"
    path.write_bytes(content)
    return headers.inspect_header(path, path.stat().st_size, path.stat().st_mtime)


def test_complete_graph_storage_and_no_payload_read(tmp_path, synthetic, monkeypatch):
    from pathlib import Path

    content = checkpoint()
    path = tmp_path / "model.safetensors"
    path.write_bytes(content)
    fdopen = headers.os.fdopen
    reads = []

    class HeaderOnly:
        def __init__(self, fd, *args):
            self.file = fdopen(fd, *args)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def fileno(self):
            return self.file.fileno()

        def read(self, count):
            reads.append(count)
            assert self.file.tell() + count <= len(content) - 12
            return self.file.read(count)

    monkeypatch.setattr(headers.os, "fdopen", HeaderOnly)
    before = Path.stat(path)
    report = slots.inspect_checkpoint(path, before.st_size, before.st_mtime, slots.PROFILE)
    assert report["source"] == "safetensors_descriptors" and not report["runtime_qualified"]
    assert report["schema_sha256"] == synthetic["schema_sha256"] and report["tensor_count"] == 2
    assert report["tensor_storage_bytes"] == 12 and sum(reads) == len(content) - 12
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize(
    "raw,reason",
    [
        (b'{"x":{},"x":{}}', "Duplicate"),
        (b'{"x":{"dtype":"F16","dtype":"F32"}}', "Duplicate"),
        (b'{"x":NaN}', "Non-finite"),
        (b'{"__metadata__":{"data":{}}}', "strings only"),
        (b'{"__metadata__":[]}', "strings only"),
        (b'{"__metadata__":{"value":"\\ud800"}}', "valid Unicode"),
        (b'{"x":{"dtype":"F16","shape":[true],"data_offsets":[0,2]}}', "shape"),
        (b'{"x":{"dtype":"F16","shape":[-1],"data_offsets":[0,2]}}', "shape"),
        (b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[false,4]}}', "offsets"),
        (b'{"x":{"dtype":"F8_E4M3","shape":[2],"data_offsets":[0,2]}}', "storage type"),
        (b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[0,4],"code":"x"}}', "fields"),
        (b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[0,2]}}', "extent"),
        (b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[1,5]}}', "holes"),
        (b'{"x":{"dtype":"F16","shape":[8],"data_offsets":[0,16]}}', "extent"),
        (b'{"x":{"dtype":"F16","shape":[2],"data_offsets":[0,4]}}', "unindexed"),
        (b'{"x":{', "Expecting"),
        (b" [1]", "Invalid SafeTensors header"),
        (b'{"x":"pickle payload"}', "descriptor"),
    ],
)
def test_malformed_or_ambiguous_headers_fail_without_model_loading(tmp_path, raw, reason):
    with pytest.raises(ValueError, match=reason):
        inspect(tmp_path, checkpoint(raw))


def test_overlapping_storage_and_truncation_are_rejected(tmp_path):
    header = {
        "a": {"dtype": "F16", "shape": [4], "data_offsets": [0, 8]},
        "b": {"dtype": "F16", "shape": [2], "data_offsets": [4, 8]},
    }
    with pytest.raises(ValueError, match="overlapping"):
        inspect(tmp_path, checkpoint(header))
    for data in (b"GGUF", struct.pack("<Q", headers.HEADER_BUDGET + 1), checkpoint()[:-1]):
        with pytest.raises(ValueError):
            inspect(tmp_path, data)


def test_scalar_and_empty_tensors_are_parsed_as_format_data_not_executed(tmp_path):
    report = inspect(
        tmp_path,
        checkpoint(
            {
                "scalar": {"dtype": "F32", "shape": [], "data_offsets": [0, 4]},
                "empty": {"dtype": "F16", "shape": [0, 2], "data_offsets": [4, 4]},
            },
            payload=bytes(4),
        ),
    )
    assert report["tensor_storage_bytes"] == 4 and report["tensor_count"] == 2


def test_changed_shape_name_count_or_unqualified_dtype_cannot_select_video_slot(tmp_path, synthetic):
    for header in (
        {"other": {"dtype": "F16", "shape": [6], "data_offsets": [0, 12]}},
        {
            "layer.weight": {"dtype": "F16", "shape": [4], "data_offsets": [0, 8]},
            "layer.bias": {"dtype": "F16", "shape": [2], "data_offsets": [8, 12]},
        },
        {
            "layer.weight": {"dtype": "BF16", "shape": [2, 2], "data_offsets": [0, 8]},
            "layer.bias": {"dtype": "BF16", "shape": [2], "data_offsets": [8, 12]},
        },
    ):
        path = tmp_path / "new-model.safetensors"
        path.write_bytes(checkpoint(header))
        with pytest.raises(ValueError, match="count|dimensions|storage type"):
            slots.inspect_checkpoint(path, path.stat().st_size, path.stat().st_mtime, slots.PROFILE)


def test_owned_inspection_has_no_llm_or_execution_authority(tmp_path, monkeypatch, synthetic):
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    content = checkpoint()
    sha = hashlib.sha256(content).hexdigest()
    path = tmp_path / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    path.chmod(0o400)
    body = VerifyModel(
        run_id=uuid4(),
        host_path="models/store/" + sha,
        app_owned=True,
        model_sha256=sha,
        size_bytes=len(content),
        mtime=path.stat().st_mtime,
        checkpoint_profile=slots.PROFILE,
        permissions=["filesystem_read", "manage_models"],
    )
    try:
        with pytest.raises(HTTPException):
            owned_model(body.host_path, sha)  # Existing LLM boundary stays GGUF-only.
        result = verify_model(body)
        assert (
            result["host_path"] is None
            and result["checkpoint_profile"]["source"] == "safetensors_descriptors"
        )
        assert result["image"] is None and not result["checkpoint_profile"]["runtime_qualified"]
        with TestClient(app) as api:
            payload = body.model_dump(mode="json")
            assert api.post("/v1/models/verify", json={**payload, "permissions": []}).status_code == 403
            for change in (
                {"check_context": True},
                {"check_image": True},
                {"app_owned": False},
                {"checkpoint_profile": "other"},
                {"host_path": "/etc/passwd"},
                {"command": "anything"},
                {"expected_schema": "b" * 64},
            ):
                assert api.post("/v1/models/verify", json={**payload, **change}).status_code == 422
        path.chmod(0o600)
        with pytest.raises(HTTPException):
            verify_model(body)
    finally:
        clear_settings_cache()


def test_missing_symlink_nonregular_and_changed_observations_are_rejected(tmp_path):
    path = tmp_path / "model.safetensors"
    path.write_bytes(checkpoint())
    alias = tmp_path / "alias.safetensors"
    alias.symlink_to(path)
    with pytest.raises(OSError):
        headers.inspect_header(alias, path.stat().st_size, path.stat().st_mtime)
    for candidate, size in ((path, 1), (tmp_path, tmp_path.stat().st_size)):
        with pytest.raises((ValueError, OSError)):
            headers.inspect_header(candidate, size, candidate.stat().st_mtime)


def test_video_slot_is_bound_to_the_exact_prepared_runtime_and_reference(monkeypatch):
    from pathlib import Path

    expected = slots.recipe(slots.PROFILE)
    assert expected["tensor_count"] == 825 and expected["role"] == "wan_model"
    with pytest.raises(ValueError, match="supported video runtime slot"):
        slots.recipe("../../other")
    original = Path.read_text

    def changed(path, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        if path.name == slots.PROFILE + ".json":
            value = json.loads(raw)
            value["runtime_source_sha256"] = "a" * 64
            return json.dumps(value)
        return raw

    monkeypatch.setattr(Path, "read_text", changed)
    with pytest.raises(ValueError, match="requires review"):
        slots.recipe(slots.PROFILE)
