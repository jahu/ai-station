"""Offline assembly for one pinned music profile; not a public installer API."""

import json
import os
import platform
import re
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from ai_station_runner import music_protocol
from ai_station_runner.speech_environment import (
    directory,
    fingerprint,
    offline_environment,
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


def command(argv, *, folder, check):
    check()
    environment = {
        **offline_environment(folder),
        "CUDA_VISIBLE_DEVICES": "",
        "NUMBA_CACHE_DIR": str(folder / "cache/numba"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    # Every child inherits the owned preparation group/scope and deadline.
    subprocess.run(argv, cwd=folder, env=environment, check=True)
    check()


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
    standalone = next(v for v in frozen["inputs"] if v["kind"] == "python")
    progress({"phase": "creating_environment"})
    bootstrap = unpack_python(objects[standalone["filename"]], folder, check)
    command([str(bootstrap), "-m", "venv", "--without-pip", str(folder / "venv")], folder=folder, check=check)
    python = str(folder / "venv/bin/python")
    command([python, "-m", "ensurepip"], folder=folder, check=check)
    wheels = [v for v in frozen["inputs"] if v["kind"] == "wheel"]
    for item in wheels:
        if Path(item["filename"]).name != item["filename"] or not re.fullmatch(
            r"[a-zA-Z0-9_.-]+", item["name"]
        ):
            raise ValueError("Music dependencies require fixed wheel names")
        (folder / "wheels" / item["filename"]).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "wheels")
        )
    lock = folder / "requirements.lock"
    lock.write_text(
        "\n".join(f"{v['name']}=={v['version']} --hash=sha256:{v['sha256']}" for v in wheels) + "\n"
    )
    progress({"phase": "installing_dependencies"})
    command(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--find-links",
            str(folder / "wheels"),
            "-r",
            str(lock),
        ],
        folder=folder,
        check=check,
    )
    command([python, "-m", "pip", "check"], folder=folder, check=check)
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


def read_json(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError("Music environment metadata cannot cross symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o022
            or info.st_size > 32768
        ):
            raise ValueError("Music environment metadata must be a bounded owned regular file")
        text = source.read(32769)
        if len(text) > 32768:
            raise ValueError("Music environment metadata exceeds its size limit")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("Music environment metadata must be an object")
        return value


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
