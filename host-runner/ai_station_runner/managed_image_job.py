"""Fixed image-container lifecycle; new dispatch remains qualification gated.

A Docker client's PID is never evidence that its container has stopped. Journals,
exact daemon/container identity and an in-container deadline survive that client.
"""

import fcntl
import hashlib
import io
import json
import math
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner import runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.managed_image_command import ImageCommand, argv
from ai_station_runner.security import resolve_child
from ai_station_runner.speech_environment import fingerprint
from ai_station_runner.telemetry import collect

PROFILE = "qwen-image21-cuda-linux-amd64-v1"
QUALIFIED = False
PERMISSIONS = {"filesystem_read", "workspace_write"}
LIMIT = 8 * 1024**2
RAM = 12 * 1024**3
GUARD_PATH = Path(__file__).with_name("image_deadline.sh").resolve()
GUARD = GUARD_PATH.read_bytes()


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    relative_path: str = Field(pattern=r"^artifacts/[A-Za-z0-9_./-]{1,200}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0, le=25 * 1024**2)


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    profile: Literal["qwen-image21-cuda-linux-amd64-v1"]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    command: ImageCommand
    references: list[Reference] = Field(default_factory=list, max_length=8)
    gpus: list[StrictInt] = Field(min_length=1, max_length=2)
    deadline_at: datetime
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def valid(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Use an absolute timezone-aware image deadline")
        if len(self.references) != self.command.reference_count:
            raise ValueError("The image command must bind all references")
        if len(set(self.gpus)) != len(self.gpus) or any(value < 0 for value in self.gpus):
            raise ValueError("Allocate distinct discovered GPUs")
        return self


def recipe():
    path = Path(__file__).with_name("recipes") / (PROFILE + ".json")
    return json.loads(path.read_text())


def owns(identity):
    """Probe the journal without creating storage for unrelated process IDs."""
    current = get_settings().host_data_dir().resolve()
    for index, part in enumerate(("runtime", "image-jobs", str(UUID(str(identity))), "image.json")):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return False
        if (
            info.st_uid != os.geteuid()
            or stat.S_ISLNK(info.st_mode)
            or (
                index < 3
                and (not stat.S_ISDIR(info.st_mode) or info.st_mode & (0o002 if index == 0 else 0o022))
            )
            or (index == 3 and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))
        ):
            raise HTTPException(409, "Image journal ownership requires inspection")
    return True


def folder(identity):
    current = get_settings().host_data_dir().resolve()
    for index, part in enumerate(("runtime", "image-jobs", str(UUID(str(identity))))):
        current /= part
        if current.is_symlink():
            raise HTTPException(409, "Image journals cannot cross symlinks")
        current.mkdir(mode=0o700, exist_ok=True)
        info = current.stat()
        if info.st_uid != os.geteuid() or info.st_mode & (0o002 if index == 0 else 0o022):
            raise HTTPException(409, "Image journals require owned private storage")
    return current


@contextmanager
def locked(identity):
    with os.fdopen(
        runtime_install.owned_file(folder(identity) / "manager.lock", os.O_RDWR | os.O_CREAT)
    ) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def read(identity):
    return runtime_install.load_json(folder(identity) / "image.json")


def save(identity, record):
    runtime_install.atomic_json(folder(identity), "image.json", record)


def write_bytes(path, data):
    if path.is_symlink():
        raise HTTPException(409, "Image metadata cannot replace a symlink")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def api_for(record):
    target = runtime_install.daemon()
    if any(record["daemon"].get(key) != target.get(key) for key in ("socket", "id", "api_version")):
        raise HTTPException(409, "The configured image job Docker context changed")
    with runtime_install.client(target["socket"]) as api:
        response = api.get("/info")
        response.raise_for_status()
        if response.json().get("ID") != record["daemon"]["id"]:
            raise HTTPException(409, "The image job Docker daemon changed")
        yield api


def path(record, suffix="/json"):
    identity = record.get("container_id") or record["name"]
    return "/v" + record["daemon"]["api_version"] + "/containers/" + identity + suffix


def labels(body):
    root = get_settings().host_data_dir().resolve()
    return {
        "ai-station.image.station": hashlib.sha256(str(root).encode()).hexdigest(),
        "ai-station.image.request": fingerprint(body.model_dump(mode="json")),
    }


def validate_record(identity, record):
    try:
        body = Start.model_validate(record["request"])
        if record.get("container_id") is not None and not re.fullmatch(
            r"[a-f0-9]{64}", record["container_id"]
        ):
            raise ValueError("Invalid owned container ID")
        if (
            str(body.run_id) != str(identity)
            or record["request_hash"] != fingerprint(body.model_dump(mode="json"))
            or record["name"] != "ai-station-image-" + str(body.run_id)
            or record["create"]["Labels"] != labels(body)
        ):
            raise ValueError("The saved image identity changed")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(409, "Image journal identity requires inspection") from None
    return body


def inspect_container(api, record):
    body = validate_record(record.get("request", {}).get("run_id"), record)
    response = api.get(path(record))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    value = response.json()
    expected = record["create"]
    actual = value.get("Config") or {}
    host = value.get("HostConfig") or {}
    mounts = sorted((m.get("Source"), m.get("Destination"), m.get("RW")) for m in value.get("Mounts", []))
    wanted = sorted((m["Source"], m["Target"], not m["ReadOnly"]) for m in expected["HostConfig"]["Mounts"])
    if (
        not re.fullmatch(r"[a-f0-9]{64}", value.get("Id", ""))
        or record.get("container_id") not in {None, value["Id"]}
        or value.get("Image") != record["image_id"]
        or any((actual.get("Labels") or {}).get(k) != v for k, v in labels(body).items())
        or actual.get("User") != expected["User"]
        or actual.get("Entrypoint") != expected["Entrypoint"]
        or actual.get("Cmd") != expected["Cmd"]
        or mounts != wanted
        or not set(expected["Env"]).issubset(set(actual.get("Env") or []))
        or any(
            host.get(k) != expected["HostConfig"][k]
            for k in (
                "NetworkMode",
                "ReadonlyRootfs",
                "Privileged",
                "Memory",
                "MemorySwap",
                "PidsLimit",
                "CapDrop",
                "DeviceRequests",
                "SecurityOpt",
                "Init",
                "LogConfig",
                "CgroupnsMode",
                "Ulimits",
            )
        )
    ):
        raise HTTPException(409, "Image container ownership or isolation changed; inspect it")
    return value


def mount_observations(config):
    result = {}
    for mount in config["HostConfig"]["Mounts"]:
        source = Path(mount["Source"])
        info = source.lstat()
        directory = mount["Target"] == "/output"
        if (
            source.resolve() != source
            or info.st_uid != os.geteuid()
            or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
            or info.st_mode & (0o002 if source == GUARD_PATH else 0o022 if directory else 0o222)
            or not directory
            and info.st_nlink != 1
        ):
            raise HTTPException(409, "Image job mounts changed or crossed a filesystem boundary")
        result[str(source)] = (
            [info.st_dev, info.st_ino]
            if directory
            else [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size]
        )
    return result


def check_mounts(record):
    if mount_observations(record["create"]) != record["mount_observations"]:
        raise HTTPException(409, "Image job sources changed before container start")


def files(frozen):
    root = get_settings().host_data_dir().resolve()
    result = {}
    for item in frozen["files"]:
        digest = item["sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid fixed image object")
        relative = "models/store/" + digest
        candidate = root / relative
        if resolve_child(root, relative) != candidate:
            raise HTTPException(409, "Image objects cannot cross symlinks")
        info = candidate.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != item["size_bytes"]
        ):
            raise HTTPException(409, "The verified image bundle is incomplete or changed")
        result[item["role"]] = candidate
    if set(result) != {"diffusion", "text_encoder", "vision_projector", "vae"}:
        raise ValueError("The fixed image bundle must bind every companion")
    return result


