"""Fixed CLI actions. Interactive links remain in native-private process output."""

import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from ai_station_runner.tailnet import cli_argv
from ai_station_runner.tailnet_install import private_directory, read_private, verified_install


def login_url(value, *, operation):
    if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() for c in value):
        return None
    parsed = urlsplit(value)
    prefix = "/a/" if operation == "login" else "/f/serve"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "login.tailscale.com"
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        return None
    return value


def _path(manager, run_id):
    if str(UUID(run_id)) != run_id:
        raise ValueError("Canonical private operation UUID required")
    folder = manager.root / "operations"
    private_directory(folder, create=False)
    return folder / (run_id + ".json")


def record(manager, run_id):
    manager._validate_owner()
    body = json.loads(read_private(_path(manager, run_id), limit=4096))
    if (
        not isinstance(body, dict)
        or body.get("run_id") != run_id
        or body.get("operation") not in {"install", "login", "serve_on", "serve_off"}
    ):
        raise ValueError("Private action journal changed")
    return body


def _begin(manager, run_id, operation, *, node_id=None, origin=None):
    if operation not in {"install", "login", "serve_on", "serve_off"}:
        raise ValueError("Unsupported private access action")
    if str(UUID(run_id)) != run_id:
        raise ValueError("Canonical private operation UUID required")
    manager._validate_owner(create=operation == "install")
    with manager._lock():
        if manager.canceled(run_id, operation):
            return {
                "run_id": run_id,
                "phase": "canceled",
                "process_confirmed_gone": True,
                "service": manager.status(),
            }
        status = manager.status()
        if operation != "install" and status["state"] in {
            "starting",
            "stopped",
            "unknown",
            "inspection_required",
        }:
            raise ValueError("The owned private service is not ready for this action")
        if status.get("configuration") == "unexpected":
            raise ValueError("Inspect the unexpected private service configuration")
        if operation not in {"install", "login"} and (
            not status.get("node_online")
            or (node_id, origin) != (status.get("node_id"), status.get("origin"))
        ):
            raise ValueError("The approved private device or origin changed")
        private_directory(manager.root / "operations")
        path = _path(manager, run_id)
        frozen = {
            "run_id": run_id,
            "operation": operation,
            "daemon_id": status.get("daemon_id") if operation != "install" else None,
            "node_id": node_id,
            "origin": origin,
        }
        if path.exists() or path.is_symlink():
            old = record(manager, run_id)
            if any(old.get(k) != v for k, v in frozen.items()):
                raise ValueError("Private operation cannot change its submitted scope")
            return _inspect(manager, run_id)
        architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
        if operation != "install":
            verified_install(manager.binary_dir, architecture)
        body = {**frozen, "created_at": time.time()}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(body, handle)
        log_dir = manager.root / "runs" / run_id
        log_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name in ("stdout.log", "stderr.log"):
            fd = os.open(log_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        manager._processes().start(
            run_id=run_id,
            argv=[
                sys.executable,
                str(Path(__file__).with_name("tailnet_install.py")),
                "--prefix",
                str(manager.binary_dir.parent),
                "--architecture",
                architecture,
            ]
            if operation == "install"
            else cli_argv(
                manager.binary_dir / "tailscale", manager.socket, operation, ui_port=manager.ui_port
            ),
            cwd=manager.root,
            executor="tailnet-" + operation,
            env={"PATH": os.defpath, "HOME": str(manager.root), "LANG": "C.UTF-8"},
            deadline_at=time.time() + (180 if operation == "install" else 15),
        )
        return _inspect(manager, run_id)


def _process(manager, body):
    process = manager._processes().inspect(body["run_id"])
    if process["executor"] != "tailnet-" + body["operation"] or process["cwd"] != str(manager.root):
        raise ValueError("Private operation lost its process ownership")
    return process


def _action_url(manager, body, process):
    if manager.canceled(body["run_id"], body["operation"]):
        return None
    if time.time() - body["created_at"] > 300 or process["status"] in {
        "canceled",
        "cancel_requested",
        "interrupted",
    }:
        return None
    # Only the latest action of this kind may disclose its interactive link.
    folder = manager.root / "operations"
    for path in folder.glob("*.json"):
        other = json.loads(read_private(path, limit=4096))
        if other.get("operation") == body["operation"] and other.get("created_at", 0) > body["created_at"]:
            return None
    if body["operation"] == "install":
        return None
    if body["operation"] == "login":
        raw = manager._read_api("/localapi/v0/status")
        if raw.get("BackendState") != "NeedsLogin":
            return None
        url = login_url(raw.get("AuthURL"), operation="login")
        if url:
            return url
    urls = set()
    for text in [process.get("stdout", ""), process.get("stderr_tail", "")]:
        for match in re.findall(r'https://login\.tailscale\.com/[^\s"<>]+', text):
            url = login_url(match, operation=body["operation"])
            if url:
                urls.add(url)
    return next(iter(urls)) if len(urls) == 1 else None


def _inspect(manager, run_id):
    body = record(manager, run_id)
    process = _process(manager, body)
    status = manager.status()
    if body["operation"] != "install" and status.get("daemon_id") != body["daemon_id"]:
        raise ValueError("Private operation belongs to another daemon start")
    phase = "running"
    if not process["alive"] and not process.get("completion_pending"):
        if manager.canceled(run_id, body["operation"]) or process["status"] == "canceled":
            phase = "canceled"
        elif process["exit_code"] is None:
            phase = "interrupted"
        elif body["operation"] == "install":
            try:
                architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
                verified_install(manager.binary_dir, architecture)
                phase = "succeeded" if process["exit_code"] == 0 else "failed"
            except (ValueError, OSError):
                phase = "failed"
        elif body["operation"] == "login":
            phase = (
                "succeeded"
                if status.get("node_online")
                else "login_required"
                if _action_url(manager, body, process)
                else "failed"
            )
        elif body["operation"] == "serve_on":
            same = (status.get("node_id"), status.get("origin")) == (body["node_id"], body["origin"])
            phase = (
                "succeeded"
                if process["exit_code"] == 0 and same and status.get("serving")
                else "https_consent_required"
                if same and _action_url(manager, body, process)
                else "failed"
            )
        else:
            phase = (
                "succeeded"
                if process["exit_code"] == 0 and status.get("configuration") == "empty"
                else "failed"
            )
    return {
        "run_id": run_id,
        "operation": body["operation"],
        "phase": phase,
        "process_confirmed_gone": not process["alive"] and not process.get("completion_pending"),
        "service": status,
    }


def _remember(manager, run_id, result):
    if result.get("operation") == "serve_on" and result["phase"] == "succeeded":
        body = record(manager, run_id)
        manager.remember_endpoint(body["node_id"], body["origin"])
    return result


def begin(manager, run_id, operation, *, node_id=None, origin=None):
    return _remember(manager, run_id, _begin(manager, run_id, operation, node_id=node_id, origin=origin))


def inspect(manager, run_id):
    return _remember(manager, run_id, _inspect(manager, run_id))


def action_link(manager, run_id):
    body = record(manager, run_id)
    result = inspect(manager, run_id)
    if result["phase"] not in {"running", "login_required", "https_consent_required"}:
        return None
    return _action_url(manager, body, _process(manager, body))


def cancel(manager, run_id):
    body = record(manager, run_id)
    manager.request_cancel(run_id, body["operation"])
    _process(manager, body)
    process = manager._processes().cancel(run_id)
    gone = not process["alive"] and not process.get("completion_pending")
    return {
        "run_id": run_id,
        "operation": body["operation"],
        "phase": "canceled" if gone else "cancel_requested",
        "process_confirmed_gone": gone,
        "service": manager.status(),
    }


def drain(manager):
    """Disable may resolve uncertainty only after all owned private jobs are gone."""
    folder = manager.root / "operations"
    if not folder.exists():
        return
    private_directory(folder, create=False)
    for path in folder.glob("*.json"):
        body = record(manager, path.stem)
        process = _process(manager, body)
        if process["alive"] or process.get("completion_pending"):
            manager.request_cancel(body["run_id"], body["operation"])
            result = cancel(manager, body["run_id"])
            if not result["process_confirmed_gone"]:
                raise ValueError("Private setup job is still stopping")
