"""Offline assembly and exact selection of one built-in headless Wan profile."""

import hashlib
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner.environment_files import command, install_python, read_json
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    unpack_python,
    unpack_tar,
    verified_object,
)

PROFILE = "wan22-5b-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
ROLES = {"wan_model", "wan_text_encoder", "wan_vae"}


def recipe():
    value = json.loads(RECIPE.read_text())
    items = value["inputs"]
    wheels = [v for v in items if v["kind"] == "wheel"]
    models = [v for v in items if v["kind"] == "model"]
    normalized = [re.sub(r"[-_.]+", "-", v["name"].lower()) for v in wheels]
    if (
        value["profile"] != PROFILE
        or len(items) != 102
        or len({v["sha256"] for v in items}) != len(items)
        or len({v["filename"] for v in items}) != len(items)
        or len(wheels) != 97
        or len(set(normalized)) != len(wheels)
        or len(models) != 3
        or {v["role"] for v in models} != ROLES
        or len([v for v in items if v["kind"] == "sdk"]) != 1
        or len([v for v in items if v["kind"] == "python"]) != 1
    ):
        raise ValueError("The complete coherent fixed video recipe is required")
    return value


def verify_source(source, frozen):
    source = Path(source)
    if source.resolve(strict=True) != source or not (source / "nodes.py").is_file():
        raise ValueError("The managed video SDK cannot cross symlinks")
    files = []
    for path in sorted(source.rglob("*.py"), key=lambda p: p.relative_to(source).as_posix()):
        if path.is_symlink() or path.resolve(strict=True) != path or not path.is_file():
            raise ValueError("The managed video SDK requires regular Python files")
        content = path.read_bytes()
        files.append(
            dict(
                path=path.relative_to(source).as_posix(),
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    if fingerprint(files) != frozen["source_sha256"]:
        raise ValueError("The managed video SDK changed from its frozen source")
    return source


def model_paths(root, folder, frozen, *, verify_weights=False, check=lambda: None):
    root, folder = Path(root), Path(folder)
    store = root / "models/store"
    if store.resolve(strict=True) != store or folder.resolve(strict=True) != folder:
        raise ValueError("Managed video storage cannot cross symlinks")
    paths = {}
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        name = item["filename"]
        if Path(name).name != name or not name.endswith(".safetensors") or item["role"] not in ROLES:
            raise ValueError("Video models require their fixed safetensors names and roles")
        link, target = folder / name, store / item["sha256"]
        if (
            not link.is_symlink()
            or link.resolve(strict=True) != target
            or target.resolve(strict=True) != target
        ):
            raise ValueError("Video model links must bind their exact immutable objects")
        info = target.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise ValueError("The immutable video model object changed")
        if verify_weights:
            verified_object(root, item, check)
        paths[item["role"]] = link
    if paths.keys() != ROLES:
        raise ValueError("All three video model companions are required")
    return paths


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("This video profile requires Linux x86-64 and Python 3.12")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Video runtime storage cannot cross a symlink")
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.geteuid() or runtime.stat().st_mode & 0o002:
        raise ValueError("Video runtime storage must be owned and not world writable")
    base = directory(runtime, "video-environments/" + fingerprint(frozen))
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing video preparation instead of overwriting it")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(dict(phase="verifying_inputs", completed_files=index + 1, file_count=len(frozen["inputs"])))
    check()
    folder.mkdir(mode=0o700)
    for name in ("home", "cache", "wheels", "sources", "models"):
        directory(folder, name)
    python = install_python(
        folder, frozen, objects, check=check, progress=progress, run_command=command, unpack=unpack_python
    )
    progress(dict(phase="preparing_sdk"))
    sdk = next(v for v in frozen["inputs"] if v["kind"] == "sdk")
    unpack_tar(objects[sdk["filename"]], folder / "sources", check).rename(folder / "source")
    verify_source(folder / "source", frozen)
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        (folder / "models" / item["filename"]).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "models")
        )
    model_paths(root, folder / "models", frozen)
    progress(dict(phase="checking_environment"))
    command(
        [python, str(Path(__file__).with_name("video_environment_probe.py")), str(folder), str(root)],
        folder=folder,
        check=check,
    )
    check()
    receipt = dict(
        profile=PROFILE,
        manifest_sha256=fingerprint(frozen),
        operation_id=str(operation_id),
        relative_path=folder.relative_to(root).as_posix(),
        environment_prepared=True,
        video_inference_tested=False,
    )
    path = folder / ".ready.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    check()
    os.replace(path, folder / "ready.json")
    progress(dict(phase="environment_prepared", video_inference_tested=False))
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != dict(profile=PROFILE, manifest_sha256=fingerprint(frozen), operation_id=identity):
        raise ValueError("The frozen video environment differs from the reviewed recipe")
    folder = root / "runtime/video-environments" / fingerprint(frozen) / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The video environment has not completed preparation")
    binary, python = folder / "python/bin/python3.12", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Video requires its own prepared Python interpreter")
    return dict(
        video_python=python,
        comfy_dir=verify_source(folder / "source", frozen),
        **model_paths(root, folder / "models", frozen),
        environment=folder,
        observation=observation,
        managed=True,
    )


def public_observation(observation):
    """Shared engine identity never discloses another account's preparation Run."""
    return {
        "profile": observation["profile"],
        "manifest_sha256": observation["manifest_sha256"],
        "environment_id": fingerprint(observation),
    }


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    public = public_observation(observation)
    folder = directory(Path(root).resolve() / "runtime", "video-environments/identities")
    path = folder / (public["environment_id"] + ".json")
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The managed video identity mapping changed")
        return public
    atomic_json(folder, path.name, observation)
    return public


def resolve_public(root, observation):
    if set(observation) != {"profile", "manifest_sha256", "environment_id"} or not re.fullmatch(
        r"[a-f0-9]{64}", observation["environment_id"]
    ):
        raise ValueError("The video engine requires its exact opaque identity")
    identity = read_json(
        Path(root).resolve()
        / "runtime/video-environments/identities"
        / (observation["environment_id"] + ".json")
    )
    if public_observation(identity) != observation:
        raise ValueError("The managed video environment identity changed")
    return resolve(root, identity)
