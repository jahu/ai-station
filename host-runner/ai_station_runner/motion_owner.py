"""Exact ownership of one network-disabled motion container per native Run."""

import csv
import fcntl
import io
import json
import os
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from ai_station_runner.motion_assets import request_digest
from ai_station_runner.motion_contract import MotionRequest
from ai_station_runner.motion_docker import docker
from ai_station_runner.motion_image import IMAGE_ID
from ai_station_runner.security import resolve_child

CID = re.compile(r"[0-9a-f]{64}")


def directory(root, run_id):
    root = Path(root).resolve()
    rid = str(UUID(run_id))
    path = resolve_child(root, f"runs/{rid}/motion")
    if path != root / f"runs/{rid}/motion":
        raise ValueError("Motion ownership traverses a symlink")
    return path


def save(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load(root, run_id):
    path = directory(root, run_id) / "request.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512000:
        raise ValueError("Motion request ownership is missing or unsafe")
    saved = json.loads(path.read_text())
    if not isinstance(saved, dict) or set(saved) != {
        "request",
        "digest",
        "image",
        "recipe",
        "user",
        "connection",
    }:
        raise ValueError("Motion request ownership fields changed")
    body = MotionRequest.model_validate(saved["request"])
    if (
        str(body.run_id) != str(UUID(run_id))
        or request_digest(body) != saved["digest"]
        or not isinstance(saved["image"], str)
        or not IMAGE_ID.fullmatch(saved["image"])
        or not isinstance(saved["recipe"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", saved["recipe"])
        or not isinstance(saved["connection"], dict)
        or set(saved["connection"]) != {"host", "daemon_id"}
        or not isinstance(saved["connection"].get("host"), str)
        or not isinstance(saved["connection"].get("daemon_id"), str)
        or saved["user"] != f"{os.getuid()}:{os.getgid()}"
        or os.getuid() == 0
    ):
        raise ValueError("Motion request ownership changed")
    return saved


def identity(saved):
    rid = str(UUID(saved["request"]["run_id"]))
    return f"ai-station-motion-{rid}", {
        "ai-station.motion.run": rid,
        "ai-station.motion.request": saved["digest"],
        "ai-station.motion.recipe": saved["recipe"],
    }


def inspect_owned(root, saved, container_id=None):
    name, expected = identity(saved)
    raw = docker(
        ["inspect", "--type", "container", name, "--format", "{{json .}}"],
        bound=saved["connection"],
        missing_ok=True,
    )
    if not raw:
        return None
    item = json.loads(raw)
    config = item.get("Config") or {}
    host = item.get("HostConfig") or {}
    labels = config.get("Labels") or {}
    work = str(directory(root, saved["request"]["run_id"]) / "work")
    mounts = item.get("Mounts") or []
    binds = [m for m in mounts if m.get("Type") == "bind"]
    tmpfs = [m for m in mounts if m.get("Type") == "tmpfs"]
    if (
        not CID.fullmatch(item.get("Id", ""))
        or (container_id and item["Id"] != container_id)
        or item.get("Image") != saved["image"]
        or any(labels.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("Refusing a container with different motion ownership")
    if (
        config.get("User") != saved["user"]
        or config.get("Entrypoint") != ["python", "-m", "ai_station_runner.motion_container"]
        or config.get("Cmd") not in (None, [])
    ):
        raise ValueError("Motion container executable/user policy changed")
    if (
        host.get("NetworkMode") != "none"
        or host.get("Runtime") != "runc"
        or host.get("Privileged")
        or not host.get("ReadonlyRootfs")
        or host.get("Devices")
        or host.get("DeviceRequests")
        or host.get("PortBindings")
        or host.get("CapAdd")
    ):
        raise ValueError("Motion container isolation changed")
    if host.get("CapDrop") != ["ALL"] or not any(
        value.startswith("no-new-privileges") for value in (host.get("SecurityOpt") or [])
    ):
        raise ValueError("Motion container privilege policy changed")
    if (
        host.get("Memory") != 4096 * 1024**2
        or host.get("MemorySwap") != 4096 * 1024**2
        or host.get("NanoCpus") != 4_000_000_000
        or host.get("PidsLimit") != 512
        or host.get("CgroupnsMode") != "private"
    ):
        raise ValueError("Motion container resource limits changed")
    if (
        len(binds) != 1
        or len(mounts) != len(binds) + len(tmpfs)
        or any(m.get("Destination") != "/tmp" or m.get("RW") is not True for m in tmpfs)
        or binds[0].get("Source") != work
        or binds[0].get("Destination") != "/work"
        or binds[0].get("RW") is not True
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,nodev,size=512m"}
        or host.get("PidMode")
        or host.get("IpcMode") != "private"
    ):
        raise ValueError("Motion container filesystem policy changed")
    return item


def create(root, saved):
    folder = directory(root, saved["request"]["run_id"])
    with (folder / "container.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (folder / "cancel.json").exists():
            raise InterruptedError("Motion render canceled before container creation")
        receipt = folder / "container.json"
        if receipt.exists():
            raise ValueError("A motion container dispatch is never replayed")
        name, labels = identity(saved)
        save(receipt, {"state": "creating", "id": None})
        args = ["create", "--pull", "never", "--name", name]
        for key, value in labels.items():
            args += ["--label", key + "=" + value]
        mount = io.StringIO()
        csv.writer(mount, lineterminator="").writerow(
            ["type=bind", "src=" + str(folder / "work"), "dst=/work"]
        )
        args += [
            "--init",
            "--network",
            "none",
            "--runtime",
            "runc",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            saved["user"],
            "--pids-limit",
            "512",
            "--memory",
            "4g",
            "--memory-swap",
            "4g",
            "--cpus",
            "4",
            "--cgroupns",
            "private",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=512m",
            "--mount",
            mount.getvalue(),
            "--env",
            "AI_STATION_RUN_ID=" + saved["request"]["run_id"],
            "--env",
            "AI_STATION_MOTION_REQUEST=" + saved["digest"],
            saved["image"],
        ]
        cid = docker(args, bound=saved["connection"])
        item = inspect_owned(root, saved, cid)
        if item is None:
            raise ValueError("Motion container creation could not be confirmed")
        save(receipt, {"state": "created", "id": item["Id"]})
        return item["Id"]


def stop(root, run_id, *, cancel=False):
    folder = directory(root, run_id)
    if cancel:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (folder / "container.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cancel:
            save(folder / "cancel.json", {"requested": True})
            if not (folder / "request.json").exists():
                return True
        saved = load(root, run_id)
        path = folder / "container.json"
        if not path.exists():
            return True
        if path.is_symlink() or path.stat().st_size > 4096:
            raise ValueError("Motion container receipt changed")
        receipt = json.loads(path.read_text())
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"state", "id"}
            or receipt.get("state") not in {"creating", "created", "removed"}
            or (
                receipt.get("id") is not None
                and (not isinstance(receipt["id"], str) or not CID.fullmatch(receipt["id"]))
            )
            or (receipt["state"] != "creating" and receipt["id"] is None)
        ):
            raise ValueError("Motion container receipt is invalid")
        if receipt["state"] == "removed":
            return True
        item = inspect_owned(root, saved, receipt.get("id"))
        if item:
            # Only this exact owned ID can be removed; never use a name-wide,
            # image-wide or daemon-wide cleanup command.
            docker(["rm", "--force", item["Id"]], bound=saved["connection"])
            save(path, {"state": "removed", "id": item["Id"]})
            return True
        if receipt.get("id"):
            save(path, {"state": "removed", "id": receipt["id"]})
            return True
        # A lost create response can still hide a late daemon-side side effect.
        # Keep ownership/resource reservations and re-inspect, never re-dispatch.
        return False


def cleanup(root, run_id):
    """Only dead-process inspection calls this; live publication keeps staging."""
    if not stop(root, run_id):
        return False
    work = directory(root, run_id) / "work"
    if work.resolve() != work or work.is_symlink():
        raise ValueError("Motion staging ownership changed")
    if work.exists():
        shutil.rmtree(work)
    return True
