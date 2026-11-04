"""Offline assembly of the built-in speech environment from verified objects.

The fixed native preparation operation owns this assembler; downloads, account
authority, cancellation and recovery use the existing Run and process lifecycle.
"""

import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from uuid import UUID

PROFILE = "chatterbox-v3-linux-x86-64-python312-v1"
RECIPE = Path(__file__).with_name("recipes") / (PROFILE + ".json")


def recipe():
    value = json.loads(RECIPE.read_text())
    if value["profile"] != PROFILE or len({v["sha256"] for v in value["inputs"]}) != len(value["inputs"]):
        raise ValueError("Invalid built-in speech recipe")
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def directory(root, relative):
    current = root
    for part in Path(relative).parts:
        if part in {".", ".."} or Path(part).is_absolute():
            raise ValueError("Invalid speech storage coordinate")
        current = current / part
        if current.is_symlink():
            raise ValueError("Speech storage cannot cross a symlink")
        current.mkdir(mode=0o700, exist_ok=True)
        info = current.stat()
        if not current.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("Speech storage must be an owned private directory")
    return current


def verified_object(root, item, check):
    path = root / "models" / "store" / item["sha256"]
    if path.parent.resolve() != root / "models" / "store":
        raise ValueError("Speech objects cannot cross a symlink")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o222
            or before.st_nlink != 1
            or before.st_size != item["size_bytes"]
        ):
            raise ValueError("Speech inputs require immutable owned objects with exact lengths")
        digest = hashlib.sha256()
        while chunk := source.read(4 * 1024**2):
            check()
            digest.update(chunk)
        after = os.fstat(source.fileno())

        def coordinate(info):
            return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size

        if coordinate(before) != coordinate(after) or digest.hexdigest() != item["sha256"]:
            raise ValueError("Speech input changed or has an unexpected hash")
    return path


def archive_path(name):
    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Runtime archives cannot escape their destination")
    return path


