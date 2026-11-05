"""Closed owned split-GGUF coordinate and bounded native structural inspection.

Publisher filenames never become host paths or container arguments. Downloaded
objects already have verified SHA identities; this operation reads headers only.
Structural agreement is not a promise of llama.cpp inference compatibility.
"""

import hashlib
import json
import math

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.gguf_context import _FIELDS, context_profile
from ai_station_runner.gguf_headers import HEADER_BUDGET, inspect_header
from ai_station_runner.media_checkpoints import STORAGE
from ai_station_runner.owned_model_files import verify_owned_model

MAX_PARTS = 64
MAX_TENSORS = 100000
TOTAL_HEADER_BUDGET = 64 * 1024**2
SPLIT_KINDS = {"split.no": 2, "split.count": 2, "split.tensors.count": 5}


class ModelPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: StrictInt = Field(gt=0, le=256 * 1024**3)
    mtime: float = Field(gt=0, allow_inf_nan=False)

    @property
    def relative_path(self):
        return "models/store/" + self.sha256


class ModelBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parts: tuple[ModelPart, ...] = Field(min_length=2, max_length=MAX_PARTS)

    @model_validator(mode="after")
    def coordinate(self):
        if len({part.sha256 for part in self.parts}) != len(self.parts):
            raise ValueError("Each GGUF part must have a distinct owned identity")
        if self.size_bytes > 2 * 1024**4:
            raise ValueError("The complete GGUF exceeds the native bundle size limit")
        return self

    @property
    def size_bytes(self):
        return sum(part.size_bytes for part in self.parts)

    def check_primary(self, path, digest, size, mtime):
        first = self.parts[0]
        if (path, digest, size, mtime) != (first.relative_path, first.sha256, first.size_bytes, first.mtime):
            raise ValueError("The primary model must be the first frozen GGUF part")


def destinations(count):
    return [f"/models/model-{index:05d}-of-{count:05d}.gguf" for index in range(1, count + 1)]


def _keep(key):
    return (
        key in {*SPLIT_KINDS, "general.architecture", "general.alignment"} or key.partition(".")[2] in _FIELDS
    )


def _signature(path):
    info = path.stat(follow_symlinks=False)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inspect_single(path, size_bytes, mtime):
    """A renamed part cannot bypass the complete-bundle coordinate."""
    report = inspect_header(
        path, size_bytes, mtime, keep_field=lambda key: key in SPLIT_KINDS, field_kinds=True
    )
    fields = report["fields"]
    if fields.get("split.count", 1) != 1 or fields.get("split.no", 0) != 0:
        raise ValueError("A split GGUF requires its verified complete bundle")
    if any(report["field_kinds"][key] != SPLIT_KINDS[key] for key in fields):
        raise ValueError("Invalid GGUF split metadata types")


def _layout(report, size_bytes):
    fields, kinds = report["fields"], report["field_kinds"]
    alignment = fields.get("general.alignment", 32)
    if (
        type(alignment) is not int
        or not 1 <= alignment <= 4096
        or alignment & (alignment - 1)
        or ("general.alignment" in fields and kinds["general.alignment"] != 4)
    ):
        raise ValueError("Invalid GGUF data alignment")
    start = (report["header_bytes"] + alignment - 1) // alignment * alignment
    # A zero-tensor metadata part need not carry an aligned data section.
    if report["tensor_count"] and start > size_bytes:
        raise ValueError("GGUF tensor data is truncated")
    spans = []
    for tensor in report["tensors"]:
        kind, shape, offset = tensor["type"], tensor["shape"], tensor["offset"]
        if kind not in STORAGE:
            raise ValueError("GGUF part uses an unsupported GGML storage type")
        block, storage = STORAGE[kind]
        if shape[0] % block:
            raise ValueError("GGUF tensor rows do not match their storage block size")
        length = math.prod(shape) // block * storage
        if offset % alignment or offset + length > size_bytes - start:
            raise ValueError("Invalid GGUF tensor offset or extent")
        spans.append((offset, offset + length))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("GGUF tensor storage overlaps")


