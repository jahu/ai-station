"""Structural admission for the fixed Wan 2.2 5B diffusion slot, not inference."""

import hashlib
import json
from pathlib import Path

from ai_station_runner.safetensors_headers import inspect_header

PROFILE = "wan22-5b-diffusion-v1"


def recipe(profile):
    if profile != PROFILE:
        raise ValueError("This checkpoint needs a supported video runtime slot")
    root = Path(__file__).with_name("recipes")
    expected = json.loads((root / (PROFILE + ".json")).read_text())
    runtime = json.loads((root / "wan22-5b-linux-x86-64-python312-v1.json").read_text())
    primary = next(v for v in runtime["inputs"] if v.get("role") == "wan_model")
    if (
        expected["profile"] != profile
        or expected["runtime_profile"] != runtime["profile"]
        or expected["runtime_source_sha256"] != runtime["source_sha256"]
        or expected["runtime_manifest_sha256"] != fingerprint(runtime)
        or expected["reference"] != {"sha256": primary["sha256"], "size_bytes": primary["size_bytes"]}
    ):
        raise ValueError("The video checkpoint slot requires review for this runtime recipe")
    return expected


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect_checkpoint(path, size_bytes, mtime, profile):
    expected = recipe(profile)
    report = inspect_header(path, size_bytes, mtime)
    if report["tensor_count"] != expected["tensor_count"]:
        raise ValueError("Checkpoint tensor count differs from the supported video graph")
    schema = fingerprint({v["name"]: v["shape"] for v in report["tensors"]})
    if schema != expected["schema_sha256"]:
        raise ValueError("Checkpoint tensor names or dimensions differ from the supported video graph")
    dtypes = sorted({v["dtype"] for v in report["tensors"]})
    if any(v not in expected["allowed_dtypes"] for v in dtypes):
        raise ValueError("Checkpoint uses an unsupported video storage type")
    return {
        "profile": profile,
        "runtime_profile": expected["runtime_profile"],
        "role": expected["role"],
        "source": "safetensors_descriptors",
        "schema_sha256": schema,
        "tensor_count": report["tensor_count"],
        "dtypes": dtypes,
        "tensor_storage_bytes": report["tensor_storage_bytes"],
        "header_bytes": report["header_bytes"],
        "runtime_qualified": False,
        "notice": "Graph/layout compatibility only; complete engine, companion, hardware and first-result qualification remain separate.",
    }
