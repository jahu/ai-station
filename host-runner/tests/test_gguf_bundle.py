"""Complete tiny split fixtures; no payload/model inference or real Docker."""

import hashlib
import struct
from uuid import uuid4

import pytest
from ai_station_runner import gguf_bundle as bundle
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.model_verify import VerifyModel, verify_model
from fastapi import HTTPException
from pydantic import ValidationError


def string(value):
    data = value.encode()
    return struct.pack("<Q", len(data)) + data


def part_bytes(index, count=2, *, total=2, tensors=None, changes=None, kinds=None):
    fields = {
        "split.no": index,
        "split.count": count,
        "split.tensors.count": total,
    }
    types = dict(bundle.SPLIT_KINDS)
    if index == 0:
        fields.update(
            {
                "general.architecture": "llama",
                "llama.block_count": 1,
                "llama.context_length": 32768,
                "llama.embedding_length": 32,
                "llama.attention.head_count": 1,
                "llama.attention.head_count_kv": 1,
            }
        )
        types.update(
            {key: 8 if isinstance(value, str) else 4 for key, value in fields.items() if key not in types}
        )
    fields.update(changes or {})
    types.update(kinds or {})
    tensors = [(f"blk.{index}.weight", [32], 0, 0)] if tensors is None else tensors
    out = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(fields))
    formats = {2: "H", 4: "I", 5: "i", 7: "?"}
    for key, value in fields.items():
        kind = types.get(key, 8 if isinstance(value, str) else 4)
        out += string(key) + struct.pack("<I", kind)
        out += string(value) if kind == 8 else struct.pack("<" + formats[kind], value)
    for name, shape, kind, offset in tensors:
        out += string(name) + struct.pack("<I", len(shape)) + struct.pack("<" + "Q" * len(shape), *shape)
        out += struct.pack("<IQ", kind, offset)
    return out + bytes(-len(out) % 32) + bytes(1024)


def store(root, data):
    digest = hashlib.sha256(data).hexdigest()
    path = root / "models/store" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o444)
    return bundle.ModelPart(sha256=digest, size_bytes=len(data), mtime=path.stat().st_mtime)


def sample(root, **second):
    return bundle.ModelBundle(parts=(store(root, part_bytes(0)), store(root, part_bytes(1, **second))))


def test_complete_bundle_preserves_files_and_uses_first_context_only(tmp_path):
    coordinate = sample(tmp_path)
    before = {part.sha256: (tmp_path / part.relative_path).read_bytes() for part in coordinate.parts}
    proof = bundle.inspect_bundle(tmp_path, coordinate)
    assert proof["size_bytes"] == coordinate.size_bytes
    assert proof["tensor_count"] == 2 and proof["part_count"] == 2
    assert proof["context_profile"]["trained_context"] == 32768
    assert proof["structurally_verified"] and not proof["inference_qualified"]
    assert all(
        (tmp_path / part.relative_path).read_bytes() == before[part.sha256] for part in coordinate.parts
    )
    assert bundle.inspect_bundle(tmp_path, coordinate) == proof
    assert bundle.destinations(2) == [
        "/models/model-00001-of-00002.gguf",
        "/models/model-00002-of-00002.gguf",
    ]


def test_zero_tensor_first_part_and_global_inventory(tmp_path):
    coordinate = bundle.ModelBundle(
        parts=(
            store(tmp_path, part_bytes(0, tensors=[])),
            store(tmp_path, part_bytes(1, tensors=[("one", [32], 8, 0), ("two", [32], 1, 64)])),
        )
    )
    assert bundle.inspect_bundle(tmp_path, coordinate)["tensor_count"] == 2


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"count": 3}, "part count"),
        ({"changes": {"split.no": 0}}, "part order"),
        ({"total": 3}, "global tensor count"),
        ({"kinds": {"split.no": 4}}, "field types"),
        ({"kinds": {"split.count": 7}}, "field types"),
        ({"kinds": {"split.tensors.count": 4}}, "field types"),
        ({"changes": {"llama.block_count": 4}}, "geometry"),
        ({"changes": {"general.architecture": "qwen2"}}, "geometry"),
        ({"tensors": [("blk.0.weight", [32], 0, 0)]}, "repeat"),
        ({"tensors": [("tensor", [32], 999, 0)]}, "storage type"),
        ({"tensors": [("tensor", [33], 8, 0)]}, "block size"),
        ({"tensors": [("tensor", [32], 0, 1)]}, "offset or extent"),
        ({"tensors": [("tensor", [32], 0, 1024)]}, "offset or extent"),
        ({"tensors": [("one", [32], 0, 0), ("two", [32], 0, 32)]}, "overlaps"),
        ({"changes": {"general.alignment": 7}}, "alignment"),
    ],
)
def test_inconsistent_or_invalid_parts_refuse(tmp_path, change, reason):
    with pytest.raises(ValueError, match=reason):
        bundle.inspect_bundle(tmp_path, sample(tmp_path, **change))


def test_missing_inventory_and_wrong_primary_refuse(tmp_path):
    coordinate = bundle.ModelBundle(
        parts=tuple(store(tmp_path, part_bytes(index, total=3)) for index in range(2))
    )
    with pytest.raises(ValueError, match="complete tensor inventory"):
        bundle.inspect_bundle(tmp_path, coordinate)
    with pytest.raises(ValueError, match="first frozen"):
        coordinate.check_primary(
            coordinate.parts[1].relative_path,
            coordinate.parts[1].sha256,
            coordinate.parts[1].size_bytes,
            coordinate.parts[1].mtime,
        )


