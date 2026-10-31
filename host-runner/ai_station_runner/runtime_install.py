"""Typed, journaled preparation of one reviewed runtime image on local Docker."""

import fcntl
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import ConfigDict, Field, model_validator

from ai_station_runner import llama_runtime, runtime_setup
from ai_station_runner.config import get_settings
from ai_station_runner.processes import ProcessNotOwned

router = APIRouter(prefix="/v1/setup/runtimes", tags=["runtime preparation"])
INSTALLATION_QUALIFIED = True
PERMISSIONS = {"manage_models", "network_read", "workspace_write"}


class Prepare(runtime_setup.RuntimeSelection):
    run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: datetime
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)

    @model_validator(mode="after")
    def timezone(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Use an absolute timezone-aware runtime preparation deadline")
        return self


class Cancel(runtime_setup.RuntimeSelection):
    model_config = ConfigDict(extra="forbid")
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)


def permitted(body):
    if set(body.permissions) != PERMISSIONS:
        raise HTTPException(403, "Runtime preparation requires model, network and workspace permissions")


def base():
    folder = get_settings().host_data_dir().resolve()
    for part in ("runtime", "setup"):
        folder = folder / part
        if folder.is_symlink():
            raise HTTPException(409, "Runtime setup storage cannot be a symlink")
        folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def owned_file(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o022
    ):
        os.close(fd)
        raise HTTPException(409, "Runtime metadata requires an owned regular file")
    return fd


def load_json(path, limit=256 * 1024):
    try:
        with os.fdopen(owned_file(path, os.O_RDONLY), "r") as handle:
            if os.fstat(handle.fileno()).st_size > limit:
                raise HTTPException(409, "Runtime metadata exceeds its bound")
            value = json.load(handle)
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise HTTPException(409, "Runtime metadata is invalid")
    return value


