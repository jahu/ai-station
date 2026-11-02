"""Owned Mac installer preflight; no application, Runner or agent endpoint."""

import json
import os
import re
import stat
import subprocess
import time
from uuid import uuid4

from dotenv import dotenv_values
from macos_transport_probe import data_parent, private_file, receipt

STARTUP_TIMEOUT = 180


def private_directory(path):
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or path.resolve(strict=True) != path
    ):
        raise ValueError("Bridge proof storage must remain a private owned canonical directory")


def read_json(path):
    private_file(path)
    if path.stat().st_size > 65536:
        raise ValueError("Bridge proof exceeded its bound")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Bridge proof must be an object")
    return value


def completed(root, request):
    if (
        request.get("schema") != 1
        or not isinstance(request.get("attempt"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", request["attempt"])
        or not isinstance(request.get("image"), str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", request["image"])
        or not isinstance(request.get("data_directory"), str)
    ):
        raise ValueError("The previous bridge request needs inspection")
    output = root / request["attempt"]
    private_directory(output)
    result = read_json(output / "result.json")
    if (
        result.get("probe_kind") != "packaged_application"
        or result.get("platform") != "Darwin"
        or result.get("image") != request["image"]
        or result.get("chosen_data_directory") != request["data_directory"]
        or result.get("cleanup_complete") is not True
        or result.get("macos_installer_qualified") is not False
    ):
        raise ValueError("The previous bridge cleanup was not confirmed; inspect the desktop log")
    if result.get("transport_passed") is True:
        checks = result.get("checks")
        if (
            result.get("image_id") != request["image"]
            or not isinstance(checks, dict)
            or checks.get("native_peer_uid") != os.geteuid()
            or any(
                checks.get(key) is not True
                for key in (
                    "socket_rebind",
                    "client_restart",
                    "sqlite_wal",
                    "concurrent_writer_lock",
                    "chosen_data_filesystem",
                )
            )
        ):
            raise ValueError("The bridge did not confirm the complete private socket/filesystem checks")
    return result


def stop_child(child):
    if child.poll() is None:
        child.terminate()  # Only this immediate, unreaped Popen handle.
        try:
            child.wait(timeout=45)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "Bridge cleanup is still running; inspect the desktop log before retrying"
            ) from None


def check(installed, state, config, value, engine, log, control):
    if engine.identity is None:
        raise ValueError("The Mac bridge requires its discovered Docker Desktop connection")
    if not isinstance(value.get("image_id"), str) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", value["image_id"]
    ):
        raise ValueError("The Mac bridge requires the verified bundled image identity")
    selected = dotenv_values(config, interpolate=False).get("AI_STATION_DATA_HOST_PATH")
    if not selected:
        raise ValueError("The desktop configuration has no application data directory")
    selected = data_parent(selected)
    root = state / "bridge-checks"
    root.mkdir(mode=0o700, exist_ok=True)
    private_directory(root)
    pending = root / "pending.json"
    if pending.exists() or pending.is_symlink():
        # A completed private receipt permits recovery after parent exit. Never
        # retry an uncertain create, signal a recorded PID or remove its files.
        completed(root, read_json(pending))
        pending.unlink()
    if control.stop_requested.is_set():
        return False
    request = {
        "schema": 1,
        "attempt": uuid4().hex,
        "image": value["image_id"],
        "data_directory": str(selected),
    }
    receipt(pending, request)
    child = None
    stopped = False
    timed_out = False
    try:
        child = subprocess.Popen(
            [
                str(installed / "python/bin/python3"),
                "-IB",
                str(installed / "scripts/macos_transport_probe.py"),
                "--output",
                str(root / request["attempt"]),
                "--data-directory",
                str(selected),
                "--packaged-image",
                request["image"],
                "--expected-cli",
                engine.identity[0],
                "--expected-endpoint",
                engine.identity[1],
            ],
            env=engine.environment,
            cwd=installed,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while child.poll() is None:
            if control.stop_requested.is_set() or time.monotonic() >= deadline:
                stopped = True
                timed_out = not control.stop_requested.is_set()
                stop_child(child)
                break
            time.sleep(0.1)
        output = root / request["attempt"]
        if stopped and not output.exists() and not output.is_symlink():
            if timed_out:
                raise RuntimeError(
                    "The private Docker Desktop check timed out; inspect the desktop log and try again"
                )
            return False  # Finally clears the confirmed pre-dispatch marker.
        result = completed(root, request)
        pending.unlink()
        if timed_out:
            raise RuntimeError(
                "The private Docker Desktop check timed out; inspect the desktop log and try again"
            )
        if stopped or control.stop_requested.is_set():
            return False
        if child.returncode or result.get("transport_passed") is not True:
            raise RuntimeError(
                "Docker Desktop could not share the private bridge/data filesystem. Inspect the desktop log; no station was started."
            )
        return True
    except OSError:
        if child is None:
            pending.unlink()  # Popen did not launch a process or send a request.
        raise
    finally:
        if child is not None:
            stop_child(child)
            output = root / request["attempt"]
            if not output.exists() and not output.is_symlink() and pending.exists():
                # The probe publishes this directory before any engine operation.
                # An exited child without it cannot have created a container.
                if read_json(pending) == request:
                    pending.unlink()
