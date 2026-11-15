"""Pinned portrait extension over an immutable already prepared Live base runtime."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import UUID

from ai_station_runner import live_environment as base
from ai_station_runner.environment_files import command, read_json
from ai_station_runner.runtime_install import atomic_json
from ai_station_runner.speech_environment import directory, fingerprint, verified_object

PROFILE = "live-portrait-linux-x86-64-python312-v1"
MANIFEST = "a0b635338ffa58f3318318326e8df4c2794cfcf1fcd6f169c41ac08b4ac92678"
NAMESPACE = "live-portrait-environments"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
QUALIFIED = True  # Real CUDA duplex inference plus inherited ownership/transport contracts.


def recipe():
    value = json.loads(RECIPE.read_text())
    if value.get("profile") != PROFILE or fingerprint(value) != MANIFEST:
        raise ValueError("Animated portrait requires its complete reviewed recipe")
    return value


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    base_observation = read_json(root / "runtime" / base.NAMESPACE / "active.json")
    selected = base.resolve(root, base_observation)
    if base_observation["manifest_sha256"] != frozen["base_manifest_sha256"]:
        raise ValueError("Prepare the qualified Live base runtime first")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["sha256"]] = verified_object(root, item, check)
        progress(
            {"phase": "verifying_inputs", "completed_files": index + 1, "file_count": len(frozen["inputs"])}
        )
    folder = directory(root, f"runtime/{NAMESPACE}/{MANIFEST}") / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing portrait preparation instead of overwriting it")
    folder.mkdir(mode=0o700)
    for item in frozen["inputs"]:
        area = "models" if item["kind"] == "model" else "sdk"
        target = folder / area / item["target"]
        directory(folder, str(target.parent.relative_to(folder)))
        if area == "models":
            target.symlink_to(os.path.relpath(objects[item["sha256"]], target.parent))
        else:
            shutil.copyfile(objects[item["sha256"]], target)
            target.chmod(0o400)
    check()
    # Optional imports are checked in the existing isolated model Python, not HTTP.
    command(
        [
            selected["python"],
            "-I",
            "-B",
            "-c",
            "import sys;sys.path.insert(0,sys.argv[1]);from src.modules.motion_extractor import MotionExtractor;from src.modules.spade_generator import SPADEDecoder;import torch,yaml;assert torch.__version__.split('+')[0]=='2.14.0'",
            str(folder / "sdk"),
        ],
        folder=folder,
        check=check,
    )
    receipt = {
        "profile": PROFILE,
        "manifest_sha256": MANIFEST,
        "operation_id": str(operation_id),
        "relative_path": folder.relative_to(root).as_posix(),
        "environment_prepared": True,
        "base_runtime": base_observation,
        "source_manifest_sha256": base.source_manifest(folder),
        "live_inference_tested": False,
    }
    atomic_json(folder, "ready.json", receipt)
    progress({"phase": "environment_prepared", "live_inference_tested": False})
    return receipt


def model_paths(root, folder, frozen, *, verify_weights=False, check=lambda: None):
    return base.model_paths(root, folder, frozen, verify_weights=verify_weights, check=check)


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != {"profile": PROFILE, "manifest_sha256": MANIFEST, "operation_id": identity}:
        raise ValueError("The frozen portrait extension differs from its reviewed recipe")
    folder = root / "runtime" / NAMESPACE / MANIFEST / identity
    receipt = read_json(folder / "ready.json")
    if not all(
        receipt.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The portrait extension has not completed preparation")
    selected = base.resolve(root, receipt["base_runtime"])
    if receipt["base_runtime"]["manifest_sha256"] != frozen["base_manifest_sha256"]:
        raise ValueError("The portrait base runtime changed")
    if base.source_manifest(folder) != receipt["source_manifest_sha256"]:
        raise ValueError("The portrait source snapshot changed")
    # Recheck each SDK file, not only a self-reported receipt hash.
    expected_files = {v["target"] for v in frozen["inputs"] if v["kind"] == "sdk"}
    actual_files = {
        p.relative_to(folder / "sdk").as_posix() for p in (folder / "sdk").rglob("*") if p.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("Unexpected code in the fixed portrait SDK")
    for item in frozen["inputs"]:
        if item["kind"] != "sdk":
            continue
        path = folder / "sdk" / item["target"]
        if (
            path.resolve() != path
            or not path.is_file()
            or path.stat().st_uid != os.geteuid()
            or path.stat().st_nlink != 1
            or path.stat().st_mode & 0o222
            or path.stat().st_size != item["size_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("The fixed portrait SDK input changed")
    return {
        **selected,
        "observation": observation,
        "portrait_environment": folder,
        "portrait_sdk": folder / "sdk",
        **model_paths(root, folder / "models", frozen),
    }


def public_observation(observation):
    return base.public_observation(observation)


def remember(root, observation):
    resolve(root, observation)
    public = public_observation(observation)
    folder = directory(Path(root).resolve(), f"runtime/{NAMESPACE}/identities")
    path = folder / (public["environment_id"] + ".json")
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The portrait identity mapping changed")
    else:
        atomic_json(folder, path.name, observation)
    return public


def resolve_public(root, observation):
    import re

    if set(observation) != {"profile", "manifest_sha256", "environment_id"} or not re.fullmatch(
        r"[a-f0-9]{64}", observation["environment_id"]
    ):
        raise ValueError("Portrait requires its exact opaque environment identity")
    identity = read_json(
        Path(root).resolve()
        / "runtime"
        / NAMESPACE
        / "identities"
        / (observation["environment_id"] + ".json")
    )
    if public_observation(identity) != observation:
        raise ValueError("The portrait environment identity changed")
    return resolve(root, identity)
