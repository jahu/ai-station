"""Read-only discovery of the installed local Mac Docker Desktop prerequisite."""

import json
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
    code, endpoint = command(
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
    if code != 0:
        raise RuntimeError("Open Docker Desktop and complete its local setup, then try again")
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


def prerequisites(package, environment):
    """Read-only preflight for the complete Mac package candidate.

    Actual installed-consumer qualification is required before this branch can
    replace the release's platform gate. This function never installs Docker.
    """
    from desktop_engine import context_command, select
    from desktop_update import compatible
    from macos_transport_probe import ARCHITECTURES, INFO

    compatible(package)
    engine = select(environment)
    code, version = context_command(engine.command("compose", "version", "--short"), env=engine.environment)
    if code or not version or len(version) > 128:
        raise RuntimeError(
            "Docker Desktop's Compose is unavailable. Finish Docker Desktop setup and try again."
        )
    code, raw = context_command(engine.command("info", "--format", INFO), env=engine.environment)
    try:
        observed = json.loads(raw) if not code and len(raw) <= 4096 else None
    except (ValueError, TypeError):
        observed = None
    if (
        not isinstance(observed, dict)
        or set(observed) != {"os", "arch", "system"}
        or observed["os"] != "linux"
        or observed["system"] != "Docker Desktop"
        or ARCHITECTURES.get(observed["arch"]) != ARCHITECTURES.get(package["architecture"])
    ):
        raise RuntimeError("Open Docker Desktop's matching local Linux engine, then try again.")
    return engine
