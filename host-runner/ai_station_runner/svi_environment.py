"""Owned offline SVI Pro assembly; no operational installation/API admission yet."""

import json
import os
import platform
import re
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner import video_environment
from ai_station_runner.environment_files import command, install_python, read_json
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    unpack_python,
    unpack_tar,
    verified_object,
)

PROFILE = "wan22-svi-pro-q4-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
BASE_MANIFEST = "13014b57a58c515483d8528a1fc2cb81a39bb698e6962a8cc606081d13314386"
QUALIFIED = False
ROLES = frozenset(
    {"wan_high_noise", "wan_low_noise", "svi_high_adapter", "svi_low_adapter", "wan_text_encoder", "wan_vae"}
)


def recipe():
    value = json.loads(RECIPE.read_text())
    base = video_environment.recipe()
    items = value["inputs"]
    wheels = [row for row in items if row["kind"] == "wheel"]
    models = [row for row in items if row["kind"] == "model"]
    sdks = [row for row in items if row["kind"] == "sdk"]
    versions = {re.sub(r"[-_.]+", "-", row["name"].lower()): row["version"] for row in wheels}
    common = [row for row in base["inputs"] if row.get("role") not in {"wan_model", "wan_vae"}]
    if (
        value["profile"] != PROFILE
        or value["base_manifest_sha256"] != BASE_MANIFEST
        or fingerprint(base) != BASE_MANIFEST
        or any(row not in items for row in common)
        or value["source_sha256"] != base["source_sha256"]
        or len(items) != 107
        or len({row["sha256"] for row in items}) != len(items)
        or len({row["filename"] for row in items}) != len(items)
        or len(wheels) != 98
        or len(versions) != 98
        or versions.get("gguf") != "0.19.0"
        or len(models) != 6
        or {row["role"] for row in models} != ROLES
        or len(sdks) != 2
        or {row["name"] for row in sdks} != {"ComfyUI", "ComfyUI-GGUF"}
        or len([row for row in items if row["kind"] == "python"]) != 1
    ):
        raise ValueError("SVI Pro requires its complete coherent fixed model and engine recipe")
    return value


def model_paths(root, folder, frozen, *, verify_weights=False, check=lambda: None):
    return video_environment.model_paths(
        root,
        folder,
        frozen,
        verify_weights=verify_weights,
        check=check,
        roles=ROLES,
        suffixes=(".gguf", ".safetensors"),
    )


def verify_sources(folder, frozen):
    source = video_environment.verify_source(folder / "source", frozen)
    gguf = video_environment.verify_source(
        folder / "gguf-source", {"source_sha256": frozen["gguf_source_sha256"]}
    )
    return {"comfy_dir": source, "gguf_dir": gguf}


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("This SVI Pro profile requires Linux x86-64 and Python 3.12")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    base = directory(root, "runtime/svi-environments/" + fingerprint(frozen))
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing SVI preparation instead of overwriting it")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(
            {"phase": "verifying_inputs", "completed_files": index + 1, "file_count": len(frozen["inputs"])}
        )
    check()
    folder.mkdir(mode=0o700)
    for name in ("home", "cache", "wheels", "sources", "models"):
        directory(folder, name)
    python = install_python(
        folder, frozen, objects, check=check, progress=progress, run_command=command, unpack=unpack_python
    )
    progress({"phase": "preparing_sdk"})
    for name, destination in (("ComfyUI", "source"), ("ComfyUI-GGUF", "gguf-source")):
        sdk = next(row for row in frozen["inputs"] if row["kind"] == "sdk" and row["name"] == name)
        unpack_tar(objects[sdk["filename"]], folder / "sources", check).rename(folder / destination)
    verify_sources(folder, frozen)
    for item in (row for row in frozen["inputs"] if row["kind"] == "model"):
        (folder / "models" / item["filename"]).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "models")
        )
    model_paths(root, folder / "models", frozen)
    progress({"phase": "checking_environment"})
    command(
        [python, str(Path(__file__).with_name("svi_environment_probe.py")), str(folder), str(root)],
        folder=folder,
        check=check,
    )
    check()
    receipt = {
        "profile": PROFILE,
        "manifest_sha256": fingerprint(frozen),
        "operation_id": str(operation_id),
        "relative_path": folder.relative_to(root).as_posix(),
        "environment_prepared": True,
        "video_inference_tested": False,
    }
    path = folder / ".ready.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    check()
    os.replace(path, folder / "ready.json")
    progress({"phase": "environment_prepared", "video_inference_tested": False})
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != {"profile": PROFILE, "manifest_sha256": fingerprint(frozen), "operation_id": identity}:
        raise ValueError("The frozen SVI environment differs from the reviewed recipe")
    folder = root / "runtime/svi-environments" / fingerprint(frozen) / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(key) == value
        for key, value in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The SVI environment has not completed preparation")
    binary, python = folder / "python/bin/python3.12", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("SVI requires its own prepared Python interpreter")
    return {
        "video_python": python,
        **verify_sources(folder, frozen),
        **model_paths(root, folder / "models", frozen),
        "environment": folder,
        "observation": observation,
        "managed": True,
    }


def public_observation(observation):
    return video_environment.public_observation(observation)


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    public = public_observation(observation)
    folder = directory(Path(root).resolve(), "runtime/svi-environments/identities")
    path = folder / (public["environment_id"] + ".json")
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The SVI environment identity mapping changed")
    else:
        atomic_json(folder, path.name, observation)
    return public


def resolve_public(root, observation):
    if set(observation) != {"profile", "manifest_sha256", "environment_id"} or not re.fullmatch(
        r"[a-f0-9]{64}", observation["environment_id"]
    ):
        raise ValueError("The SVI engine requires its exact opaque identity")
    identity = read_json(
        Path(root).resolve()
        / "runtime/svi-environments/identities"
        / (observation["environment_id"] + ".json")
    )
    if public_observation(identity) != observation:
        raise ValueError("The SVI environment identity changed")
    return resolve(root, identity)