def inspect_bundle(root, bundle: ModelBundle):
    paths = [verify_owned_model(root, p.relative_path, p.sha256) for p in bundle.parts]
    before = [_signature(path) for path in paths]
    first_fields = None
    first_kinds = None
    context = None
    inventory = {}
    layer_bytes = {}
    shared_bytes = 0
    budget = TOTAL_HEADER_BUDGET
    total = None
    for index, (part, path) in enumerate(zip(bundle.parts, paths)):
        report = inspect_header(
            path,
            part.size_bytes,
            part.mtime,
            keep_field=_keep,
            tensors=True,
            allow_empty=index == 0,
            field_kinds=True,
            tensor_limit=MAX_TENSORS - len(inventory),
            header_limit=min(HEADER_BUDGET, budget),
        )
        budget -= report["header_bytes"]
        fields, kinds = report["fields"], report["field_kinds"]
        if any(kinds.get(key) != kind for key, kind in SPLIT_KINDS.items()):
            raise ValueError("GGUF split metadata has missing or incorrect field types")
        if fields["split.no"] != index or fields["split.count"] != len(bundle.parts):
            raise ValueError("GGUF part order or complete part count does not match")
        declared = fields["split.tensors.count"]
        if not 1 <= declared <= MAX_TENSORS or (total is not None and declared != total):
            raise ValueError("GGUF global tensor count is inconsistent or exceeds its bound")
        total = declared
        geometry = {k: v for k, v in fields.items() if k not in {*SPLIT_KINDS, "general.alignment"}}
        if index == 0:
            context = context_profile(geometry)
            first_fields = geometry
            first_kinds = kinds
        elif any(
            first_fields.get(key) != value or first_kinds.get(key) != kinds[key]
            for key, value in geometry.items()
        ):
            raise ValueError("GGUF parts disagree on architecture or context geometry")
        _layout(report, part.size_bytes)
        for tensor in report["tensors"]:
            if tensor["name"] in inventory:
                raise ValueError("GGUF tensor names repeat across parts")
            inventory[tensor["name"]] = {"shape": tensor["shape"], "type": tensor["type"]}
            block, storage = STORAGE[tensor["type"]]
            length = math.prod(tensor["shape"]) // block * storage
            segments = tensor["name"].split(".", 2)
            if len(segments) == 3 and segments[0] == "blk" and segments[1].isdigit():
                layer_bytes[segments[1]] = layer_bytes.get(segments[1], 0) + length
            else:
                shared_bytes += length
    if len(inventory) != total:
        raise ValueError("The GGUF bundle does not contain its declared complete tensor inventory")
    for part, path, observed in zip(bundle.parts, paths, before):
        if verify_owned_model(root, part.relative_path, part.sha256) != path or _signature(path) != observed:
            raise ValueError("GGUF part changed during complete bundle inspection")
    identity = hashlib.sha256(
        json.dumps(bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    schema = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "kind": "gguf_split",
        "bundle_id": identity,
        "part_count": len(paths),
        "size_bytes": bundle.size_bytes,
        "tensor_count": total,
        "schema_sha256": schema,
        "context_profile": context,
        "structurally_verified": True,
        "inference_qualified": False,
        "largest_layer_bytes": max(layer_bytes.values(), default=0),
        "shared_tensor_bytes": shared_bytes,
    }


def hardware_budget(proof, context_size, gpu_count):
    """Conservative equal-layer split: layer rounding/shared weights/KV margins.

    Every GPU must independently have room. KV is conservatively budgeted in
    full on each device; this is admission advice, not measured peak allocation.
    """
    context = proof["context_profile"]
    if (
        type(gpu_count) is not int
        or not 1 <= gpu_count <= 16
        or type(context_size) is not int
        or not 512 <= context_size <= context["trained_context"]
        or context_size % 256
    ):
        raise ValueError("Choose available CUDA devices and a supported trained context")
    mib = 1024**2
    weights = (proof["size_bytes"] + gpu_count - 1) // gpu_count
    # One whole layer covers equal-layer rounding; shared embeddings/output are
    # charged to each GPU rather than assuming their placement or tied weights.
    per_gpu = (
        weights
        + proof["largest_layer_bytes"]
        + proof["shared_tensor_bytes"]
        + context_size * context["q8_kv_bytes_per_token"]
        + (context["state_reserve_mib"] + 1024) * mib
    )
    return {
        "per_gpu_mib": (per_gpu + mib - 1) // mib,
        "ram_mib": (proof["size_bytes"] * 115 + 100 * mib - 1) // (100 * mib) + 1024,
        "context_size": context_size,
        "gpu_count": gpu_count,
        "automatic_ram_offload": False,
    }


def admit_hardware(proof, context_size, selected, hardware):
    budget = hardware_budget(proof, context_size, len(selected))
    memory = (hardware.get("memory") or {}).get("available_mib")
    if type(memory) not in {int, float} or not math.isfinite(memory) or memory < budget["ram_mib"]:
        raise ValueError("The complete GGUF bundle needs more available host RAM")
    devices = {device.get("index"): device for device in hardware.get("gpus", [])}
    for index in selected:
        device = devices.get(index, {})
        total, used = device.get("memory_total_mib"), device.get("memory_used_mib")
        if (
            type(total) not in {int, float}
            or type(used) not in {int, float}
            or not math.isfinite(total)
            or not math.isfinite(used)
            or not 0 <= used <= total
            or total - used < budget["per_gpu_mib"]
        ):
            raise ValueError("Each selected GPU must fit the complete bundle share and context")
    return budget
