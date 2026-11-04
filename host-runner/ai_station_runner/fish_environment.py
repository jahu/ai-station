"""Fixed offline Fish/Whisper environments; no user-supplied packages or paths."""

import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner import fish_source_wheels
from ai_station_runner.environment_files import command, install_python, read_json
from ai_station_runner.fish_contract import MODEL_FILES, SOURCE_SHA256, digest, source_files
from ai_station_runner.fish_model_views import model_paths as model_paths
from ai_station_runner.fish_model_views import model_reference as checked_model_reference
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    unpack_python,
    unpack_tar,
    verified_object,
)

PROFILE = "fish-s2-pro-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")
GROUPS = {"fish", "transcription"}
ASR_FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}


def recipe():
    value = json.loads(RECIPE.read_text())
    items = value["inputs"]
    models = [v for v in items if v["kind"] == "model"]
    if (
        value["profile"] != PROFILE
        or value["python_version"] != "3.12.14"
        or value["source_sha256"] != SOURCE_SHA256
        or len(items) != 163
        or len({v["sha256"] for v in items}) != len(items)
        or len({v["filename"] for v in items}) != len(items)
        or len(models) != 13
        or any(not v["environments"] or not set(v["environments"]) <= GROUPS for v in items)
        or sum(v["kind"] == "sdk" for v in items) != 1
        or sum(v["kind"] == "python" for v in items) != 1
    ):
        raise ValueError("The complete fixed Fish/Whisper recipe is required")
    fish_source_wheels.validate(value)
    fish_models = {v["model_filename"]: v for v in models if v["model_group"] == "fish"}
    if set(fish_models) != set(MODEL_FILES) or any(
        fish_models[name]["sha256"] != expected["sha256"]
        or fish_models[name]["size_bytes"] != expected["size"]
        for name, expected in MODEL_FILES.items()
    ):
        raise ValueError("The fixed Fish model set changed")
    if {v["model_filename"] for v in models if v["model_group"] == "transcription"} != ASR_FILES:
        raise ValueError("The complete offline Whisper model is required")
    for group, count in (("fish", 133), ("transcription", 23)):
        actual = {
            re.sub(r"[-_.]+", "-", v["name"].lower()): v["version"]
            for v in items
            if v["kind"] == "wheel" and group in v["environments"] and not v.get("build_only")
        }
        if group == "fish":
            actual.update({name: v["version"] for name, v in fish_source_wheels.SOURCES.items()})
        expected = {
            re.sub(r"[-_.]+", "-", v["name"].lower()): v["version"] for v in value["dependency_groups"][group]
        }
        if len(actual) != count or len(expected) != count or actual != expected:
            raise ValueError("Each Fish/Whisper environment needs its complete independent dependency set")
    return value


def verify_source(source):
    source = Path(source)
    if source.resolve(strict=True) != source:
        raise ValueError("Managed Fish source cannot cross symlinks")
    value = hashlib.sha256()
    for path in source_files(source):
        name = path.relative_to(source).as_posix().encode()
        value.update(len(name).to_bytes(4, "big"))
        value.update(name)
        value.update(bytes.fromhex(digest(path)))
    if value.hexdigest() != SOURCE_SHA256:
        raise ValueError("Prepared Fish source differs from the reviewed revision")
    return source


def model_reference(models, name):
    return checked_model_reference(models, name, frozen=recipe())