def atomic_json(folder, filename, value):
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=folder)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, folder / filename)
        directory_fd = os.open(folder, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def directory(identity):
    folder = base() / str(UUID(str(identity)))
    if folder.is_symlink():
        raise HTTPException(409, "Runtime preparation cannot cross a symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


@contextmanager
def locked():
    with os.fdopen(owned_file(base() / "manager.lock", os.O_RDWR | os.O_CREAT), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read(identity):
    return load_json(directory(identity) / "manifest.json")


def save(identity, record):
    atomic_json(directory(identity), "manifest.json", record)


def daemon():
    # Freeze the effective CLI context into one local Unix endpoint. Never turn
    # a caller-supplied address into raw Docker access or operate a remote host.
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = os.environ.get("DOCKER_HOST") if not context else None
    if not endpoint:
        endpoint = llama_runtime.docker(
            "context",
            "inspect",
            *([context] if context else []),
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        )
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise HTTPException(409, "Runtime preparation requires a local Docker Unix socket")
    path = Path(endpoint.removeprefix("unix://"))
    if any(part == ".." for part in path.parts) or "\x00" in str(path):
        raise HTTPException(409, "The configured Docker socket is invalid")
    socket = str(path.resolve())
    with client(socket) as api:
        info = api.get("/info")
        info.raise_for_status()
        version = api.get("/version")
        version.raise_for_status()
    info, version = info.json(), version.json()
    if (
        not isinstance(info.get("ID"), str)
        or not info["ID"]
        or not re.fullmatch(r"1\.[0-9]{1,3}", version.get("ApiVersion", ""))
    ):
        raise HTTPException(503, "Local Docker identity/version could not be confirmed")
    return {
        "socket": socket,
        "id": info["ID"],
        "api_version": version["ApiVersion"],
        "data_root": info.get("DockerRootDir"),
    }


def client(socket):
    return httpx.Client(
        transport=httpx.HTTPTransport(uds=socket),
        base_url="http://docker",
        timeout=httpx.Timeout(30, connect=5),
        trust_env=False,
    )


def inspect_image(api, frozen):
    from urllib.parse import quote

    response = api.get("/images/" + quote(frozen["image_reference"], safe="") + "/json")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    value = response.json()
    return runtime_setup.validate_image(value, frozen["image_reference"])


def process_manager():
    from ai_station_runner.app import manager

    return manager()


def snapshot(identity, record, *, stdout_offset=0, stderr_offset=0):
    process = None
    if record.get("dispatch_started"):
        try:
            process = process_manager().inspect(
                str(identity), stdout_offset=stdout_offset, stderr_offset=stderr_offset
            )
            if process["executor"] != "runtime_setup":
                raise HTTPException(409, "Runtime preparation process ownership changed")
        except ProcessNotOwned:
            record["requires_inspection"] = True
    alive = bool(process and (process["alive"] or process.get("completion_pending")))
    status = "running" if alive else "canceled" if record.get("cancel_requested") else "interrupted"
    image = record.get("verified_image")
    if not alive and not record.get("cancel_requested") and not record.get("requires_inspection"):
        if process and process.get("exit_code") is not None:
            status = "failed"
        # A Runner restart can lose waitpid's exit code. A verified native job
        # receipt plus a fresh exact-image inspection reconciles success safely.
        result_path = directory(identity) / "result.json"
        result = None
        if (
            process
            and result_path.exists()
            and not result_path.is_symlink()
            and result_path.stat().st_size <= 8192
        ):
            result = load_json(result_path, 8192)
        if image or result and result.get("request_hash") == record["request_hash"]:
            with client(record["daemon"]["socket"]) as api:
                info = api.get("/info")
                info.raise_for_status()
                if info.json().get("ID") != record["daemon"]["id"]:
                    raise HTTPException(409, "Docker daemon identity changed during runtime preparation")
                current = inspect_image(api, record["recipe"])
            if current is not None and current == (image or result.get("image")):
                status = "succeeded"
                image = current
            else:
                image = None
                status = "interrupted"
    return {
        "run_id": str(identity),
        "runner_id": get_settings().runner_id,
        "status": status,
        "alive": alive,
        "requires_inspection": record.get("requires_inspection", False),
        "cancel_requested": record.get("cancel_requested", False),
        "image": image,
        "manifest_sha256": record.get("manifest_sha256"),
        "process": process,
    }


@router.get("")
def catalog():
    selection = runtime_setup.RuntimeSelection(profile="llamacpp-cuda-linux-amd64-v1")
    result = runtime_setup.inspect_image(selection)
    result["configured_image"] = {"present": False, "status": "unknown"}
    result["usable_image"] = bool(result["image"]["present"])
    result["storage"] = None
    try:
        configured = llama_runtime.docker(
            "image", "inspect", get_settings().llama_image, "--format", "{{.Id}}", missing_ok=True
        )
        present = isinstance(configured, str) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", configured))
        result["configured_image"] = {"present": present, "status": "available" if present else "unavailable"}
        result["usable_image"] = result["usable_image"] or present
        target = daemon()
        try:
            free = shutil.disk_usage(target["data_root"]).free
            result["storage"] = {"free_bytes": free, "required_bytes": result["recipe"]["minimum_free_bytes"]}
        except (OSError, TypeError):
            free = None
        enough = free is not None and free >= result["recipe"]["minimum_free_bytes"]
        result["installation_available"] = bool(
            INSTALLATION_QUALIFIED and result["platform_supported"] and (result["image"]["present"] or enough)
        )
        if INSTALLATION_QUALIFIED:
            result["installation_notice"] = (
                ""
                if result["installation_available"]
                else "Check the supported platform and free Docker storage before preparing this runtime"
            )
    except (HTTPException, httpx.HTTPError, OSError, ValueError):
        result["installation_notice"] = "Local Docker runtime inspection could not be confirmed"
    return result


@router.get("/{identity}")
def inspect(
    identity: UUID,
    stdout_offset: int = Query(0, ge=0, le=2**63 - 1),
    stderr_offset: int = Query(0, ge=0, le=2**63 - 1),
):
    with locked():
        record = read(identity)
        if record is None:
            raise HTTPException(404, "Runtime preparation was not found")
        return snapshot(identity, record, stdout_offset=stdout_offset, stderr_offset=stderr_offset)


@router.post("/prepare")
def prepare(body: Prepare):
    permitted(body)
    identity = str(body.run_id)
    value = body.model_dump(mode="json")
    request_hash = runtime_setup.fingerprint(value)
    with locked():
        previous = read(identity)
        if previous is not None:
            if previous.get("cancel_requested") and previous.get("request_hash") is None:
                return snapshot(identity, previous)
            if previous.get("request_hash") != request_hash:
                raise HTTPException(409, "Runtime preparation identity is immutable")
            return snapshot(identity, previous)
        frozen = runtime_setup.recipe(body)
        if runtime_setup.fingerprint(frozen) != body.manifest_sha256:
            raise HTTPException(409, "Runtime recipe changed; review it before preparing")
        if not runtime_setup.platform_supported():
            raise HTTPException(409, "This runtime profile requires Linux x86-64")
        if not 0 < body.deadline_at.timestamp() - time.time() <= 4 * 3600:
            raise HTTPException(422, "Runtime deadline must be within the next four hours")
        target = daemon()
        with client(target["socket"]) as api:
            image = inspect_image(api, frozen)
        record = {
            "request": value,
            "request_hash": request_hash,
            "recipe": frozen,
            "manifest_sha256": body.manifest_sha256,
            "daemon": target,
            "dispatch_started": False,
            "cancel_requested": False,
            "verified_image": image,
        }
        if image is not None:
            save(identity, record)
            return snapshot(identity, record)
        active = base() / "active.json"
        if active.is_symlink():
            raise HTTPException(409, "Runtime preparation ownership cannot cross symlinks")
        if active.exists():
            owner = (load_json(active) or {}).get(body.profile)
            if owner:
                old = read(owner)
                if old:
                    observation = snapshot(owner, old)
                    if observation["alive"] or observation["requires_inspection"]:
                        raise HTTPException(
                            409, "Another owned runtime preparation is active or requires inspection"
                        )
        try:
            free = shutil.disk_usage(target["data_root"]).free
        except (OSError, TypeError):
            raise HTTPException(409, "Free Docker storage could not be confirmed") from None
        if free < frozen["minimum_free_bytes"]:
            raise HTTPException(409, "More free Docker storage is needed for runtime preparation")
        ownership = load_json(active) or {}
        ownership[body.profile] = identity
        atomic_json(base(), "active.json", ownership)
        # Persist intent before launch. An uncertain launch is inspected, never
        # blindly replayed; ProcessManager separately persists PID/group identity.
        record["dispatch_started"] = True
        save(identity, record)
        process_manager().start(
            run_id=identity,
            argv=[sys.executable, "-m", "ai_station_runner.runtime_install_job", identity],
            cwd=get_settings().host_data_dir().resolve(),
            executor="runtime_setup",
            env={**os.environ, "AI_STATION_DATA_HOST_PATH": str(get_settings().host_data_dir().resolve())},
            deadline_at=body.deadline_at.timestamp(),
        )
        return snapshot(identity, record)


@router.post("/{identity}/cancel")
def cancel(identity: UUID, body: Cancel):
    permitted(body)
    with locked():
        record = read(identity) or {"request_hash": None, "dispatch_started": False}
        record["cancel_requested"] = True
        save(identity, record)
        if record.get("dispatch_started"):
            try:
                info = process_manager().inspect(str(identity))
                if info["executor"] != "runtime_setup":
                    raise HTTPException(409, "Runtime preparation process ownership changed")
                process_manager().cancel(str(identity))
            except ProcessNotOwned:
                record["requires_inspection"] = True
                save(identity, record)
        return snapshot(identity, record)
