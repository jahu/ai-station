"""Opaque prepared speech identities, shared without preparation account/Run IDs."""

import os
import re
import stat
from pathlib import Path
from uuid import UUID

from ai_station_runner import speech_environment
from ai_station_runner.environment_files import read_json

PROFILE = "chatterbox-v3-linux-x86-64-python312-v1"


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    if (
        not isinstance(observation, dict)
        or set(observation) != {"profile", "manifest_sha256", "operation_id"}
        or any(not isinstance(value, str) for value in observation.values())
    ):
        raise ValueError("Speech requires its exact prepared environment observation")
    frozen = speech_environment.recipe()
    identity = str(UUID(observation["operation_id"]))
    manifest = speech_environment.fingerprint(frozen)
    if observation != {"profile": PROFILE, "manifest_sha256": manifest, "operation_id": identity}:
        raise ValueError("The frozen speech environment differs from the reviewed recipe")
    folder = root / "runtime/speech" / manifest / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(key) == value
        for key, value in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The speech environment has not completed preparation")
    binary, python = folder / "python/bin/python3.12", folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Speech requires its own prepared Python interpreter")
    models = folder / "models"
    store = root / "models/store"
    if models.resolve(strict=True) != models or store.resolve(strict=True) != store:
        raise ValueError("Speech model directories cannot cross symlinks")
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        name = item["filename"]
        if Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Use the fixed direct speech model filenames")
        path, target = models / name, store / item["sha256"]
        if not path.is_symlink() or path.resolve(strict=True) != target or target.resolve() != target:
            raise ValueError("Speech model views must retain their exact immutable objects")
        info = target.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise ValueError("A fixed speech model object changed")
    cache = folder / "cache"
    if not cache.is_dir() or cache.resolve() != cache:
        raise ValueError("Speech requires its own prepared offline cache")
    return {
        "python": python,
        "script": Path(__file__).with_name("managed_speech_job.py"),
        "cache": cache,
        "models": models,
        "environment": folder,
        "managed": True,
        "observation": observation,
    }


def public_observation(observation):
    return {
        "profile": observation["profile"],
        "manifest_sha256": observation["manifest_sha256"],
        "environment_id": speech_environment.fingerprint(observation),
    }


def active(root):
    root = Path(root).resolve(strict=True)
    return resolve(root, read_json(root / "runtime/speech/active.json"))


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    public = public_observation(observation)
    folder = speech_environment.directory(Path(root).resolve() / "runtime", "speech/identities")
    path = folder / (public["environment_id"] + ".json")
    if path.exists() or path.is_symlink():
        if read_json(path) != observation:
            raise ValueError("The managed speech identity mapping changed")
    else:
        atomic_json(folder, path.name, observation)
    return public


def before_adoption(root, observation):
    # Preserve an older activated environment before replacing its active pointer.
    # Existing shared bindings can then outlive a later explicit preparation.
    try:
        previous = active(root)["observation"]
    except (OSError, ValueError, KeyError):
        previous = None
    if previous is not None:
        remember(root, previous)
    remember(root, observation)


def resolve_public(root, observation):
    if (
        not isinstance(observation, dict)
        or set(observation) != {"profile", "manifest_sha256", "environment_id"}
        or not isinstance(observation["environment_id"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", observation["environment_id"])
    ):
        raise ValueError("Speech requires its exact opaque engine identity")
    root = Path(root).resolve(strict=True)
    path = root / "runtime/speech/identities" / (observation["environment_id"] + ".json")
    try:
        identity = read_json(path)
    except FileNotFoundError:
        # Read-only compatibility for an engine activated before opaque identities.
        selected = active(root)
        if public_observation(selected["observation"]) != observation:
            raise ValueError("The selected speech environment identity is unavailable") from None
        return selected
    if public_observation(identity) != observation:
        raise ValueError("The managed speech environment identity changed")
    return resolve(root, identity)