def copy_references(body, work):
    root = get_settings().host_data_dir().resolve()
    copied = []
    for index, reference in enumerate(body.references):
        source = root / reference.relative_path
        if resolve_child(root, reference.relative_path) != source:
            raise HTTPException(409, "Image references cannot cross symlinks")
        target = work / f"input-{index}.png"
        with os.fdopen(runtime_install.owned_file(source, os.O_RDONLY), "rb") as f:
            before = os.fstat(f.fileno())
            data = f.read(reference.size_bytes + 1)
            after = os.fstat(f.fileno())
        if (
            len(data) != reference.size_bytes
            or before.st_size != len(data)
            or (before.st_ino, before.st_mtime_ns, before.st_size)
            != (after.st_ino, after.st_mtime_ns, after.st_size)
            or hashlib.sha256(data).hexdigest() != reference.sha256
        ):
            raise HTTPException(409, "The selected image reference changed")
        write_bytes(target, data)
        target.chmod(0o400)
        copied.append(target)
    return copied


def create_config(body, work, models, image_id, devices, *, prepare_assets=True):
    if (
        GUARD_PATH.is_relative_to(get_settings().host_data_dir().resolve())
        or GUARD_PATH.read_bytes() != GUARD
    ):
        raise HTTPException(409, "Image deadline code must stay outside shared application storage")
    refs = (
        copy_references(body, work)
        if prepare_assets
        else [work / f"input-{i}.png" for i in range(len(body.references))]
    )
    guard = GUARD_PATH
    output = work / "output"
    if prepare_assets:
        output.mkdir(mode=0o700, exist_ok=False)
    mounts = [
        dict(Type="bind", Source=str(guard), Target="/station/deadline.sh", ReadOnly=True),
        dict(Type="bind", Source=str(output), Target="/output", ReadOnly=False),
    ]
    aliases = {
        "diffusion": "diffusion.gguf",
        "text_encoder": "text.gguf",
        "vae": "vae.safetensors",
        "vision_projector": "vision.gguf",
    }
    mounts.extend(
        dict(Type="bind", Source=str(p), Target="/models/" + aliases[role], ReadOnly=True)
        for role, p in models.items()
    )
    mounts.extend(
        dict(Type="bind", Source=str(p), Target=f"/inputs/{i}.png", ReadOnly=True) for i, p in enumerate(refs)
    )
    return dict(
        Image=image_id,
        User=f"{os.getuid()}:{os.getgid()}",
        WorkingDir="/output",
        Tty=False,
        Entrypoint=["/bin/sh", "/station/deadline.sh"],
        Cmd=[str(math.floor(body.deadline_at.timestamp())), *argv(body.command, gpu_count=len(devices))],
        Env=[
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "NVIDIA_VISIBLE_DEVICES=" + ",".join(devices),
            "CUDA_VISIBLE_DEVICES=" + ",".join(devices),
        ],
        Labels=labels(body),
        HostConfig=dict(
            NetworkMode="none",
            CgroupnsMode="private",
            Ulimits=[dict(Name="core", Soft=0, Hard=0)],
            ReadonlyRootfs=True,
            Privileged=False,
            CapDrop=["ALL"],
            SecurityOpt=["no-new-privileges"],
            PidsLimit=512,
            Memory=RAM,
            MemorySwap=RAM,
            Init=True,
            DeviceRequests=[
                dict(Driver="nvidia", Count=0, DeviceIDs=devices, Capabilities=[["gpu"]], Options={})
            ],
            Mounts=mounts,
            LogConfig={"Type": "json-file", "Config": {"max-size": "16m", "max-file": "1"}},
        ),
    )