def unpack_tar(source, destination, check):
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        if len(members) > 10000 or sum(v.size for v in members) > 150 * 1024**2:
            raise ValueError("Speech SDK archive exceeded its bound")
        for member in members:
            archive_path(member.name)
            if not member.isfile() and not member.isdir():
                raise ValueError("Speech SDK archives cannot contain links or special files")
            check()
            archive.extract(member, destination, filter="data")
    entries = list(destination.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ValueError("Speech SDK archive must have one source root")
    return entries[0]


def unpack_segmenter(source, destination, check):
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > 1000 or sum(v.file_size for v in members) > 400 * 1024**2:
            raise ValueError("Speech tokenizer archive exceeded its bound")
        for item in members:
            archive_path(item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                raise ValueError("Speech tokenizer archive cannot contain links or special files")
            check()
            archive.extract(item, destination)


def unpack_python(source, destination, check, *, python_version="3.12"):
    """Pinned standalone Python includes legitimate in-tree binary/library links."""
    if python_version not in {"3.10", "3.12"}:
        raise ValueError("Use a reviewed fixed runtime Python version")
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        if len(members) > 20000 or sum(v.size for v in members) > 250 * 1024**2:
            raise ValueError("The standalone Python archive exceeded its bound")
        for item in members:
            path = archive_path(item.name)
            if path.parts[0] != "python" or not (
                item.isfile() or item.isdir() or item.issym() or item.islnk()
            ):
                raise ValueError("The standalone Python archive has an unexpected member")
            check()
            archive.extract(item, destination, filter="data")
    folder = destination / "python"
    for path in folder.rglob("*"):
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Standalone Python links must stay inside its owned directory")
    return folder / ("bin/python" + python_version)


def offline_environment(folder):
    return {
        "PATH": str(folder / "venv/bin") + os.pathsep + "/usr/bin:/bin",
        "HOME": str(folder / "home"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "HF_HOME": str(folder / "cache"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PKUSEG_HOME": str(folder / "segmenter"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "SOURCE_DATE_EPOCH": "1704067200",
    }


def command(argv, *, folder, check):
    check()
    # Inherit the caller's owned process group/deadline. No detached child.
    subprocess.run(argv, cwd=folder, env=offline_environment(folder), check=True)
    check()


def prepare(root, operation_id, *, check=lambda: None, progress=lambda value: None):
    """Trusted internal entry: fixed recipe, no network or caller-selected code.

    The caller must own the process group/deadline. Interrupted directories are
    preserved, never inferred ready or silently overwritten on another attempt.
    """
    if (
        platform.system() != "Linux"
        or platform.machine() not in {"x86_64", "AMD64"}
        or sys.version_info[:2] != (3, 12)
    ):
        raise ValueError("This speech environment requires Linux x86-64 and Python 3.12")
    root = Path(root).resolve(strict=True)
    frozen = recipe()
    identity = fingerprint(frozen)
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Runtime storage cannot cross a symlink")
    runtime.mkdir(mode=0o700, exist_ok=True)
    info = runtime.stat()
    # Common app runtime storage can be group writable for the same-user
    # control plane. The native speech subtree itself is private below it.
    if not runtime.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o002:
        raise ValueError("Runtime storage must remain owned and not world writable")
    base = directory(runtime, "speech/" + identity)
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing speech preparation instead of overwriting it")
    # Verify every executable/source input before creating or executing the venv.
    objects = {}
    for index, item in enumerate(frozen["inputs"]):
        objects[item["filename"]] = verified_object(root, item, check)
        progress(
            {"phase": "verifying_inputs", "completed_files": index + 1, "file_count": len(frozen["inputs"])}
        )
    check()
    folder.mkdir(mode=0o700)
    for name in ("home", "cache", "wheels", "sources", "built", "models", "segmenter"):
        directory(folder, name)
    (folder / "preparing.json").write_text(json.dumps({"profile": PROFILE, "manifest_sha256": identity}))
    progress({"phase": "creating_environment"})
    standalone = next(v for v in frozen["inputs"] if v["kind"] == "python")
    bootstrap = unpack_python(objects[standalone["filename"]], folder, check)
    command([str(bootstrap), "-m", "venv", "--without-pip", str(folder / "venv")], folder=folder, check=check)
    python = str(folder / "venv/bin/python")
    command([python, "-m", "ensurepip"], folder=folder, check=check)
    wheels = [v for v in frozen["inputs"] if v["kind"] == "wheel"]
    for item in wheels:
        # Only reviewed names inside this new directory; immutable store stays single-link.
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
    for item in (v for v in frozen["inputs"] if v["kind"] == "sdk"):
        progress({"phase": "building_sdk", "sdk": item["name"]})
        target = directory(folder, "sources/" + item["name"])
        source = unpack_tar(objects[item["filename"]], target, check)
        command(
            [
                python,
                "-m",
                "pip",
                "wheel",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(folder / "built"),
                str(source),
            ],
            folder=folder,
            check=check,
        )
    built = sorted((folder / "built").glob("*.whl"))
    if len(built) != 2:
        raise ValueError("Speech preparation must produce the two pinned SDK wheels")
    command(
        [python, "-m", "pip", "install", "--no-index", "--no-deps", *map(str, built)],
        folder=folder,
        check=check,
    )
    command([python, "-m", "pip", "check"], folder=folder, check=check)
    for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
        (folder / "models" / item["filename"]).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "models")
        )
    model_cache = directory(folder, "models/models--ResembleAI--chatterbox")
    snapshot = directory(model_cache, "snapshots/" + frozen["model_revision"])
    (snapshot / "Cangjie5_TC.json").symlink_to(os.path.relpath(objects["Cangjie5_TC.json"], snapshot))
    directory(model_cache, "refs").joinpath("main").write_text(frozen["model_revision"])
    segmenter = next(v for v in frozen["inputs"] if v["kind"] == "segmenter")
    (folder / "segmenter" / segmenter["filename"]).symlink_to(
        os.path.relpath(objects[segmenter["filename"]], folder / "segmenter")
    )
    unpack_segmenter(objects[segmenter["filename"]], directory(folder, "segmenter/spacy_ontonotes"), check)
    progress({"phase": "checking_environment"})
    probe = Path(__file__).with_name("speech_environment_probe.py")
    command([python, str(probe), str(folder)], folder=folder, check=check)
    check()
    receipt = {
        "profile": PROFILE,
        "manifest_sha256": identity,
        "operation_id": str(operation_id),
        "relative_path": folder.relative_to(root).as_posix(),
        "environment_prepared": True,
        "speech_inference_tested": False,
        "inputs": [{"filename": v["filename"], "sha256": v["sha256"]} for v in frozen["inputs"]],
    }
    # Readiness is last; uncompleted preparation never activates the audio adapter.
    temporary = folder / ".ready.json"
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.chmod(0o600)
    check()
    os.replace(temporary, folder / "ready.json")
    progress({"phase": "environment_prepared", "speech_inference_tested": False})
    return receipt
