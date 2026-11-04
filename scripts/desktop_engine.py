"""Process-local Docker routing for the trusted desktop installer/supervisor."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerEngine:
    prefix: tuple[str, ...]
    environment: dict[str, str]
    identity: tuple[str, str] | None = None

    def command(self, *arguments: str) -> list[str]:
        return [*self.prefix, *arguments]


def context_command(argv, *, env):
    try:
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Open Docker Desktop and complete its local setup, then try again") from None
    return result.returncode, result.stdout.strip()


def select(environment: dict[str, str], *, expected: tuple[str, str] | None = None) -> DockerEngine:
    """Pin Mac commands; retain existing Linux/WSL routing and configuration."""
    if platform.system() != "Darwin":
        if expected is not None:
            raise RuntimeError("Docker Desktop handoff coordinates require a native Mac")
        return DockerEngine(("docker",), dict(environment))

    from macos_desktop_docker import connection

    binary, endpoint = connection(context_command)
    identity = (binary, endpoint)
    if expected is not None and identity != expected:
        raise RuntimeError(
            "Docker Desktop changed during startup. Close AI Station and try again; "
            "no image or Compose operation was sent to the replacement engine."
        )
    # Explicit --host is retained for every command, including Compose shutdown.
    # Remove context, TLS and builder overrides before Docker/Compose sees them;
    # a shell's other station must not override this local desktop selection.
    env = {
        key: value
        for key, value in environment.items()
        if not key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
    }
    env.update(
        HOME=str(Path.home()),
        PATH=str(Path(binary).parent) + os.pathsep + os.defpath,
        DOCKER_HOST=endpoint,
    )
    return DockerEngine((binary, "--host", endpoint), env, identity)
