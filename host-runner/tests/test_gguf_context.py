import struct
from uuid import uuid4

import pytest
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.gguf_context import HEADER_BUDGET, context_profile, inspect_context
from ai_station_runner.model_verify import VerifyModel, verify_model
from fastapi import HTTPException


def fields():
    return {
        "general.architecture": "qwen35",
        "qwen35.block_count": 64,
        "qwen35.context_length": 262144,
        "qwen35.embedding_length": 5120,
        "qwen35.attention.head_count": 24,
        "qwen35.attention.head_count_kv": 4,
        "qwen35.attention.key_length": 256,
        "qwen35.attention.value_length": 256,
        "qwen35.full_attention_interval": 4,
    }


def header(values):
    output = bytearray(b"GGUF" + struct.pack("<IQQ", 3, 0, len(values)))
    for key, val in values.items():
        encoded = key.encode()
        output += struct.pack("<Q", len(encoded)) + encoded
        if isinstance(val, str):
            encoded = val.encode()
            output += struct.pack("<IQ", 8, len(encoded)) + encoded
        else:
            output += struct.pack("<II", 4, val)
    return output


def test_header_profile_skips_tokenizer_and_tensors_and_preserves_file(tmp_path):
    data = header(fields())
    # Append tokenizer strings after architecture fields, before untouched tensor bytes.
    struct.pack_into("<Q", data, 16, len(fields()) + 1)
    key = b"tokenizer.ggml.tokens"
    data += struct.pack("<Q", len(key)) + key + struct.pack("<IIQ", 9, 8, 2)
    data += struct.pack("<Q", 3) + b"foo" + struct.pack("<Q", 3) + b"bar"
    model = tmp_path / "model.gguf"
    model.write_bytes(data + b"UNREAD TENSOR DATA")
    before = model.stat()
    profile = inspect_context(model, before.st_size, before.st_mtime)
    assert profile["attention_layers"] == 16
    assert profile["q8_kv_bytes_per_token"] == 34816
    assert profile["state_reserve_mib"] == 512
    assert model.read_bytes() == data + b"UNREAD TENSOR DATA"
    assert model.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize(
    "changes",
    [
        {"general.architecture": "unknown"},
        {"qwen35.block_count": 0},
        {"qwen35.attention.head_count_kv": 900},
        {"qwen35.full_attention_interval": 0},
        {"qwen35.attention.recurrent_layers": None},
        {"qwen35.attention.key_length": True},
    ],
)
def test_unsupported_or_invalid_profiles_are_rejected(changes):
    with pytest.raises(ValueError):
        context_profile({**fields(), **changes})


@pytest.mark.parametrize(
    "data",
    [
        b"GGUF",
        b"NOPE" + bytes(100),
        b"GGUF" + struct.pack("<IQQ", 3, 0, 4097),
        b"GGUF" + struct.pack("<IQQQ", 3, 0, 1, HEADER_BUDGET + 1),
        b"GGUF" + struct.pack("<IQQQ", 3, 0, 1, 1) + b"x" + struct.pack("<IIQ", 9, 9, 1),
    ],
)
def test_malformed_headers_are_bounded(tmp_path, data):
    model = tmp_path / "bad.gguf"
    model.write_bytes(data)
    with pytest.raises(ValueError):
        inspect_context(model, model.stat().st_size, model.stat().st_mtime)


def test_symlink_and_changed_observation_cannot_be_inspected(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(header(fields()))
    alias = tmp_path / "alias.gguf"
    alias.symlink_to(model)
    with pytest.raises(OSError):
        inspect_context(alias, model.stat().st_size, model.stat().st_mtime)
    with pytest.raises(ValueError):
        inspect_context(model, 1, model.stat().st_mtime)


def test_dense_attention_uses_all_layers():
    profile = context_profile(
        {
            key.replace("qwen35", "llama"): val if key != "general.architecture" else "llama"
            for key, val in fields().items()
        }
    )
    assert profile["attention_layers"] == 64
    assert profile["q8_kv_bytes_per_token"] == 139264
    assert profile["state_reserve_mib"] == 0


def test_context_verification_enforces_permission_and_boundary(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    model = root / "model.gguf"
    model.write_bytes(header(fields()))
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    clear_settings_cache()
    body = VerifyModel(
        run_id=uuid4(),
        host_path=str(model),
        size_bytes=model.stat().st_size,
        mtime=model.stat().st_mtime,
        check_context=True,
        permissions=["filesystem_read", "manage_models"],
    )
    try:
        report = verify_model(body)
        assert report["context_profile"]["q8_kv_bytes_per_token"] == 34816
        with pytest.raises(HTTPException) as denied:
            verify_model(body.model_copy(update={"permissions": []}))
        assert denied.value.status_code == 403
        outside = tmp_path / "outside.gguf"
        outside.write_bytes(header(fields()))
        with pytest.raises(HTTPException) as escaped:
            verify_model(body.model_copy(update={"host_path": str(outside)}))
        assert escaped.value.status_code == 422
    finally:
        clear_settings_cache()