def validate_dispatch(api, identity, record):
    body = validate_record(identity, record)
    frozen = recipe()
    if not QUALIFIED or body.manifest_sha256 != fingerprint(frozen):
        raise HTTPException(409, "This image recipe cannot dispatch new work")
    image = runtime_install.inspect_image(api, frozen["runtime"])
    hardware = collect(get_settings().host_data_dir())
    devices = {int(v["index"]): v["uuid"] for v in hardware.get("gpus", [])}
    if image is None or any(v not in devices for v in body.gpus):
        raise HTTPException(409, "Image runtime or allocated GPUs changed")
    expected = create_config(
        body,
        folder(identity),
        files(frozen),
        image["id"],
        [devices[v] for v in body.gpus],
        prepare_assets=False,
    )
    if expected != record["create"] or record["image_id"] != image["id"]:
        raise HTTPException(409, "Image container policy changed before dispatch")
    check_mounts(record)


def log_bytes(api, record):
    streams = {1: bytearray(), 2: bytearray()}
    pending = b""
    limited = False
    with api.stream(
        "GET", path(record, "/logs"), params={"stdout": "true", "stderr": "true", "follow": "false"}
    ) as response:
        response.raise_for_status()
        consumed = 0
        for chunk in response.iter_bytes(chunk_size=65536):
            consumed += len(chunk)
            if consumed > 20 * 1024**2:
                limited = True
                break
            pending += chunk
            while len(pending) >= 8:
                kind, length = pending[0], int.from_bytes(pending[4:8], "big")
                if kind not in streams or pending[1:4] != b"\x00\x00\x00" or length > 1024**2:
                    raise HTTPException(409, "Image container logs exceeded their framing bound")
                if len(pending) < 8 + length:
                    break
                data, pending = pending[8 : 8 + length], pending[8 + length :]
                space = LIMIT - len(streams[kind])
                streams[kind].extend(data[:space])
                limited = limited or len(data) > space
        if pending and not limited:
            raise HTTPException(409, "Image container logs are incomplete")
    return bytes(streams[1]), bytes(streams[2]), limited


