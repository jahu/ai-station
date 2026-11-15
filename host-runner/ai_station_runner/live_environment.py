"""Frozen offline Live runtime. No ambient Python, model resolver or host devices."""

import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner.environment_files import command, install_python, read_json
from ai_station_runner.speech_environment import directory, fingerprint, unpack_tar, verified_object

PROFILE = "live-identity-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
MANIFEST = "4efdf390b80da847e8c1e89861de73241e1d9fda267e04e027bd0021cdca82ba"
QUALIFIED = True  # Linux separate-GPU synthetic-device and session contracts qualified.
NAMESPACE = "live-environments"


def recipe():
    value = json.loads(RECIPE.read_text())
    if value.get("profile") != PROFILE or fingerprint(value) != MANIFEST:
        raise ValueError("Live requires its complete reviewed engine recipe")
    return value


def model_paths(root, folder, frozen, *, verify_weights=False, check=lambda: None):
    result = {}
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        path = folder / item["target"]
        expected = root / "models/store" / item["sha256"]
        if path.resolve(strict=True) != expected or expected.resolve() != expected:
            raise ValueError("Live model links must identify their exact immutable objects")
        info = expected.stat()
        if (
            not expected.is_file()
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
        ):
            raise ValueError("Live models require immutable owned regular objects")
        if info.st_size != item["size_bytes"]:
            raise ValueError("Live model size changed")
        if verify_weights:
            verified_object(root, item, check)
        result[item["role"]] = path
    return result


def source_manifest(folder):
    result = {}
    for path in sorted((folder / "sdk").rglob("*")):
        if path.is_symlink():
            raise ValueError("Live source cannot cross symlinks")
        if path.is_file() and path.suffix != ".pyc":
            result[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprint(result)


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (platform.system(), platform.machine(), sys.version_info[:2]) != ("Linux", "x86_64", (3, 12)):
        raise ValueError("This Live profile requires Linux x86-64 and Python 3.12")
    from ai_station_runner.live_source_wheels import build

    root = Path(root).resolve(strict=True)
    frozen = recipe()
    base = directory(root, f"runtime/{NAMESPACE}/{MANIFEST}")
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing Live preparation instead of overwriting it")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(
            {"phase": "verifying_inputs", "completed_files": index + 1, "file_count": len(frozen["inputs"])}
        )
    check()
    folder.mkdir(mode=0o700)
    for name in ("home", "cache", "wheels", "sources", "models", "integration"):
        directory(folder, name)
    python = install_python(
        folder,
        frozen,
        objects,
        check=check,
        progress=progress,
        prepare_wheels=lambda python: build(
            python, folder, frozen, objects, check=check, run_command=command
        ),
    )
    progress({"phase": "preparing_sdk"})
    sdk = next(v for v in frozen["inputs"] if v.get("name") == "Seed-VC-Realtime")
    unpack_tar(objects[sdk["filename"]], directory(folder / "sources", "sdk"), check).rename(folder / "sdk")
    # Upstream examples and desktop frontends are unnecessary for browser IPC.
    for path in list((folder / "sdk").iterdir()):
        if path.name not in {
            "audio_modules",
            "configs",
            "realtime_vc_engine.py",
            "hf_utils.py",
            "LICENSE",
            "README.md",
        }:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    for name, target in (("Seed-VC-Live-Bridge", "bridge.py"), ("Seed-VC-Live-License", "LICENSE")):
        item = next(v for v in frozen["inputs"] if v.get("name") == name)
        shutil.copyfile(objects[item["filename"]], folder / "integration" / target)
        (folder / "integration" / target).chmod(0o400)
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        target = Path(item["target"])
        directory(folder / "models", target.parent)
        (folder / "models" / target).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "models" / target.parent)
        )
    model_paths(root, folder / "models", frozen)
    progress({"phase": "checking_environment"})
    command(
        [python, str(Path(__file__).with_name("live_environment_probe.py")), str(folder)],
        folder=folder,
        check=check,
    )
    receipt = {
        "profile": PROFILE,
        "manifest_sha256": MANIFEST,
        "operation_id": str(operation_id),
        "relative_path": folder.relative_to(root).as_posix(),
        "environment_prepared": True,
        "source_manifest_sha256": source_manifest(folder),
        "live_inference_tested": False,
    }
    from ai_station_runner.runtime_install import atomic_json

    check()
    atomic_json(folder, "ready.json", receipt)
    progress({"phase": "environment_prepared", "live_inference_tested": False})
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != {"profile": PROFILE, "manifest_sha256": MANIFEST, "operation_id": identity}:
        raise ValueError("The frozen Live environment differs from its reviewed recipe")
    folder = root / "runtime" / NAMESPACE / MANIFEST / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The Live environment has not completed preparation")
    binary, python = folder / "python/bin/python3.12", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Live requires its own prepared Python")
    if source_manifest(folder) != ready["source_manifest_sha256"]:
        raise ValueError("The prepared Live SDK changed")
    for name, target in (("Seed-VC-Live-Bridge", "bridge.py"), ("Seed-VC-Live-License", "LICENSE")):
        item = next(v for v in frozen["inputs"] if v.get("name") == name)
        path = folder / "integration" / target
        if path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("The fixed independent voice integration changed")
    return {
        "python": python,
        "environment": folder,
        "observation": observation,
        **model_paths(root, folder / "models", frozen),
    }


def public_observation(observation):
    from ai_station_runner.video_environment import public_observation as public

    return public(observation)


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    public = public_observation(observation)
    folder = directory(Path(root).resolve(), f"runtime/{NAMESPACE}/identities")
    name = public["environment_id"] + ".json"
    if (folder / name).exists():
        if read_json(folder / name) != observation:
            raise ValueError("The Live identity mapping changed")
    else:
        atomic_json(folder, name, observation)
    return public


def resolve_public(root, observation):
    import re

    if set(observation) != {"profile", "manifest_sha256", "environment_id"} or not re.fullmatch(
        r"[a-f0-9]{64}", observation["environment_id"]
    ):
        raise ValueError("Live requires its exact opaque environment identity")
    identity = read_json(
        Path(root).resolve()
        / "runtime"
        / NAMESPACE
        / "identities"
        / (observation["environment_id"] + ".json")
    )
    if public_observation(identity) != observation:
        raise ValueError("The Live environment identity changed")
    return resolve(root, identity)
