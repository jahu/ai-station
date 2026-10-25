"""Owned native service primitives. No operational HTTP endpoint is registered yet."""

import fcntl
import hashlib
import json
import os
import platform
import socket
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx

from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from ai_station_runner.tailnet import daemon_argv, exact_serve_config, public_status
from ai_station_runner.tailnet_install import private_directory, read_private, verified_install


class TailnetManager:
    def __init__(self, private_root: Path, binary_dir: Path, data_root: Path, *, ui_port: int = 8765):
        self.root = private_root.expanduser().absolute()
        self.data_root = data_root.expanduser().resolve()
        if (
            self.root.resolve() != self.root
            or self.root.is_relative_to(self.data_root)
            or self.data_root.is_relative_to(self.root)
            or type(ui_port) is not int
            or not 1 <= ui_port <= 65535
        ):
            raise ValueError("Native private access must be separate from control-plane data")
        self.binary_dir = binary_dir.expanduser().absolute()
        self.ui_port = ui_port
        self.socket = self.root / "control.sock"
        if len(os.fsencode(self.socket)) > 100:
            raise ValueError("Native private access needs a shorter Unix socket path")
        self.owner = {
            "owner": "ai-station-tailnet",
            "version": 1,
            "uid": os.getuid(),
            "data_root_sha256": hashlib.sha256(str(self.data_root).encode()).hexdigest(),
        }
        self._manager = None

    def _validate_owner(self, *, create=False):
        private_directory(self.root, create=create)
        marker = self.root / "owner.json"
        if not marker.exists() and not marker.is_symlink():
            if not create or any(self.root.iterdir()):
                raise ValueError("This private directory is not owned by AI Station")
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(self.owner, handle)
        if json.loads(read_private(marker, limit=4096)) != self.owner:
            raise ValueError("This private service belongs to another data directory")

    @contextmanager
    def _lock(self):
        fd = os.open(self.root / "service.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            info = os.fstat(lock.fileno())
            if (
                info.st_uid != os.getuid()
                or info.st_nlink != 1
                or not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
            ):
                raise ValueError("Private service lock is not owned")
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _processes(self):
        registry = self.root / "runtime/processes.json"
        if registry.exists() or registry.is_symlink():
            read_private(registry, limit=1024 * 1024)
        if self._manager is None:
            self._manager = ProcessManager(self.root, grace_seconds=0.5)
        return self._manager

    def _service(self):
        path = self.root / "service.json"
        if not path.exists() and not path.is_symlink():
            return None
        record = json.loads(read_private(path, limit=4096))
        if not isinstance(record, dict) or str(UUID(record.get("run_id", ""))) != record.get("run_id"):
            raise ValueError("Private service ownership journal is invalid")
        return record

    def _write(self, record):
        path = self.root / "service.tmp"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            info = os.fstat(handle.fileno())
            if (
                info.st_uid != os.getuid()
                or info.st_nlink != 1
                or not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
            ):
                raise ValueError("Private service journal is unsafe")
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path, self.root / "service.json")

    def _inspect(self, service):
        try:
            result = self._processes().inspect(service["run_id"])
        except ProcessNotOwned as exc:
            raise ValueError("Inspect the private launch journal before retrying") from exc
        if result["executor"] != "tailnet-daemon" or result["cwd"] != str(self.root):
            raise ValueError("Private process no longer belongs to this service")
        return result

    def _socket_ready(self, *, harden=False):
        try:
            info = self.socket.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Private service socket changed ownership or type")
        if harden:
            os.chmod(self.socket, 0o600)
        elif stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Private service socket is not restricted")
        return True

    def _read_api(self, path):
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(self.socket)),
            base_url="http://local-tailscaled.sock",
            timeout=2,
            trust_env=False,
        ) as client:
            with client.stream("GET", path) as response:
                response.raise_for_status()
                parts, size = [], 0
                for block in response.iter_bytes():
                    size += len(block)
                    if size > 1024 * 1024:
                        raise ValueError("Private service response exceeds its limit")
                    parts.append(block)
        return json.loads(b"".join(parts))

    def status(self):
        if not self.root.exists() and not self.root.is_symlink():
            return {"state": "stopped", "owned": False, "node_online": False, "serving": False}
        self._validate_owner()
        service = self._service()
        if service is None:
            return {"state": "stopped", "owned": True, "node_online": False, "serving": False}
        if not (self.root / "runtime/processes.json").exists():
            return {"state": "inspection_required", "owned": True, "node_online": False, "serving": False}
        record = self._inspect(service)
        if not record["alive"]:
            return {
                "state": "inspection_required"
                if self.socket.exists() or self.socket.is_symlink()
                else "stopped",
                "owned": True,
                "daemon_id": service["run_id"],
                "node_online": False,
                "serving": False,
            }
        if not self._socket_ready():
            return {
                "state": "starting",
                "owned": True,
                "daemon_id": service["run_id"],
                "node_online": False,
                "serving": False,
            }
        try:
            answer = public_status(self._read_api("/localapi/v0/status"))
            config = self._read_api("/localapi/v0/serve-config")
        except (httpx.HTTPError, ValueError, OSError):
            answer, config = {"state": "unknown", "node_online": False}, None
        serving = bool(
            answer.get("origin") and exact_serve_config(config, answer["origin"], ui_port=self.ui_port)
        )
        return {**answer, "owned": True, "daemon_id": service["run_id"], "serving": serving}

    def start(self, run_id: str):
        if str(UUID(run_id)) != run_id:
            raise ValueError("Canonical operation UUID required")
        self._validate_owner(create=True)
        with self._lock():
            old = self._service()
            if old is not None and self._inspect(old)["alive"]:
                for _ in range(50):
                    if self._socket_ready(harden=True):
                        break
                    time.sleep(0.02)
                return {**self.status(), "started": False}
            if old is not None and old["run_id"] == run_id:
                raise ValueError("Inspect the previous start; use a new reviewed operation to retry")
            if self.socket.exists() or self.socket.is_symlink():
                raise ValueError("Inspect the existing private socket before restarting")
            architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
            verified_install(self.binary_dir, architecture)
            journal = {"run_id": run_id, "phase": "preparing"}
            self._write(journal)
            log_dir = self.root / "runs" / run_id
            log_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            for name in ("stdout.log", "stderr.log"):
                fd = os.open(log_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            self._processes().start(
                run_id=run_id,
                argv=daemon_argv(self.binary_dir / "tailscaled", self.root, self.socket),
                cwd=self.root,
                executor="tailnet-daemon",
                env={"PATH": os.defpath, "HOME": str(self.root), "LANG": "C.UTF-8"},
            )
            self._write({**journal, "phase": "running"})
            for _ in range(50):
                if self._socket_ready(harden=True):
                    break
                if not self._inspect(journal)["alive"]:
                    break
                time.sleep(0.02)
            return {**self.status(), "started": True}

    def stop(self, *, only_start_run_id: str | None = None):
        self._validate_owner()
        with self._lock():
            service = self._service()
            if service is None or only_start_run_id is not None and service["run_id"] != only_start_run_id:
                return {"stopped": False}
            record = self._inspect(service)
            before = self.socket.lstat() if self.socket.exists() or self.socket.is_symlink() else None
            if record["alive"]:
                record = self._processes().cancel(service["run_id"])
            if record["alive"]:
                raise ValueError("Private process shutdown is not confirmed")
            if before is not None and (self.socket.exists() or self.socket.is_symlink()):
                self._socket_ready()
                after = self.socket.lstat()
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise ValueError("Private socket was replaced during shutdown")
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(0.5)
                    try:
                        probe.connect(str(self.socket))
                    except ConnectionRefusedError:
                        self.socket.unlink()
                    else:
                        raise ValueError("Private socket still has a listener; inspect ownership")
            return {"stopped": True, "daemon_id": service["run_id"]}
