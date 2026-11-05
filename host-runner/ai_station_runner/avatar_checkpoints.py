"""Finite Sonic adapted-UNet admission; metadata never executes model code."""

import hashlib
import json
import math
import re
from pathlib import Path

from ai_station_runner.torch_state_zip import inspect_archive

PROFILE = "sonic-whole-unet-v1"
RUNTIME = "sonic-whole-linux-x86-64-python310-v1"
FILENAME = "Sonic/unet.pth"
# Qualified on Linux through the complete source/install/ordinary-Run route.
# Keep withdrawals separate from publisher metadata and the fixed graph slot.
INFERENCE_QUALIFIED = True


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


def checked_source(value):
    fields = {
        "profile",
        "relative_path",
        "sha256",
        "size_bytes",
        "mtime",
        "schema_sha256",
        "module_metadata_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Choose the exact frozen avatar checkpoint observation")
    expected = recipe(value["profile"])
    if (
        any(
            type(value[k]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[k])
            for k in ("sha256", "schema_sha256", "module_metadata_sha256")
        )
        or value["relative_path"] != "models/store/" + value["sha256"]
        or type(value["size_bytes"]) is not int
        or not 128 <= value["size_bytes"] <= 32 * 1024**3
        or type(value["mtime"]) not in {int, float}
        or not math.isfinite(value["mtime"])
        or value["mtime"] < 0
        or value["schema_sha256"] != expected["schema_sha256"]
        or value["module_metadata_sha256"] != expected["module_metadata_sha256"]
    ):
        raise ValueError("Avatar weights require the fixed graph and immutable owned-file identity")
    return dict(value)


def source_path(root, value):
    from ai_station_runner.owned_model_files import verify_owned_model

    source = checked_source(value)
    return verify_owned_model(
        root, source["relative_path"], source["sha256"], checkpoint_format="pytorch_zip_tensor_data"
    )


def selected_environment(root, source, identity):
    from ai_station_runner.avatar_environment import resolve_id

    source = checked_source(source)
    expected = recipe(source["profile"])
    selected = resolve_id(root, identity)
    observed = selected["observation"]
    if (
        observed["profile"] != expected["runtime_profile"]
        or observed["manifest_sha256"] != expected["runtime_manifest_sha256"]
    ):
        raise ValueError("The selected avatar checkpoint needs its exact prepared engine and companions")
    path = source_path(root, source)
    inspect_checkpoint(path, source["size_bytes"], source["mtime"], source["profile"])
    return {**selected, "checkpoint_path": path}


def load_selected(root, value):
    from ai_station_runner.torch_state_loader import load_weights

    source = checked_source(value)
    return load_weights(
        source_path(root, source),
        **{
            k: source[k] for k in ("sha256", "size_bytes", "mtime", "schema_sha256", "module_metadata_sha256")
        },
    )
