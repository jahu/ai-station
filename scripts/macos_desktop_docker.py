"""Read-only discovery of the installed local Mac Docker Desktop prerequisite."""

import os
import platform
import shutil
import stat
from pathlib import Path
from urllib.parse import urlsplit


def application_binaries():
    return (
        Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
        Path.home() / "Applications/Docker.app/Contents/Resources/bin/docker",
    )


def find_cli():
    if platform.system() != "Darwin":
        raise RuntimeError("Docker Desktop discovery requires a native Mac")
    known = application_binaries()
    targets = set()
    for path in known:
        try:
            application = path.parents[3]
            if application.is_symlink():
                continue
            actual = path.resolve(strict=True)
            if actual.is_relative_to(application.resolve(strict=True)):
                targets.add(actual)
        except (OSError, RuntimeError):
            continue
    ambient = shutil.which("docker")
    candidates = [*known, Path.home() / ".docker/bin/docker"]
    if ambient:
        candidates.append(Path(ambient))
    for candidate in candidates:
        try:
            actual = candidate.resolve(strict=True)
            info = actual.stat()
        except (OSError, RuntimeError):
            continue
        if (
            actual in targets
            and stat.S_ISREG(info.st_mode)
            and not info.st_mode & 0o022
            and os.access(actual, os.X_OK)
        ):
            return actual
    raise RuntimeError(
        "Open Docker Desktop from Applications and complete its setup first. "
        "AI Station did not install software or change Docker settings."
    )


def connection(command):
    binary = find_cli()
    # Finder does not inherit shell startup files. Do not copy Docker/provider
    # routing or credentials from another station's environment.
    env = {"PATH": str(binary.parent) + os.pathsep + os.defpath, "HOME": str(Path.home()), "LANG": "C"}
    _, endpoint = command(
        [
            str(binary),
            "context",
            "inspect",
            "desktop-linux",
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        ],
        env=env,
    )
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "unix"
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 32 for char in endpoint)
        or endpoint != "unix://" + parsed.path
    ):
        raise ValueError("Only the local Docker Desktop Unix endpoint is accepted")
    return str(binary), endpoint
