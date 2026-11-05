"""Structural diffusion admission for the fixed ACE-Step graph, not music inference."""

import hashlib
import json
from pathlib import Path

from ai_station_runner.safetensors_headers import inspect_header

PROFILE = "ace-step15-turbo-diffusion-v1"
RUNTIME = "ace-step15-turbo-linux-x86-64-python312-v1"
FILENAME = "acestep-v15-turbo/model.safetensors"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recipe(profile):
    if profile != PROFILE:
        raise ValueError("This checkpoint needs a supported music runtime slot")
    folder = Path(__file__).with_name("recipes")
    expected = json.loads((folder / (PROFILE + ".json")).read_text())
    runtime = json.loads((folder / (RUNTIME + ".json")).read_text())
    primary = next(v for v in runtime["inputs"] if v["filename"] == FILENAME)
    if (
        expected["profile"] != PROFILE
        or expected["runtime_profile"] != runtime["profile"]
        or runtime["profile"] != RUNTIME
        or expected["role"] != "ace_step15_turbo_diffusion"
        or expected["filename"] != FILENAME
        or expected["format"] != "safetensors"
        or expected["runtime_manifest_sha256"] != fingerprint(runtime)
        or expected["runtime_sdk_sha256"]
        != {v["name"]: v["sha256"] for v in runtime["inputs"] if v["kind"] == "sdk"}
        or expected["reference"] != {k: primary[k] for k in ("sha256", "size_bytes")}
        or expected["fixed_companions"]
        != [
            {k: v[k] for k in ("filename", "sha256", "size_bytes")}
            for v in runtime["inputs"]
            if v["kind"] == "model" and v != primary
        ]
    ):
        raise ValueError("The music checkpoint slot requires review for this runtime and companion recipe")
    return expected


def inspect_checkpoint(path, size_bytes, mtime, profile):
    expected = recipe(profile)
    report = inspect_header(path, size_bytes, mtime)
    if report["tensor_count"] != expected["tensor_count"]:
        raise ValueError("Checkpoint tensor count differs from the supported music graph")
    schema = fingerprint({v["name"]: v["shape"] for v in report["tensors"]})
    if schema != expected["schema_sha256"]:
        raise ValueError("Checkpoint tensor names or dimensions differ from the supported music graph")
    dtypes = sorted({v["dtype"] for v in report["tensors"]})
    if any(v not in expected["allowed_dtypes"] for v in dtypes):
        raise ValueError("Checkpoint uses an unsupported music storage type")
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
        "header_sha256": report["header_sha256"],
        "runtime_qualified": False,
        "notice": expected["notice"],
    }
