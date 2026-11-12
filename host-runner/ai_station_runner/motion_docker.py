"""Pinned local Docker connection for fixed motion operations, never an API."""

import json
import os
import subprocess
from pathlib import Path


def environment():
    return {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "DOCKER_CONFIG"}}


def call(args, *, missing_ok=False):
    result = subprocess.run(["docker", *args], env=environment(), capture_output=True, text=True, timeout=15)
    if len(result.stdout) > 512000 or len(result.stderr) > 64000:
        raise ValueError("Motion Docker response exceeded its bound")
    if result.returncode:
        if missing_ok and "no such" in result.stderr.lower():
            return None
        raise ValueError("The owned motion container operation could not be confirmed")
    return result.stdout.strip()


def connection():
    host = os.environ.get("DOCKER_HOST")
    if not host:
        context = os.environ.get("DOCKER_CONTEXT")
        args = (
            ["context", "inspect"]
            + ([context] if context else [])
            + ["--format", "{{json .Endpoints.docker.Host}}"]
        )
        host = json.loads(call(args))
    if not isinstance(host, str) or not host.startswith("unix:///"):
        raise ValueError("Motion rendering requires a local Unix Docker connection")
    socket = Path(host.removeprefix("unix://")).resolve(strict=True)
    if not socket.is_socket():
        raise ValueError("The local motion Docker socket is unavailable")
    host = "unix://" + str(socket)
    identity = call(["--host", host, "info", "--format", "{{.ID}}"])
    if not identity or len(identity) > 200:
        raise ValueError("The local Docker daemon identity is unavailable")
    return {"host": host, "daemon_id": identity}


def docker(args, *, bound=None, missing_ok=False):
    bound = connection() if bound is None else bound
    if not isinstance(bound, dict) or not isinstance(bound.get("daemon_id"), str) or not bound["daemon_id"]:
        raise ValueError("Motion Docker identity is invalid")
    host = bound.get("host", "")
    if (
        not isinstance(host, str)
        or not host.startswith("unix:///")
        or not Path(host.removeprefix("unix://")).is_socket()
    ):
        raise ValueError("Motion Docker connection changed")
    if call(["--host", host, "info", "--format", "{{.ID}}"]) != bound.get("daemon_id"):
        raise ValueError("Refusing a different motion Docker daemon")
    return call(["--host", host, *args], missing_ok=missing_ok)
