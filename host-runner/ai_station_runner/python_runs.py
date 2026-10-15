"""Typed Python dispatch with frozen files and exact owned-container identity."""

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_station_runner.browser_runs import CONTAINER, IMAGE, save
from ai_station_runner.browser_runs import docker as browser_docker
from ai_station_runner.config import get_settings
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.python_protocol import MAX_INPUT, MAX_INPUT_TOTAL, MAX_SCRIPT
from ai_station_runner.validation_environment import component_directory, relative_directory
from ai_station_runner.worktrees import inspect_worktree, owned_path

PERMISSIONS = {"filesystem_read", "workspace_write", "python_execute"}
ENTRYPOINT = ["python", "-u", "/opt/ai-station/python_container.py"]
DIGEST = r"^[a-f0-9]{64}$"


class PythonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID
    suffix: str = Field(pattern=r"^\.(csv|xlsx|json|txt)$")
    sha256: str = Field(pattern=DIGEST)
    size_bytes: int = Field(ge=0, le=MAX_INPUT, strict=True)

    @property
    def filename(self):
        return f"{self.artifact_id}{self.suffix}"

    @property
    def relative_path(self):
        clean = str(self.artifact_id).replace("-", "")
        return f"artifacts/{clean[:2]}/{clean[2:4]}/{self.filename}"


class PythonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    worktree_run_id: UUID
    script_relative: str = Field(min_length=1, max_length=200)
    script_sha256: str = Field(pattern=DIGEST)
    inputs: list[PythonInput] = Field(default_factory=list, max_length=8)
    expected_outputs: list[str] = Field(min_length=1, max_length=8)
    maximum_runtime: int = Field(default=120, ge=1, le=600, strict=True)
    permissions: list[str] = Field(max_length=32)

    @field_validator("script_relative")
    @classmethod
    def script_path(cls, value):
        relative_directory(value)
        if not value.endswith(".py"):
            raise ValueError("A Python source entrypoint is required")
        return value

    @field_validator("expected_outputs")
    @classmethod
    def output_paths(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Output filenames must be unique")
        for value in values:
            relative_directory(value)
            if len(value) > 200 or value == ".":
                raise ValueError("Expected a bounded output filename")
        return values

    @model_validator(mode="after")
    def input_limits(self):
        if len({item.artifact_id for item in self.inputs}) != len(self.inputs):
            raise ValueError("Input artifacts must be unique")
        if sum(item.size_bytes for item in self.inputs) > MAX_INPUT_TOTAL:
            raise ValueError("Python input files exceed the total limit")
        return self


def directory(run_id):
    return owned_path(f"runtime/python/{UUID(run_id)}")


def capabilities():
    configured = get_settings().python_image
    unavailable = {"available": False, "reason": "Build and configure the optional AI Station Python image"}
    if not re.fullmatch(r"ai-station-python:[A-Za-z0-9_.-]+", configured):
        return unavailable
    try:
        raw = docker(["image", "inspect", configured, "--format", "{{json .}}"], missing_ok=True)
        image = json.loads(raw) if raw else {}
        config = image.get("Config") or {}
        if (
            not IMAGE.fullmatch(image.get("Id", ""))
            or config.get("Entrypoint") != ENTRYPOINT
            or config.get("User") != "1000:1000"
            or (config.get("Labels") or {}).get("ai-station.python.protocol") != "1"
        ):
            return unavailable
        return {"available": True, "image_id": image["Id"], "protocol": 1, "network": False}
    except (OSError, RuntimeError, ValueError):
        return unavailable


def copy_snapshot(source, destination, digest, limit, *, expected_size=None):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > limit
            or expected_size is not None
            and before.st_size != expected_size
        ):
            raise ValueError("Python source/input must be a bounded regular file")
        data = bytearray()
        while chunk := os.read(fd, min(65536, limit + 1 - len(data))):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Python source/input exceeds its limit")
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Python source/input changed after approval")
        with destination.open("xb") as handle:
            handle.write(data)
        destination.chmod(0o400)
    finally:
        os.close(fd)


def docker(args, *, missing_ok=False):
    try:
        return browser_docker(args, missing_ok=missing_ok)
    except RuntimeError as exc:
        raise RuntimeError("Python container operation could not be confirmed") from exc


