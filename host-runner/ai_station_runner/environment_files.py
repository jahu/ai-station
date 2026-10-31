"""Pure offline environment file/dependency primitives for fixed native profiles."""

import json
import os
import re
import stat
import subprocess
from pathlib import Path

from ai_station_runner.speech_environment import offline_environment, unpack_python


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


def read_json(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError("Managed environment metadata cannot cross symlinks")
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
            raise ValueError("Managed environment metadata must be a bounded owned regular file")
        text = source.read(32769)
        if len(text) > 32768:
            raise ValueError("Managed environment metadata exceeds its size limit")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("Managed environment metadata must be an object")
        return value


def install_python(
    folder,
    frozen,
    objects,
    *,
    check,
    progress,
    run_command=command,
    unpack=unpack_python,
    prepare_wheels=None,
):
    """Install only verified, exact wheels; no resolver, network or ambient site packages."""
    standalone = next(v for v in frozen["inputs"] if v["kind"] == "python")
    progress({"phase": "creating_environment"})
    bootstrap = unpack(objects[standalone["filename"]], folder, check)
    run_command(
        [str(bootstrap), "-m", "venv", "--without-pip", str(folder / "venv")], folder=folder, check=check
    )
    python = str(folder / "venv/bin/python")
    run_command([python, "-m", "ensurepip"], folder=folder, check=check)
    wheels = [v for v in frozen["inputs"] if v["kind"] == "wheel"]
    for item in wheels:
        if Path(item["filename"]).name != item["filename"] or not re.fullmatch(
            r"[a-zA-Z0-9_.-]+", item["name"]
        ):
            raise ValueError("Runtime dependencies require fixed wheel names")
        (folder / "wheels" / item["filename"]).symlink_to(
            os.path.relpath(objects[item["filename"]], folder / "wheels")
        )
    if prepare_wheels is not None:
        wheels = [*wheels, *prepare_wheels(python)]
    lock = folder / "requirements.lock"
    lock.write_text(
        "\n".join(f"{v['name']}=={v['version']} --hash=sha256:{v['sha256']}" for v in wheels) + "\n"
    )
    progress({"phase": "installing_dependencies"})
    run_command(
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
    run_command([python, "-m", "pip", "check"], folder=folder, check=check)
    return python
