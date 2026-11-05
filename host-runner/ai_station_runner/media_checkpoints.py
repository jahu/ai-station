"""Verify checkpoint graph/layout for a fixed runtime slot, without loading it."""

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.gguf_headers import inspect_header

# GGML storage layouts used by the fixed stable-diffusion.cpp recipe. Unsupported
# IQ/custom packed types need their own reviewed layout before slot admission.
# Block lengths/sizes follow ggml-common.h, not estimates from a filename.
STORAGE = {
    0: (1, 4),
    1: (1, 2),
    2: (32, 18),
    3: (32, 20),
    6: (32, 22),
    7: (32, 24),
    8: (32, 34),
    10: (256, 84),
    11: (256, 110),
    12: (256, 144),
    13: (256, 176),
    14: (256, 210),
    30: (1, 2),
}
PROFILE = "qwen-image21-diffusion-v1"


def recipe(profile):
    if profile != PROFILE:
        raise ValueError("This checkpoint needs a supported runtime slot")
    root = Path(__file__).with_name("recipes")
    expected = json.loads((root / (PROFILE + ".json")).read_text())
    runtime = json.loads((root / "qwen-image21-cuda-linux-amd64-v1.json").read_text())
    primary = next(v for v in runtime["files"] if v["role"] == "diffusion")
    if (
        expected["profile"] != profile
        or expected["runtime_profile"] != runtime["profile"]
        or expected["runtime_image_reference"] != runtime["runtime"]["image_reference"]
        or expected["reference"] != {"sha256": primary["sha256"], "size_bytes": primary["size_bytes"]}
    ):
        raise ValueError("The checkpoint slot requires review for this runtime recipe")
    return expected


def inspect_checkpoint(path, size_bytes, mtime, profile):
    expected = recipe(profile)
    report = inspect_header(
        path,
        size_bytes,
        mtime,
        keep_field=lambda k: k in {"general.architecture", "general.alignment"},
        tensors=True,
    )
    if report["tensor_count"] != expected["tensor_count"]:
        raise ValueError("Checkpoint tensor count differs from the supported image graph")
    shapes = {v["name"]: v["shape"] for v in report["tensors"]}
    schema = hashlib.sha256(json.dumps(shapes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if schema != expected["schema_sha256"]:
        raise ValueError("Checkpoint tensor names or dimensions differ from the supported image graph")
    alignment = report["fields"].get("general.alignment", 32)
    if type(alignment) is not int or not 1 <= alignment <= 4096 or alignment & (alignment - 1):
        raise ValueError("Invalid GGUF data alignment")
    start = (report["header_bytes"] + alignment - 1) // alignment * alignment
    if start > size_bytes:
        raise ValueError("GGUF tensor data is truncated")
    spans = []
    types = set()
    for tensor in report["tensors"]:
        kind, offset = tensor["type"], tensor["offset"]
        if kind not in expected["allowed_ggml_types"] or kind not in STORAGE:
            raise ValueError("Checkpoint uses an unsupported GGML storage type")
        block, storage = STORAGE[kind]
        if tensor["shape"][0] % block:
            raise ValueError("Quantized tensor rows do not match their GGML block size")
        length = math.prod(tensor["shape"]) // block * storage
        if offset % alignment or offset + length > size_bytes - start:
            raise ValueError("Checkpoint tensor offset or extent is invalid")
        spans.append((offset, offset + length))
        types.add(kind)
    spans.sort()
    if any(first[1] > second[0] for first, second in zip(spans, spans[1:])):
        raise ValueError("Checkpoint tensor payloads overlap")
    return {
        "profile": profile,
        "runtime_profile": expected["runtime_profile"],
        "role": expected["role"],
        "source": "gguf_tensor_descriptors",
        "schema_sha256": schema,
        "tensor_count": report["tensor_count"],
        "ggml_types": sorted(types),
        "tensor_storage_bytes": sum(end - begin for begin, end in spans),
        "header_bytes": report["header_bytes"],
        "runtime_qualified": False,
        "notice": "Graph/layout compatibility only; companion readiness, resource admission and first-result qualification remain separate.",
    }


# Typed selection of an already downloaded object; it cannot select a host path,
# companion, image or command. Generation retains its ordinary workspace rights.
class CheckpointSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["qwen-image21-diffusion-v1"]
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=64 * 1024**3)
    mtime: float = Field(ge=0, allow_inf_nan=False)
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def namespace(self):
        if self.relative_path != "models/store/" + self.sha256:
            raise ValueError("Select a verified image checkpoint from application storage")
        return self


def resolve_source(source):
    from ai_station_runner.owned_models import owned_model

    path = owned_model(source.relative_path, source.sha256)
    proof = inspect_checkpoint(path, source.size_bytes, source.mtime, source.profile)
    if proof["schema_sha256"] != source.schema_sha256:
        raise ValueError("The selected image checkpoint graph changed")
    return path


def device_budget(source):
    expected = recipe(source.profile)
    baseline = expected.get(
        "workload", {"primary_vram_mib": 12288, "companion_vram_mib": 12288, "maximum_side": 1024}
    )
    delta = (source.size_bytes - expected["reference"]["size_bytes"]) / 1024**2
    return {
        "primary_vram_mib": max(
            baseline["primary_vram_mib"], math.ceil(baseline["primary_vram_mib"] + delta)
        ),
        "companion_vram_mib": baseline["companion_vram_mib"],
        "ram_mib": max(12288, math.ceil(source.size_bytes / 1024**2 + 2048)),
        "maximum_side": baseline["maximum_side"],
    }
