"""Finite Sonic adapted-UNet admission; metadata never executes model code."""

import hashlib
import json
from pathlib import Path

from ai_station_runner.torch_state_zip import inspect_archive

PROFILE = "sonic-whole-unet-v1"
RUNTIME = "sonic-whole-linux-x86-64-python310-v1"
FILENAME = "Sonic/unet.pth"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recipe(profile):
    if profile != PROFILE:
        raise ValueError("This checkpoint needs a supported avatar runtime slot")
    folder = Path(__file__).with_name("recipes")
    expected = json.loads((folder / (PROFILE + ".json")).read_text())
    runtime = json.loads((folder / (RUNTIME + ".json")).read_text())
    primary = next(v for v in runtime["inputs"] if v["filename"] == FILENAME)
    if (
        expected["profile"] != PROFILE
        or expected["runtime_profile"] != runtime["profile"]
        or runtime["profile"] != RUNTIME
        or expected["role"] != "sonic_adapted_unet"
        or expected["filename"] != FILENAME
        or expected["format"] != "pytorch_zip_tensor_data"
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
        raise ValueError("The avatar checkpoint slot requires review for this runtime and companion recipe")
    return expected


def inspect_checkpoint(path, size_bytes, mtime, profile):
    expected = recipe(profile)
    report = inspect_archive(path, size_bytes, mtime)
    if (
        report["tensor_count"] != expected["tensor_count"]
        or report["schema_sha256"] != expected["schema_sha256"]
        or report["module_metadata_sha256"] != expected["module_metadata_sha256"]
        or report["dtypes"] != expected["allowed_dtypes"]
        or not report["storage_layout_verified"]
    ):
        raise ValueError(
            "Checkpoint graph, precision or module-version data differs from the supported avatar"
        )
    return {
        **report,
        "profile": profile,
        "runtime_profile": expected["runtime_profile"],
        "role": expected["role"],
        "notice": expected["notice"],
    }
