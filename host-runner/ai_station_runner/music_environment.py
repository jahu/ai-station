"""Offline assembly for one pinned music profile; not a public installer API."""

import json
import os
import platform
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner import music_protocol
from ai_station_runner.environment_files import command as command
from ai_station_runner.environment_files import install_python
from ai_station_runner.environment_files import read_json as read_json
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    unpack_python,
    unpack_tar,
    verified_object,
)

PROFILE = "ace-step15-turbo-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")


def recipe():
    value = json.loads(RECIPE.read_text())
    inputs = value["inputs"]
    if (
        value["profile"] != PROFILE
        or fingerprint(value["model_manifest"]) != music_protocol.MANIFEST_SHA256
        or value["source_sha256"] != music_protocol.SOURCE_SHA256
        or len({v["sha256"] for v in inputs}) != len(inputs)
        or len({v["filename"] for v in inputs}) != len(inputs)
        or len([v for v in inputs if v["kind"] == "python"]) != 1
        or len([v for v in inputs if v["kind"] == "sdk"]) != 1
        or {v["filename"] for v in inputs if v["kind"] == "model"}
        != {v["path"] for v in value["model_manifest"]["files"]}
    ):
        raise ValueError("The complete fixed music recipe is required")
    return value


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("This music profile requires Linux x86-64 and Python 3.12")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    digest = fingerprint(frozen)
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Music runtime storage cannot cross a symlink")
    runtime.mkdir(mode=0o700, exist_ok=True)
    info = runtime.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o002:
        raise ValueError("Music runtime storage must be owned and not world writable")
    base = directory(runtime, "music-environments/" + digest)
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing music preparation instead of overwriting it")
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
    sdk = next(v for v in frozen["inputs"] if v["kind"] == "sdk")
    source = unpack_tar(objects[sdk["filename"]], folder / "sources", check)
    source.rename(folder / "source")
    music_protocol.verify_source(folder / "source")
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        target = (
            directory(folder / "models", str(Path(item["filename"]).parent)) / Path(item["filename"]).name
        )
        target.symlink_to(os.path.relpath(objects[item["filename"]], target.parent))
    model_receipt = folder / "models/ai-station-model.json"
    model_receipt.write_text(json.dumps(frozen["model_manifest"], indent=2) + "\n")
    model_receipt.chmod(0o400)
    music_protocol.model_manifest(
        folder / "models", verify_weights=True, immutable_root=root / "models/store"
    )
    progress({"phase": "checking_environment"})
    probe = Path(__file__).with_name("music_environment_probe.py")
    command([python, str(probe), str(folder), str(root)], folder=folder, check=check)
    check()
    receipt = dict(
        profile=PROFILE,
        manifest_sha256=digest,
        operation_id=str(operation_id),
        relative_path=folder.relative_to(root).as_posix(),
        environment_prepared=True,
        music_inference_tested=False,
    )
    temporary = folder / ".ready.json"
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.chmod(0o600)
    check()
    os.replace(temporary, folder / "ready.json")
    progress({"phase": "environment_prepared", "music_inference_tested": False})
    return receipt


def resolve(root, observation):
    """Resolve only the current recipe's owned, explicitly frozen environment."""
    from ai_station_runner.security import resolve_child

    root = Path(root).resolve(strict=True)
    digest = fingerprint(recipe())
    identity = str(UUID(observation["operation_id"]))
    if observation != {"profile": PROFILE, "manifest_sha256": digest, "operation_id": identity}:
        raise ValueError("The frozen music environment differs from the reviewed recipe")
    relative = f"runtime/music-environments/{digest}/{identity}"
    folder = root / relative
    if resolve_child(root, relative + "/ready.json") != folder / "ready.json":
        raise ValueError("Music readiness cannot cross a symlink")
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(key) == value
        for key, value in {**observation, "relative_path": relative, "environment_prepared": True}.items()
    ):
        raise ValueError("The frozen music environment has not completed preparation")
    binary = folder / "python/bin/python3.12"
    python = folder / "venv/bin/python"
    if (
        not binary.is_file()
        or binary.is_symlink()
        or not os.access(binary, os.X_OK)
        or python.resolve() != binary
    ):
        raise ValueError("Music requires its own prepared Python interpreter")
    music_protocol.verify_source(folder / "source")
    music_protocol.model_manifest(folder / "models", immutable_root=root / "models/store")
    return dict(
        python=python,
        source=folder / "source",
        models=folder / "models",
        environment=folder,
        observation=observation,
        managed=True,
    )
