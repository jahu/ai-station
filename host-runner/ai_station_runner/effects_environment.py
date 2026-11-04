"""Offline immutable MMAudio environment; configured installations remain separate."""

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

PROFILE = "mmaudio-large44-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")


def recipe():
    from ai_station_runner.effects_contract import ASSETS

    value = json.loads(RECIPE.read_text())
    items = value["inputs"]
    wheels = [v for v in items if v["kind"] == "wheel"]
    runtime = [v for v in wheels if not v.get("build_only")]
    models = [v for v in items if v["kind"] == "model"]
    if (
        value["profile"] != PROFILE
        or len(items) != 86
        or len({v["sha256"] for v in items}) != len(items)
        or len({v["filename"] for v in items}) != len(items)
        or len(wheels) != 76
        or len(runtime) != 74
        or len({re.sub(r"[-_.]+", "-", v["name"].lower()) for v in runtime}) != len(runtime)
        or len(models) != 7
        or {v["filename"] for v in models} != set(ASSETS)
        or any(
            v["size_bytes"] != ASSETS[v["filename"]]["size"] or v["sha256"] != ASSETS[v["filename"]]["sha256"]
            for v in models
        )
        or sum(v["kind"] == "sdist" for v in items) != 1
        or sum(v["kind"] == "sdk" for v in items) != 1
        or sum(v["kind"] == "python" for v in items) != 1
    ):
        raise ValueError("The complete fixed MMAudio preparation recipe is required")
    return value


def verify_source(source, frozen):
    source = Path(source)
    if source.resolve(strict=True) != source or not (source / "mmaudio/eval_utils.py").is_file():
        raise ValueError("The managed effects SDK cannot cross symlinks")
    sdk = source / "mmaudio"
    if any(p.is_symlink() for p in sdk.rglob("*")):
        raise ValueError("The effects SDK cannot contain symlinks")
    digest = hashlib.sha256()
    for path in sorted(p for p in sdk.rglob("*") if p.suffix in (".py", ".yaml", ".json")):
        if path.resolve(strict=True) != path or not path.is_file():
            raise ValueError("The effects SDK requires regular source files")
        name = path.relative_to(source).as_posix().encode()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    if digest.hexdigest() != frozen["source_sha256"]:
        raise ValueError("The prepared effects SDK changed from its reviewed source")
    return source


def model_paths(root, folder, frozen):
    root, folder = Path(root), Path(folder)
    store = root / "models/store"
    if folder.resolve(strict=True) != folder or store.resolve(strict=True) != store:
        raise ValueError("Effects storage cannot cross symlinks")
    result = {}
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        relative = item["filename"]
        if Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            raise ValueError("Use the fixed effects companion paths")
        link, target = folder / relative, store / item["sha256"]
        if (
            not link.is_symlink()
            or link.parent.resolve() != link.parent
            or link.resolve(strict=True) != target
            or target.resolve(strict=True) != target
        ):
            raise ValueError("Effects model links must bind exact immutable objects")
        info = target.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise ValueError("The immutable effects model object changed")
        result[relative] = link
    return result


def model_reference(models, relative):
    """An exact managed view may use checked links; all other roots stay strict."""
    models = Path(models)
    if (
        len(models.parents) < 5
        or models.name != "models"
        or models.parents[2].name != "effects-environments"
        or models.parents[3].name != "runtime"
    ):
        return None
    root, frozen = models.parents[4], recipe()
    identity = str(UUID(models.parent.name))
    expected = root / "runtime/effects-environments" / fingerprint(frozen) / identity / "models"
    if models != expected:
        raise ValueError("The managed effects model root changed")
    paths = model_paths(root, models, frozen)
    if relative not in paths:
        raise ValueError("The effects model is outside the fixed companion set")
    return paths[relative]


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("Effects preparation requires the Linux x86-64 Python 3.12 Host Runner")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Effects runtime storage cannot cross symlinks")
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.geteuid() or runtime.stat().st_mode & 0o002:
        raise ValueError("Effects runtime storage must be owned and not world writable")
    base = directory(runtime, "effects-environments/" + fingerprint(frozen))
    identity = str(UUID(str(operation_id)))
    folder = base / identity
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect existing effects preparation instead of overwriting it")
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
        unpack=lambda source, target, tick: unpack_python(source, target, tick, python_version="3.12"),
        prepare_wheels=lambda binary: avatar_source_wheel.build(
            binary, folder, frozen, objects, check=check, run_command=command, python_version=(3, 12, 14)
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
        [python, str(Path(__file__).with_name("effects_environment_probe.py")), str(folder)],
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
        effects_inference_tested=False,
    )
    path = folder / ".ready.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    check()
    os.replace(path, folder / "ready.json")
    progress(dict(phase="environment_prepared", effects_inference_tested=False))
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != dict(profile=PROFILE, manifest_sha256=fingerprint(frozen), operation_id=identity):
        raise ValueError("The effects environment differs from its reviewed recipe")
    folder = root / "runtime/effects-environments" / fingerprint(frozen) / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The effects environment has not completed preparation")
    binary, python = folder / "python/bin/python3.12", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Effects require their own prepared Python interpreter")
    model_paths(root, folder / "models", frozen)
    return dict(
        mmaudio_python=python,
        mmaudio_dir=verify_source(folder / "source", frozen),
        mmaudio_models=folder / "models",
        environment=folder,
        observation=observation,
        managed=True,
    )


def environment_id(observation):
    return fingerprint(observation)


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    folder = directory(Path(root).resolve() / "runtime", "effects-environments/identities")
    name = environment_id(observation) + ".json"
    path = folder / name
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The effects identity mapping changed")
    else:
        atomic_json(folder, name, observation)


def resolve_id(root, identity):
    if type(identity) is not str or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
        raise ValueError("Use the exact opaque effects environment identity")
    observed = read_json(
        Path(root).resolve() / "runtime/effects-environments/identities" / (identity + ".json")
    )
    if environment_id(observed) != identity:
        raise ValueError("The managed effects identity mapping changed")
    return resolve(root, observed)
