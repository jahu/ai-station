"""Standard-library-only model views usable by the separate CPU ASR child."""

import json
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from ai_station_runner.environment_files import read_json
from ai_station_runner.speech_environment import fingerprint

PROFILE = "fish-s2-pro-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
GROUPS = {"fish", "transcription"}


def view_recipe():
    value = json.loads(RECIPE.read_text())
    if value.get("profile") != PROFILE or len(value.get("inputs", [])) != 163:
        raise ValueError("Use the fixed Fish/Whisper model view recipe")
    return value


def model_paths(root, folder, group, frozen):
    if group not in GROUPS:
        raise ValueError("Use the fixed Fish or transcription model group")
    root, folder = Path(root), Path(folder)
    store = root / "models/store"
    if folder.resolve(strict=True) != folder or store.resolve(strict=True) != store:
        raise ValueError("Fish model storage cannot cross symlinks")
    result = {}
    for item in (v for v in frozen["inputs"] if v["kind"] == "model" and v["model_group"] == group):
        name = item["model_filename"]
        if Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Use fixed direct model filenames")
        link, target = folder / name, store / item["sha256"]
        if not link.is_symlink() or link.resolve(strict=True) != target or target.resolve() != target:
            raise ValueError("Fish model views must bind their exact immutable objects")
        info = target.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise ValueError("The immutable Fish/Whisper model object changed")
        result[name] = link
    return result


def model_reference(models, name, frozen=None):
    """Only this exact managed namespace may use closed-world model links."""
    models = Path(models)
    if (
        len(models.parents) < 6
        or models.name not in GROUPS
        or models.parent.name != "models"
        or models.parents[3].name != "fish-environments"
        or models.parents[4].name != "runtime"
    ):
        return None
    root = models.parents[5]
    frozen = frozen if frozen is not None else view_recipe()
    identity = str(UUID(models.parents[1].name))
    expected = root / "runtime/fish-environments" / fingerprint(frozen) / identity / "models" / models.name
    if models != expected:
        raise ValueError("The managed Fish model root changed")
    checked_ready(root, models.parents[1], frozen, identity)
    paths = model_paths(root, models, models.name, frozen)
    if name not in paths:
        raise ValueError("Model is outside the fixed Fish/Whisper companion set")
    return paths[name]


def checked_ready(root, folder, frozen, identity):
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(key) == value
        for key, value in {
            "profile": PROFILE,
            "manifest_sha256": fingerprint(frozen),
            "operation_id": identity,
            "relative_path": folder.relative_to(root).as_posix(),
            "environment_prepared": True,
        }.items()
    ):
        raise ValueError("The Fish/Whisper model view is not prepared")


def environment_directory(root, identity):
    if type(identity) is not str or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
        raise ValueError("Use the exact opaque Fish environment identity")
    root, frozen = Path(root).resolve(strict=True), view_recipe()
    observed = read_json(root / "runtime/fish-environments/identities" / (identity + ".json"))
    operation = str(UUID(observed["operation_id"]))
    if fingerprint(observed) != identity or observed != {
        "profile": PROFILE,
        "manifest_sha256": fingerprint(frozen),
        "operation_id": operation,
    }:
        raise ValueError("The Fish environment identity changed")
    folder = root / "runtime/fish-environments" / fingerprint(frozen) / operation
    checked_ready(root, folder, frozen, operation)
    return folder