def publish(identity, record):
    work = folder(identity)
    root = get_settings().host_data_dir().resolve()
    relative = f"artifacts/{identity[:2]}/{identity[2:4]}/{identity}.png"
    if published := record.get("output"):
        if published.get("relative_path") != relative:
            raise HTTPException(409, "The published image receipt changed")
        target = resolve_child(root, relative)
        if target != root / relative:
            raise HTTPException(409, "The published image cannot cross a symlink")
        with os.fdopen(runtime_install.owned_file(target, os.O_RDONLY), "rb") as f:
            data = f.read(25 * 1024**2 + 1)
        if len(data) != published["size_bytes"] or hashlib.sha256(data).hexdigest() != published["sha256"]:
            raise HTTPException(409, "The published image is unavailable or changed")
        return published
    source = work / "output/result.png"
    if source.resolve() != source:
        raise HTTPException(409, "Image output cannot cross a symlink")
    command = record["request"]["command"]
    with os.fdopen(runtime_install.owned_file(source, os.O_RDONLY), "rb") as f:
        if os.fstat(f.fileno()).st_size > 25 * 1024**2:
            raise HTTPException(409, "Image output exceeded its byte budget")
        data = f.read(25 * 1024**2 + 1)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != (command["width"], command["height"]):
            raise HTTPException(409, "Image output does not match its frozen dimensions")
        image.load()
    root = get_settings().host_data_dir().resolve()
    relative = f"artifacts/{identity[:2]}/{identity[2:4]}/{identity}.png"
    target = resolve_child(root, relative)
    if target != root / relative:
        raise HTTPException(409, "Image output cannot cross a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    if target.exists():
        with os.fdopen(runtime_install.owned_file(target, os.O_RDONLY), "rb") as f:
            old = f.read(len(data) + 1)
        if old != data:
            raise HTTPException(409, "An existing image output cannot be overwritten")
    else:
        fd, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.link(temporary, target)
            descriptor = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"relative_path": relative, "sha256": digest, "size_bytes": len(data)}


def canceled_result(identity):
    return dict(
        run_id=str(identity),
        runner_id=get_settings().runner_id,
        executor="photo_pipe",
        execution_target="container",
        status="canceled",
        alive=False,
        exit_code=None,
        pid=None,
        process_group_id=None,
        stdout="",
        stderr="",
        stdout_offset=0,
        stderr_offset=0,
        stdout_more=False,
        stderr_more=False,
        stdout_log="",
        stderr_log="",
    )