@pytest.mark.parametrize("change", ["missing", "symlink", "writable", "hardlink", "changed"])
def test_each_part_has_owned_immutable_boundary(tmp_path, change):
    coordinate = sample(tmp_path)
    path = tmp_path / coordinate.parts[1].relative_path
    if change == "missing":
        path.unlink()
    elif change == "symlink":
        target = tmp_path / "outside"
        path.rename(target)
        path.symlink_to(target)
    elif change == "writable":
        path.chmod(0o644)
    elif change == "hardlink":
        (tmp_path / "other").hardlink_to(path)
    else:
        coordinate = coordinate.model_copy(
            update={"parts": (coordinate.parts[0], coordinate.parts[1].model_copy(update={"size_bytes": 99}))}
        )
    with pytest.raises((OSError, ValueError)):
        bundle.inspect_bundle(tmp_path, coordinate)


def test_group_budgets_and_typed_closed_coordinates(tmp_path, monkeypatch):
    coordinate = sample(tmp_path)
    for parts in [coordinate.parts[:1], coordinate.parts * 33, (coordinate.parts[0],) * 2]:
        with pytest.raises(ValidationError):
            bundle.ModelBundle(parts=parts)
    with pytest.raises(ValidationError):
        bundle.ModelPart(**{**coordinate.parts[0].model_dump(), "path": "/etc/passwd"})
    monkeypatch.setattr(bundle, "TOTAL_HEADER_BUDGET", 20)
    with pytest.raises(ValueError, match="budget"):
        bundle.inspect_bundle(tmp_path, coordinate)


def test_global_descriptor_budget_applies_across_parts(tmp_path, monkeypatch):
    coordinate = sample(tmp_path)
    monkeypatch.setattr(bundle, "MAX_TENSORS", 1)
    with pytest.raises(ValueError, match="global tensor count"):
        bundle.inspect_bundle(tmp_path, coordinate)


def test_single_context_does_not_estimate_a_fragment_as_complete(tmp_path):
    from ai_station_runner.gguf_context import inspect_context

    coordinate = sample(tmp_path)
    first = coordinate.parts[0]
    with pytest.raises(ValueError, match="complete bundle"):
        inspect_context(tmp_path / first.relative_path, first.size_bytes, first.mtime)


def test_hardware_budget_uses_complete_size_trained_context_and_each_gpu(tmp_path):
    proof = bundle.inspect_bundle(tmp_path, sample(tmp_path))
    # Synthetic larger total isolates aggregate residency from first-part size.
    proof["size_bytes"] = 24 * 1024**3
    one = bundle.hardware_budget(proof, 4096, 1)
    two = bundle.hardware_budget(proof, 4096, 2)
    assert one["per_gpu_mib"] > two["per_gpu_mib"] > 12288
    assert two["ram_mib"] > 24 * 1024
    assert not two["automatic_ram_offload"]
    with pytest.raises(ValueError, match="trained context"):
        bundle.hardware_budget(proof, 33024, 2)


def test_change_during_other_part_inspection_refuses(tmp_path, monkeypatch):
    coordinate = sample(tmp_path)
    original = bundle.inspect_header

    def inspect(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.name == coordinate.parts[1].sha256:
            (tmp_path / coordinate.parts[0].relative_path).chmod(0o644)
        return result

    monkeypatch.setattr(bundle, "inspect_header", inspect)
    with pytest.raises(ValueError):
        bundle.inspect_bundle(tmp_path, coordinate)


def test_typed_model_inspection_hides_native_paths_and_rejects_fragment(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    clear_settings_cache()
    try:
        coordinate = sample(tmp_path)
        first = coordinate.parts[0]
        body = VerifyModel(
            run_id=uuid4(),
            host_path=first.relative_path,
            model_sha256=first.sha256,
            app_owned=True,
            size_bytes=first.size_bytes,
            mtime=first.mtime,
            check_context=True,
            model_bundle=coordinate,
            permissions=["filesystem_read", "manage_models"],
        )
        report = verify_model(body)
        assert report["model_bundle"]["size_bytes"] == coordinate.size_bytes
        assert report["host_path"] is None and str(tmp_path) not in str(report)
        with pytest.raises(HTTPException) as denied:
            verify_model(body.model_copy(update={"permissions": []}))
        assert denied.value.status_code == 403
        (tmp_path / coordinate.parts[1].relative_path).unlink()
        with pytest.raises(HTTPException) as missing:
            verify_model(body)
        assert missing.value.status_code == 422
    finally:
        clear_settings_cache()


def test_bundle_image_inspection_uses_fixed_runtime_without_configured_fallback(tmp_path, monkeypatch):
    from ai_station_runner import runtime_setup

    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    clear_settings_cache()
    try:
        coordinate = sample(tmp_path)
        first = coordinate.parts[0]
        profiles = []

        def inspect(selection):
            profiles.append(selection.profile)
            return {"image": {"present": True, "id": "sha256:" + "a" * 64}}

        def configured(**kwargs):
            raise AssertionError("Bundle verification must not select a configured moving image")

        monkeypatch.setattr(runtime_setup, "inspect_image", inspect)
        monkeypatch.setattr(runtime_setup, "image_observation", configured)
        body = VerifyModel(
            run_id=uuid4(),
            host_path=first.relative_path,
            model_sha256=first.sha256,
            app_owned=True,
            size_bytes=first.size_bytes,
            mtime=first.mtime,
            check_context=True,
            check_image=True,
            model_bundle=coordinate,
            permissions=["filesystem_read", "manage_models"],
        )
        report = verify_model(body)
        assert profiles == ["llamacpp-cuda-linux-amd64-v1"]
        assert report["image"]["name"] == runtime_setup.REFERENCE
        assert report["image"]["present"]
    finally:
        clear_settings_cache()
