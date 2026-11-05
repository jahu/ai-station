"""Structural T3 admission for a fixed Chatterbox graph, not speech inference."""

import hashlib
import json
from pathlib import Path

from ai_station_runner.safetensors_headers import inspect_header

PROFILE = "chatterbox-v3-t3-v1"
RUNTIME = "chatterbox-v3-linux-x86-64-python312-v1"
FILENAME = "t3_mtl23ls_v3.safetensors"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recipe(profile):
    if profile != PROFILE:
        raise ValueError("This checkpoint needs a supported speech runtime slot")
    folder = Path(__file__).with_name("recipes")
    expected = json.loads((folder / (PROFILE + ".json")).read_text())
    runtime = json.loads((folder / (RUNTIME + ".json")).read_text())
    primary = next(v for v in runtime["inputs"] if v["filename"] == FILENAME)
    if (
        expected["profile"] != PROFILE
        or expected["runtime_profile"] != runtime["profile"]
        or runtime["profile"] != RUNTIME
        or expected["role"] != "chatterbox_t3"
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
        raise ValueError("The speech checkpoint slot requires review for this runtime and companion recipe")
    return expected


def inspect_checkpoint(path, size_bytes, mtime, profile):
    expected = recipe(profile)
    report = inspect_header(path, size_bytes, mtime)
    if report["tensor_count"] != expected["tensor_count"]:
        raise ValueError("Checkpoint tensor count differs from the supported speech graph")
    schema = fingerprint({v["name"]: v["shape"] for v in report["tensors"]})
    if schema != expected["schema_sha256"]:
        raise ValueError("Checkpoint tensor names or dimensions differ from the supported speech graph")
    dtypes = sorted({v["dtype"] for v in report["tensors"]})
    if any(v not in expected["allowed_dtypes"] for v in dtypes):
        raise ValueError("Checkpoint uses an unsupported speech storage type")
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


def selected_environment(root, source, runtime, *, verify_weights=False):
    from ai_station_runner.owned_model_files import verify_owned_model
    from ai_station_runner.speech_runtime import resolve_public

    root = Path(root).resolve(strict=True)
    selected = resolve_public(root, runtime)
    expected = recipe(source.profile)
    if selected["observation"]["manifest_sha256"] != expected["runtime_manifest_sha256"]:
        raise ValueError("This speech checkpoint needs its reviewed engine and fixed companions")
    path = verify_owned_model(root, source.relative_path, source.sha256, checkpoint_format="safetensors")
    proof = inspect_checkpoint(path, source.size_bytes, source.mtime, source.profile)
    if proof["schema_sha256"] != source.schema_sha256:
        raise ValueError("The selected speech checkpoint graph changed")
    if verify_weights:
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != source.sha256:
                raise ValueError("The selected speech checkpoint content changed")
    return {**selected, "checkpoint_path": path}