def snapshot(api, identity, record, *, stdout_offset=0, stderr_offset=0):
    if any(type(v) is not int or v < 0 for v in (stdout_offset, stderr_offset)):
        raise HTTPException(422, "Image log offsets must be nonnegative integers")
    item = inspect_container(api, record)
    if item is None:
        if record.get("cancel_requested") and record.get("removed_after_cancel"):
            return canceled_result(identity)
        raise HTTPException(409, "The owned image container is missing; inspect before retrying")
    state = item["State"]
    if state.get("Status") not in {"created", "running", "exited", "restarting", "paused"}:
        raise HTTPException(409, "The image container state requires inspection")
    alive = bool(state.get("Running") or state.get("Status") in {"restarting", "paused"})
    log_failure = False
    try:
        stdout, stderr, limited = log_bytes(api, record)
    except (HTTPException, httpx.HTTPError):
        # Log availability cannot invalidate a separately confirmed stop, nor
        # turn an unobservable successful execution into a published artifact.
        stdout = stderr = b""
        limited = False
        log_failure = True
    record["logs_unavailable"] = log_failure
    result = dict(
        run_id=str(identity),
        runner_id=get_settings().runner_id,
        executor="photo_pipe",
        execution_target="container",
        pid=state.get("Pid") or None,
        process_group_id=None,
        alive=alive,
        completion_pending=state.get("Status") == "created"
        and bool(record.get("start_attempted"))
        and not record.get("cancel_requested"),
        status="running"
        if alive
        else "canceled"
        if record.get("cancel_requested")
        else "interrupted"
        if state.get("Status") == "created"
        else "exited",
        exit_code=state.get("ExitCode") if state.get("Status") == "exited" else None,
        stdout_log=str(
            (folder(identity) / "stdout.log").relative_to(get_settings().host_data_dir().resolve())
        ),
        stderr_log=str(
            (folder(identity) / "stderr.log").relative_to(get_settings().host_data_dir().resolve())
        ),
    )
    for stream, data, offset in (("stdout", stdout, stdout_offset), ("stderr", stderr, stderr_offset)):
        saved = folder(identity) / (stream + ".log")
        if saved.exists():
            with os.fdopen(runtime_install.owned_file(saved, os.O_RDONLY), "rb") as f:
                old = f.read(LIMIT + 1)
            if log_failure:
                data = old
            elif not data.startswith(old):
                limited = True
                data = old
        write_bytes(saved, data)
        chunk = data[offset : offset + 65536]
        result.update(
            {
                stream: chunk.decode(errors="replace"),
                stream + "_offset": min(offset + len(chunk), len(data)),
                stream + "_more": offset + len(chunk) < len(data),
            }
        )
    limited = limited or record.get("logs_limited", False)
    record["logs_limited"] = limited
    if not alive and result["exit_code"] == 0 and not record.get("cancel_requested"):
        if limited or log_failure or record.get("output_error"):
            result["exit_code"] = 1
            result["stderr_tail"] = (
                record.get("output_error")
                or "Image completion logs were unavailable or exceeded their byte budget"
            )
            record["output_error"] = result["stderr_tail"]
        else:
            try:
                record["output"] = publish(str(identity), record)
            except (HTTPException, OSError, ValueError):
                result["exit_code"] = 1
                result["stderr_tail"] = (
                    "Image output was missing, invalid or changed; no result was published."
                )
                record["output_error"] = result["stderr_tail"]
        record["completed_at"] = datetime.now(UTC).isoformat()
    save(identity, record)
    if record.get("output") and result["exit_code"] == 0 and not record.get("cancel_requested"):
        # The final receipt is durable before retiring the private duplicate.
        # Reinspection verifies the published file; deletion cannot resurrect it.
        source = folder(identity) / "output/result.png"
        if source.resolve() != source:
            raise HTTPException(409, "Image output cannot cross a symlink")
        source.unlink(missing_ok=True)
    return result