@contextmanager
def snapshot_lock(worktree_run_id):
    path = owned_path(f"runtime/validation-worktrees/{worktree_run_id}.lock")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with path.open("a") as lock:
        os.chmod(path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def start_python(manager, body):
    if not PERMISSIONS.issubset(body.permissions):
        raise PermissionError(
            "Python execution requires explicit filesystem, workspace and Python permissions"
        )
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = root / "request.json"
        if request.exists():
            saved = load_request(run_id)
            if PythonRequest.model_validate(saved["request"]) != body:
                raise ValueError("Run already owns another Python request")
            try:
                record = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise ValueError("Uncertain Python dispatch requires inspection") from exc
            if record["executor"] != "python":
                raise ValueError("Unexpected Python process owner")
            return record
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        capability = capabilities()
        if not capability["available"]:
            raise ValueError(capability["reason"])
        with snapshot_lock(str(body.worktree_run_id)):
            record = inspect_worktree(manager, str(body.worktree_run_id))
            if record["state"] != "ready" or record["project_id"] != str(body.project_id):
                raise ValueError("Python execution requires this project’s ready owned worktree")
            workspace = owned_path(record["relative_path"])
            script = Path(body.script_relative)
            parent = component_directory(workspace, script.parent.as_posix())
            stage = root / "inputs"
            stage.mkdir(mode=0o700)  # An uncertain partial snapshot is never silently replaced.
            copy_snapshot(parent / script.name, stage / "script.py", body.script_sha256, MAX_SCRIPT)
            for item in body.inputs:
                copy_snapshot(
                    owned_path(item.relative_path),
                    stage / item.filename,
                    item.sha256,
                    MAX_INPUT,
                    expected_size=item.size_bytes,
                )
        save(
            request,
            {
                "request": body.model_dump(mode="json"),
                "digest": hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
                "image": capability["image_id"],
            },
        )
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.python_job", run_id],
            cwd=get_settings().host_data_dir().resolve(),
            executor="python",
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(sys.path),
                "AI_STATION_DATA_HOST_PATH": str(get_settings().host_data_dir().resolve()),
                "PYTHONUNBUFFERED": "1",
            },
        )


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 32768:
        raise ValueError("Python request exceeds its limit")
    saved = json.loads(path.read_text())
    body = PythonRequest.model_validate(saved["request"])
    if (
        str(body.run_id) != str(UUID(run_id))
        or saved["digest"] != hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        or not IMAGE.fullmatch(saved["image"])
    ):
        raise ValueError("Python request ownership mismatch")
    return saved


def container_identity(saved):
    body = PythonRequest.model_validate(saved["request"])
    return f"ai-station-python-{body.run_id}", {
        "ai-station.python.owner": str(body.run_id),
        "ai-station.python.request": saved["digest"],
    }


def inspect_container(saved, recorded_id=None):
    name, labels = container_identity(saved)
    raw = docker(["inspect", "--type", "container", name, "--format", "{{json .}}"], missing_ok=True)
    if not raw:
        return None
    item = json.loads(raw)
    if (
        not CONTAINER.fullmatch(item.get("Id", ""))
        or recorded_id
        and item["Id"] != recorded_id
        or item.get("Name") != "/" + name
        or item.get("Image") != saved["image"]
        or any(
            (item.get("Config", {}).get("Labels") or {}).get(key) != value for key, value in labels.items()
        )
    ):
        raise ValueError("Refusing a container whose Python ownership does not match")
    return item


def stop_container(run_id):
    root = directory(run_id)
    saved = load_request(run_id)
    with (root / "container.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "container.json"
        if not path.exists():
            return True
        manifest = json.loads(path.read_text())
        if manifest["state"] == "removed":
            return True
        item = inspect_container(saved, manifest.get("id"))
        if item:
            docker(["rm", "--force", item["Id"]])
            save(path, {"state": "removed", "id": item["Id"]})
            return True
        if manifest.get("id"):
            save(path, {"state": "removed", "id": manifest["id"]})
            return True
        return False  # Lost create response may still hide a late daemon side effect.


def cancel_python(run_id):
    save(directory(run_id) / "cancel.json", {"requested": True})
    return stop_container(run_id)


def python_report(manager, run_id):
    record = manager.inspect(run_id)
    if (
        record["executor"] != "python"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record["status"] in {"canceled", "interrupted"}
    ):
        raise ValueError("Python execution has no confirmed completion")
    saved = load_request(run_id)
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 32768:
        raise ValueError("Python report exceeds its limit")
    report = json.loads(path.read_text())
    if (
        report.get("run_id") != run_id
        or report.get("request_digest") != saved["digest"]
        or not stop_container(run_id)
    ):
        raise ValueError("Python execution requires ownership/cleanup inspection")
    return report
