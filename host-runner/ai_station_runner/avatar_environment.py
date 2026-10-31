"""Offline immutable Sonic environment; configured installations remain separate."""

import hashlib
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner import avatar_source_wheel
from ai_station_runner.environment_files import command, install_python, read_json
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    unpack_python,
    unpack_tar,
    verified_object,
)

PROFILE = "sonic-whole-linux-x86-64-python310-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")


def recipe():
    value = json.loads(RECIPE.read_text())
    items = value["inputs"]
    wheels = [v for v in items if v["kind"] == "wheel"]
    models = [v for v in items if v["kind"] == "model"]
    if (
        value["profile"] != PROFILE
        or len(items) != 92
        or len({v["sha256"] for v in items}) != len(items)
        or len({v["filename"] for v in items}) != len(items)
        or len(wheels) != 75
        or len({re.sub(r"[-_.]+", "-", v["name"].lower()) for v in wheels}) != 75
        or len(models) != 14
        or sum(v["kind"] == "sdist" for v in items) != 1
        or sum(v["kind"] == "sdk" for v in items) != 1
        or sum(v["kind"] == "python" for v in items) != 1
    ):
        raise ValueError("The complete fixed Sonic preparation recipe is required")
    return value


def verify_source(source, frozen):
    source = Path(source)
    if source.resolve(strict=True) != source or not (source / "sonic.py").is_file():
        raise ValueError("The managed avatar SDK cannot cross symlinks")
    paths = [*source.rglob("*.py"), source / "config/inference/sonic.yaml"]
    rows = []
    for path in sorted(paths, key=lambda p: p.relative_to(source).as_posix()):
        if path.resolve(strict=True) != path or not path.is_file():
            raise ValueError("The avatar SDK requires regular source files")
        content = path.read_bytes()
        rows.append(
            dict(
                path=path.relative_to(source).as_posix(),
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    if fingerprint(rows) != frozen["source_sha256"]:
        raise ValueError("The prepared avatar SDK changed from its reviewed source")
    return source


def model_paths(root, folder, frozen):
    root, folder = Path(root), Path(folder)
    store = root / "models/store"
    if folder.resolve(strict=True) != folder or store.resolve(strict=True) != store:
        raise ValueError("Avatar storage cannot cross symlinks")
    result = {}
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        relative = item["filename"]
        if Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            raise ValueError("Use the fixed avatar companion paths")
        link, target = folder / relative, store / item["sha256"]
        if (
            not link.is_symlink()
            or link.parent.resolve() != link.parent
            or link.resolve(strict=True) != target
            or target.resolve(strict=True) != target
        ):
            raise ValueError("Avatar model links must bind exact immutable objects")
        info = target.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise ValueError("The immutable avatar model object changed")
        result[relative] = link
    return result


def model_reference(models, relative):
    """An exact managed view may use checked links; all other roots stay strict."""
    models = Path(models)
    if (
        len(models.parents) < 5
        or models.name != "models"
        or models.parents[2].name != "avatar-environments"
        or models.parents[3].name != "runtime"
    ):
        return None
    root, frozen = models.parents[4], recipe()
    identity = str(UUID(models.parent.name))
    expected = root / "runtime/avatar-environments" / fingerprint(frozen) / identity / "models"
    if models != expected:
        raise ValueError("The managed avatar model root changed")
    paths = model_paths(root, models, frozen)
    if relative not in paths:
        raise ValueError("The avatar model is outside the fixed companion set")
    return paths[relative]


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("Avatar preparation requires the Linux x86-64 Python 3.12 Host Runner")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Avatar runtime storage cannot cross symlinks")
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.geteuid() or runtime.stat().st_mode & 0o002:
        raise ValueError("Avatar runtime storage must be owned and not world writable")
    base = directory(runtime, "avatar-environments/" + fingerprint(frozen))
    identity = str(UUID(str(operation_id)))
    folder = base / identity
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect existing avatar preparation instead of overwriting it")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(dict(phase="verifying_inputs", completed_files=index + 1, file_count=len(frozen["inputs"])))
    check()
    folder.mkdir(mode=0o700)
    for name in ("home", "cache", "wheels", "sources", "models", "bin"):
        directory(folder, name)
    python = install_python(
        folder,
        frozen,
        objects,
        check=check,
        progress=progress,
        run_command=command,
        unpack=lambda source, target, tick: unpack_python(source, target, tick, python_version="3.10"),
        prepare_wheels=lambda binary: avatar_source_wheel.build(
            binary, folder, frozen, objects, check=check, run_command=command
        ),
    )
    progress(dict(phase="preparing_sdk"))
    sdk = next(v for v in frozen["inputs"] if v["kind"] == "sdk")
    unpack_tar(objects[sdk["filename"]], folder / "sources", check).rename(folder / "source")
    verify_source(folder / "source", frozen)
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        link = folder / "models" / item["filename"]
        directory(folder / "models", link.parent.relative_to(folder / "models").as_posix())
        link.symlink_to(os.path.relpath(objects[item["filename"]], link.parent))
    model_paths(root, folder / "models", frozen)
    progress(dict(phase="checking_environment"))
    command(
        [python, str(Path(__file__).with_name("avatar_environment_probe.py")), str(folder)],
        folder=folder,
        check=check,
    )
    check()
    receipt = dict(
        profile=PROFILE,
        manifest_sha256=fingerprint(frozen),
        operation_id=identity,
        relative_path=folder.relative_to(root).as_posix(),
        environment_prepared=True,
        avatar_inference_tested=False,
    )
    path = folder / ".ready.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    check()
    os.replace(path, folder / "ready.json")
    progress(dict(phase="environment_prepared", avatar_inference_tested=False))
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != dict(profile=PROFILE, manifest_sha256=fingerprint(frozen), operation_id=identity):
        raise ValueError("The avatar environment differs from its reviewed recipe")
    folder = root / "runtime/avatar-environments" / fingerprint(frozen) / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The avatar environment has not completed preparation")
    binary, python = folder / "python/bin/python3.10", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Avatars require their own prepared Python interpreter")
    model_paths(root, folder / "models", frozen)
    codec = folder / "bin/ffmpeg"
    binaries = list(
        (folder / "venv/lib/python3.10/site-packages/imageio_ffmpeg/binaries").glob("ffmpeg-linux*")
    )
    if (
        len(binaries) != 1
        or not binaries[0].is_file()
        or binaries[0].resolve(strict=True) != binaries[0]
        or not os.access(binaries[0], os.X_OK)
        or codec.parent.resolve(strict=True) != codec.parent
        or not codec.is_symlink()
        or codec.resolve(strict=True) != binaries[0]
    ):
        raise ValueError("Avatars require their prepared offline FFmpeg")
    return dict(
        sonic_python=python,
        sonic_dir=verify_source(folder / "source", frozen),
        sonic_models=folder / "models",
        environment=folder,
        observation=observation,
        managed=True,
    )


def environment_id(observation):
    return fingerprint(observation)


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    folder = directory(Path(root).resolve() / "runtime", "avatar-environments/identities")
    name = environment_id(observation) + ".json"
    path = folder / name
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The avatar identity mapping changed")
    else:
        atomic_json(folder, name, observation)


def resolve_id(root, identity):
    if type(identity) is not str or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
        raise ValueError("Use the exact opaque avatar environment identity")
    observed = read_json(
        Path(root).resolve() / "runtime/avatar-environments/identities" / (identity + ".json")
    )
    if environment_id(observed) != identity:
        raise ValueError("The managed avatar identity mapping changed")
    return resolve(root, observed)