def start(body: Start):
    if set(body.permissions) != PERMISSIONS:
        raise HTTPException(403, "Image read/write permissions are required")
    identity = str(body.run_id)
    request = body.model_dump(mode="json")
    digest = fingerprint(request)
    with locked(identity):
        record = read(identity)
        if record:
            if record.get("request_hash") not in {None, digest}:
                raise HTTPException(409, "Image operation identity is immutable")
            if record.get("cancel_requested") and not record.get("create"):
                return canceled_result(identity)
        else:
            frozen = recipe()
            if not QUALIFIED or body.manifest_sha256 != fingerprint(frozen):
                raise HTTPException(409, "This image profile is not qualified or its manifest changed")
            if not 1 < body.deadline_at.timestamp() - time.time() <= 3600:
                raise HTTPException(422, "Use an image deadline within one hour")
            models = files(frozen)
            hardware = collect(get_settings().host_data_dir())
            gpus = {int(v["index"]): v["uuid"] for v in hardware.get("gpus", [])}
            if any(v not in gpus for v in body.gpus):
                raise HTTPException(422, "Choose discovered allocated GPUs")
            record = {
                "request": request,
                "request_hash": digest,
                "daemon": runtime_install.daemon(),
                "name": "ai-station-image-" + identity,
                "cancel_requested": False,
            }
            with api_for(record) as api:
                image = runtime_install.inspect_image(api, frozen["runtime"])
            if image is None:
                raise HTTPException(409, "Prepare the reviewed image runtime before generating")
            record["image_id"] = image["id"]
            record["create"] = create_config(
                body, folder(identity), models, image["id"], [gpus[v] for v in body.gpus]
            )
            record["mount_observations"] = mount_observations(record["create"])
            save(identity, record)  # Durable before any container create/start request.
        with api_for(record) as api:
            item = inspect_container(api, record)
            if item is None:
                if record.get("cancel_requested") and record.get("removed_after_cancel"):
                    return canceled_result(identity)
                if record.get("container_id") or record.get("start_attempted"):
                    raise HTTPException(409, "An earlier image container disappeared; inspect it")
                validate_dispatch(api, identity, record)
                response = api.post(
                    "/v" + record["daemon"]["api_version"] + "/containers/create",
                    params={"name": record["name"]},
                    json=record["create"],
                )
                response.raise_for_status()
                item = inspect_container(api, record)
                if item is None:
                    raise HTTPException(409, "Image container creation could not be confirmed")
            record["container_id"] = item["Id"]
            save(identity, record)
            if not record.get("start_attempted") and not record.get("cancel_requested"):
                validate_dispatch(api, identity, record)
                record["start_attempted"] = True
                save(identity, record)
                response = api.post(path(record, "/start"))
                response.raise_for_status()
            return snapshot(api, identity, record)


def inspect(identity, *, stdout_offset=0, stderr_offset=0):
    if not owns(identity):
        raise HTTPException(404, "Image operation is not owned by this Runner")
    with locked(identity):
        record = read(identity)
        if not record:
            raise HTTPException(404, "Image operation is not owned by this Runner")
        if record.get("cancel_requested") and not record.get("create"):
            return canceled_result(identity)
        validate_record(identity, record)
        with api_for(record) as api:
            return snapshot(api, identity, record, stdout_offset=stdout_offset, stderr_offset=stderr_offset)


def cancel(identity, *, permissions):
    if set(permissions) != PERMISSIONS:
        raise HTTPException(403, "Image read/write permissions are required")
    with locked(identity):
        record = read(identity) or {"request_hash": None}
        record["cancel_requested"] = True
        save(identity, record)  # A late start can never resurrect this operation.
        if not record.get("create"):
            return canceled_result(identity)
        validate_record(identity, record)
        with api_for(record) as api:
            item = inspect_container(api, record)
            if item is None:
                if record.get("removed_after_cancel"):
                    return canceled_result(identity)
                raise HTTPException(409, "Missing image container requires cleanup inspection")
            if item["State"].get("Status") == "created" and record.get("start_attempted"):
                # A timed-out Docker start may still be queued in the daemon.
                # Deletion of this exact owned ID fences that late request;
                # observing "created" alone cannot prove a safe cancellation.
                response = api.delete(path(record, ""), params={"force": "true", "v": "false"})
                response.raise_for_status()
                if inspect_container(api, record) is not None:
                    raise HTTPException(409, "Image start cancellation is still unconfirmed")
                record["removed_after_cancel"] = True
                save(identity, record)
                return canceled_result(identity)
            if item["State"].get("Running"):
                try:
                    api.post(path(record, "/stop"), params={"t": 3}).raise_for_status()
                except Exception:
                    current = inspect_container(api, record)
                    if current and current["State"].get("Running"):
                        api.post(path(record, "/kill"), params={"signal": "KILL"}).raise_for_status()
            return snapshot(api, identity, record)