def whisper_manifest(frozen):
    return {
        "version": 1,
        "model": "Systran/faster-whisper-tiny",
        "revision": frozen["transcription_revision"],
        "files": {
            v["model_filename"]: {"size": v["size_bytes"], "sha256": v["sha256"]}
            for v in frozen["inputs"]
            if v["kind"] == "model" and v["model_group"] == "transcription"
        },
    }


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("Fish preparation requires the Linux x86-64 Python 3.12 Host Runner")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Fish runtime storage cannot cross symlinks")
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.stat().st_uid != os.geteuid() or runtime.stat().st_mode & 0o002:
        raise ValueError("Fish runtime storage must be owned and not world writable")
    base = directory(runtime, "fish-environments/" + fingerprint(frozen))
    identity = str(UUID(str(operation_id)))
    folder = base / identity
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect existing Fish preparation instead of overwriting it")
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(dict(phase="verifying_inputs", completed_files=index + 1, file_count=len(frozen["inputs"])))
    check()
    folder.mkdir(mode=0o700)
    for name in ("sources", "models/fish", "models/transcription"):
        directory(folder, name)
    for group in ("fish", "transcription"):
        target = directory(folder, group)
        for name in ("home", "cache", "wheels"):
            directory(target, name)
        subset = {**frozen, "inputs": [v for v in frozen["inputs"] if group in v["environments"]]}
        install_python(
            target,
            subset,
            objects,
            check=check,
            progress=lambda value, role=group: progress({**value, "environment": role}),
            run_command=command,
            unpack=lambda source, target, tick: unpack_python(source, target, tick, python_version="3.12"),
            prepare_wheels=(
                lambda binary: fish_source_wheels.build(
                    binary, target, subset, objects, check=check, run_command=command
                )
            )
            if group == "fish"
            else None,
        )
    progress(dict(phase="preparing_sdk"))
    sdk = next(v for v in frozen["inputs"] if v["kind"] == "sdk")
    unpack_tar(objects[sdk["filename"]], folder / "sources", check).rename(folder / "source")
    verify_source(folder / "source")
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        link = folder / "models" / item["model_group"] / item["model_filename"]
        link.symlink_to(os.path.relpath(objects[item["filename"]], link.parent))
    manifest = folder / "models/transcription/ai-station-model.json"
    manifest.write_text(json.dumps(whisper_manifest(frozen), indent=2) + "\n")
    manifest.chmod(0o600)
    for group in ("fish", "transcription"):
        model_paths(root, folder / "models" / group, group, frozen)
        progress(dict(phase="checking_environment", environment=group))
        command(
            [
                str(folder / group / "venv/bin/python"),
                str(Path(__file__).with_name("fish_environment_probe.py")),
                str(folder),
                group,
            ],
            folder=folder / group,
            check=check,
        )
    verify_source(folder / "source")
    check()
    receipt = dict(
        profile=PROFILE,
        manifest_sha256=fingerprint(frozen),
        operation_id=identity,
        relative_path=folder.relative_to(root).as_posix(),
        environment_prepared=True,
        fish_inference_tested=False,
    )
    path = folder / ".ready.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    check()
    os.replace(path, folder / "ready.json")
    progress(dict(phase="environment_prepared", fish_inference_tested=False))
    return receipt


def resolve(root, observation):
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = str(UUID(observation["operation_id"]))
    if observation != dict(profile=PROFILE, manifest_sha256=fingerprint(frozen), operation_id=identity):
        raise ValueError("The Fish environment differs from its reviewed recipe")
    folder = root / "runtime/fish-environments" / fingerprint(frozen) / identity
    ready = read_json(folder / "ready.json")
    if not all(
        ready.get(k) == v
        for k, v in {
            **observation,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }.items()
    ):
        raise ValueError("The Fish/Whisper environment has not completed preparation")
    binaries = {}
    for group in ("fish", "transcription"):
        binary, python = folder / group / "python/bin/python3.12", folder / group / "venv/bin/python"
        if (
            not binary.is_file()
            or binary.is_symlink()
            or not os.access(binary, os.X_OK)
            or python.resolve() != binary
        ):
            raise ValueError("Fish/Whisper require their own prepared Python interpreters")
        model_paths(root, folder / "models" / group, group, frozen)
        binaries[group] = python
    if read_json(folder / "models/transcription/ai-station-model.json") != whisper_manifest(frozen):
        raise ValueError("The prepared Whisper model manifest changed")
    return dict(
        fish_speech_python=binaries["fish"],
        fish_speech_dir=verify_source(folder / "source"),
        fish_speech_models=folder / "models/fish",
        transcription_python=binaries["transcription"],
        transcription_model_dir=folder / "models/transcription",
        environment=folder,
        observation=observation,
        managed=True,
    )


def environment_id(observation):
    return fingerprint(observation)


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    folder = directory(Path(root).resolve() / "runtime", "fish-environments/identities")
    name = environment_id(observation) + ".json"
    path = folder / name
    if path.exists():
        if read_json(path) != observation:
            raise ValueError("The Fish identity mapping changed")
    else:
        atomic_json(folder, name, observation)


def resolve_id(root, identity):
    if type(identity) is not str or re.fullmatch(r"[a-f0-9]{64}", identity) is None:
        raise ValueError("Use the exact opaque Fish environment identity")
    observed = read_json(Path(root).resolve() / "runtime/fish-environments/identities" / (identity + ".json"))
    if environment_id(observed) != identity:
        raise ValueError("The managed Fish identity mapping changed")
    return resolve(root, observed)
