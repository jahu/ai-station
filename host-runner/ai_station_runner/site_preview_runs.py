"""Typed, journaled ownership of offline preview sessions and action proxies."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_station_runner.browser_runs import CONTAINER, IMAGE, docker
from ai_station_runner.config import get_settings
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.python_runs import copy_snapshot
from ai_station_runner.site_preview_protocol import (
    MAX_ACTIONS,
    MAX_FRAME,
    PROTOCOL_VERSION,
    action_request,
    asset_path,
)
from ai_station_runner.site_preview_source import MAX_ARCHIVE, BuildSource
from ai_station_runner.worktrees import owned_path

PERMISSIONS = {"filesystem_read", "browser_preview"}
ENTRYPOINT = ["python", "-u", "/opt/ai-station/site_preview_renderer.py"]


class Archive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_ARCHIVE, strict=True)

    @property
    def relative_path(self):
        aid = str(self.artifact_id)
        clean = aid.replace("-", "")
        return f"artifacts/{clean[:2]}/{clean[2:4]}/{aid}.zip"


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    archive: Archive
    entry: str = "index.html"
    width: int = Field(default=1240, ge=320, le=1600, strict=True)
    height: int = Field(default=800, ge=240, le=1200, strict=True)
    maximum_runtime: int = Field(default=300, ge=5, le=900, strict=True)
    permissions: list[Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")]] = Field(max_length=32)

    @field_validator("entry")
    @classmethod
    def html_entry(cls, value):
        asset_path(value)
        if not value.lower().endswith(".html"):
            raise ValueError("Preview requires an HTML build entry")
        return value


class PreviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    preview_run_id: UUID
    expected_revision: int = Field(ge=0, le=MAX_ACTIONS, strict=True)
    action: dict
    permissions: list[Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")]] = Field(max_length=32)

    @model_validator(mode="after")
    def bounded_action(self):
        if self.run_id == self.preview_run_id:
            raise ValueError("Interaction and preview require distinct Run identities")
        action_request(self.protocol(), 1600, 1200)
        return self

    def protocol(self):
        return {
            "kind": "action",
            "id": str(self.run_id),
            "expected_revision": self.expected_revision,
            "action": self.action,
        }


def path(run_id, name="request.json", *, action=False):
    root = "site-preview-actions" if action else "site-previews"
    return owned_path(f"runtime/{root}/{UUID(str(run_id))}/{name}")


@contextmanager
def locked(filename):
    filename = owned_path(filename.relative_to(get_settings().host_data_dir().resolve()).as_posix())
    filename.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(filename, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def save(filename, payload):
    filename = owned_path(filename.relative_to(get_settings().host_data_dir().resolve()).as_posix())
    filename.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".preview-", dir=filename.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, filename)
        directory = os.open(filename.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(filename, limit=32768):
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("Invalid preview journal file")
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
        if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Preview journal changed during inspection")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Invalid preview journal object")
    return value


def digest(body):
    return hashlib.sha256(body.model_dump_json().encode()).hexdigest()


def capabilities():
    configured = get_settings().site_preview_image
    unavailable = {
        "available": False,
        "reason": "Build and configure the optional offline site-preview image",
    }
    if not re.fullmatch(r"ai-station-site-preview:[A-Za-z0-9_.-]+", configured):
        return unavailable
    try:
        raw = docker(["image", "inspect", configured, "--format", "{{json .}}"], missing_ok=True)
        image = json.loads(raw) if raw else {}
        config = image.get("Config") or {}
        if (
            not IMAGE.fullmatch(image.get("Id", ""))
            or config.get("Entrypoint") != ENTRYPOINT
            or config.get("User") != "1000:1000"
            or (config.get("Labels") or {}).get("ai-station.site-preview.protocol") != PROTOCOL_VERSION
        ):
            return unavailable
        return {
            "available": True,
            "image_id": image["Id"],
            "network": False,
            "gpu": False,
            "protocol": int(PROTOCOL_VERSION),
            "maximum_sessions": 1,
            "ram_mib": 1536,
        }
    except (OSError, RuntimeError, ValueError):
        return unavailable


def load_request(run_id, *, action=False):
    saved = read(path(run_id, action=action))
    body = (PreviewAction if action else PreviewRequest).model_validate(saved["request"])
    if str(body.run_id) != str(UUID(str(run_id))) or digest(body) != saved.get("digest"):
        raise ValueError("Preview request ownership mismatch")
    if not action and (
        not IMAGE.fullmatch(saved.get("image", ""))
        or type(saved.get("created_at")) not in {float, int}
        or not math.isfinite(saved["created_at"])
        or saved["created_at"] <= 0
    ):
        raise ValueError("Invalid preview image or deadline identity")
    if action and saved.get("preview_digest") != load_request(str(body.preview_run_id))["digest"]:
        raise ValueError("Interaction belongs to another preview request")
    return saved


def container_identity(saved):
    body = PreviewRequest.model_validate(saved["request"])
    return f"ai-station-site-preview-{body.run_id}", {
        "ai-station.site-preview.owner": str(body.run_id),
        "ai-station.site-preview.request": saved["digest"],
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
        raise ValueError("Refusing a container whose preview ownership does not match")
    return item


def stop_container(run_id):
    saved = load_request(run_id)
    with locked(path(run_id, "container.lock")):
        filename = path(run_id, "container.json")
        if not filename.exists():
            return True
        manifest = read(filename)
        if manifest.get("state") == "removed":
            return True
        if manifest.get("state") not in {"creating", "created"}:
            raise ValueError("Invalid preview container journal")
        item = inspect_container(saved, manifest.get("id"))
        if item:
            docker(["rm", "--force", item["Id"]])
            save(filename, {"state": "removed", "id": item["Id"]})
            return True
        if manifest.get("id"):
            save(filename, {"state": "removed", "id": manifest["id"]})
            return True
        return False


def cancel_preview(run_id):
    load_request(run_id)
    save(path(run_id, "cancel.json"), {"requested": True})
    return stop_container(run_id)


def frame_metadata(run_id, frame):
    body = PreviewRequest.model_validate(load_request(run_id)["request"])
    keys = {
        "revision",
        "action_id",
        "width",
        "height",
        "path",
        "title",
        "blocked_requests",
        "relative_path",
        "sha256",
        "size_bytes",
    }
    if not isinstance(frame, dict) or set(frame) != keys:
        raise ValueError("Invalid preview frame metadata")
    revision = frame["revision"]
    if (
        type(revision) is not int
        or not 0 <= revision <= MAX_ACTIONS
        or frame["width"] != body.width
        or frame["height"] != body.height
        or type(frame["width"]) is not int
        or type(frame["height"]) is not int
        or not isinstance(frame["title"], str)
        or len(frame["title"]) > 300
        or type(frame["blocked_requests"]) is not int
        or not 0 <= frame["blocked_requests"] <= 10000
    ):
        raise ValueError("Invalid preview frame viewport or revision")
    if frame["path"] is not None:
        asset_path(frame["path"])
    if (
        revision == 0
        and frame["action_id"] is not None
        or revision > 0
        and (not isinstance(frame["action_id"], str) or str(UUID(frame["action_id"])) != frame["action_id"])
    ):
        raise ValueError("Invalid preview frame action identity")
    if (
        frame["relative_path"] != f"runtime/site-previews/{run_id}/frames/{revision}.png"
        or not isinstance(frame["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", frame["sha256"])
        or type(frame["size_bytes"]) is not int
        or not 0 < frame["size_bytes"] <= MAX_FRAME
    ):
        raise ValueError("Invalid preview frame file identity")
    return frame


def state(manager, run_id):
    record = manager.inspect(run_id)
    if record["executor"] != "site_preview":
        raise ValueError("Unexpected preview process owner")
    saved = load_request(run_id)
    filename = path(run_id, "state.json")
    frame = None
    if filename.exists():
        current = read(filename)
        if current.get("request_digest") != saved["digest"]:
            raise ValueError("Preview state ownership mismatch")
        frame = frame_metadata(run_id, current["frame"])
    return {
        "run_id": run_id,
        "frame": frame,
        "expires_at": saved["created_at"] + saved["request"]["maximum_runtime"],
        "cancel_requested": path(run_id, "cancel.json").exists(),
        "process": {
            key: record.get(key)
            for key in ("alive", "status", "exit_code", "cleanup_confirmed", "completion_pending")
        },
    }


def _environment():
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": os.pathsep.join(sys.path),
        "AI_STATION_DATA_HOST_PATH": str(get_settings().host_data_dir().resolve()),
        "PYTHONUNBUFFERED": "1",
    }


def start_preview(manager, body):
    if not PERMISSIONS.issubset(body.permissions):
        raise PermissionError("Offline preview requires filesystem_read and browser_preview permissions")
    run_id = str(body.run_id)
    with locked(owned_path("runtime/site-preview-admission.lock")):
        if path(run_id).exists():
            if PreviewRequest.model_validate(load_request(run_id)["request"]) != body:
                raise ValueError("Run already owns another preview request")
            try:
                record = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise ValueError("Uncertain preview dispatch requires inspection") from exc
            if record["executor"] != "site_preview":
                raise ValueError("Unexpected preview process owner")
            return record
        owner_file = owned_path("runtime/site-preview-owner.json")
        if owner_file.exists():
            old = str(UUID(read(owner_file)["run_id"]))
            try:
                record = manager.inspect(old)
                if (
                    record["executor"] != "site_preview"
                    or record["alive"]
                    or record.get("completion_pending")
                    or record.get("cleanup_confirmed") is not True
                ):
                    raise ValueError("Another preview is active or requires inspection")
            except ProcessNotOwned as exc:
                if not path(old, "cancel.json").exists() or not stop_container(old):
                    raise ValueError("Previous preview dispatch requires inspection") from exc
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        capability = capabilities()
        if not capability["available"]:
            raise ValueError(capability["reason"])
        destination = path(run_id, "source.zip")
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        copy_snapshot(
            owned_path(body.archive.relative_path),
            destination,
            body.archive.sha256,
            MAX_ARCHIVE,
            expected_size=body.archive.size_bytes,
        )
        BuildSource(destination, body.archive.sha256, body.archive.size_bytes, body.entry)
        save(
            path(run_id),
            {
                "request": body.model_dump(mode="json"),
                "digest": digest(body),
                "image": capability["image_id"],
                "created_at": time.time(),
            },
        )
        save(owner_file, {"run_id": run_id})
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.site_preview_job", run_id],
            cwd=get_settings().host_data_dir().resolve(),
            executor="site_preview",
            env=_environment(),
        )


def action_result(run_id):
    saved = load_request(run_id, action=True)
    filename = path(run_id, "receipt.json", action=True)
    if not filename.exists():
        return {"state": "pending"}
    receipt = read(filename)
    if receipt.get("digest") != saved["digest"] or receipt.get("state") not in {
        "frame",
        "rejected",
        "canceled",
        "sent",
    }:
        raise ValueError("Invalid preview interaction receipt")
    if receipt["state"] == "frame":
        frame = frame_metadata(saved["request"]["preview_run_id"], receipt["frame"])
        if frame["action_id"] != run_id or frame["revision"] != saved["request"]["expected_revision"] + 1:
            raise ValueError("Interaction frame ownership mismatch")
    return receipt


def start_action(manager, body):
    if not PERMISSIONS.issubset(body.permissions):
        raise PermissionError("Preview interaction requires explicit preview permissions")
    load_request(str(body.preview_run_id))
    with locked(path(body.preview_run_id, "action-admission.lock")):
        return _start_action(manager, body)


def _start_action(manager, body):
    if not PERMISSIONS.issubset(body.permissions):
        raise PermissionError("Preview interaction requires explicit preview permissions")
    run_id, preview_id = str(body.run_id), str(body.preview_run_id)
    with locked(path(run_id, "request.lock", action=True)):
        if path(run_id, action=True).exists():
            if PreviewAction.model_validate(load_request(run_id, action=True)["request"]) != body:
                raise ValueError("Run already owns another preview interaction")
            try:
                record = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise ValueError("Uncertain interaction dispatch requires inspection") from exc
            if record["executor"] != "site_preview_action":
                raise ValueError("Unexpected preview interaction process owner")
            return record
        current = state(manager, preview_id)
        if not current["process"]["alive"] or current["cancel_requested"] or not current["frame"]:
            raise ValueError("Preview is not ready for interaction")
        saved = load_request(preview_id)
        parent = PreviewRequest.model_validate(saved["request"])
        action_request(body.protocol(), parent.width, parent.height)
        if body.expected_revision != current["frame"]["revision"]:
            raise ValueError("Preview frame changed; refresh before interacting")
        if body.expected_revision >= MAX_ACTIONS:
            raise ValueError("Preview interaction budget exhausted")
        active_file = path(preview_id, "action-owner.json")
        if active_file.exists():
            active = read(active_file)
            if active.get("preview_digest") != saved["digest"]:
                raise ValueError("Preview interaction admission ownership mismatch")
            previous = str(UUID(active["run_id"]))
            try:
                record = manager.inspect(previous)
            except ProcessNotOwned as exc:
                raise ValueError("Previous preview interaction requires inspection") from exc
            if (
                record["executor"] != "site_preview_action"
                or record["alive"]
                or record.get("completion_pending")
                or record.get("cleanup_confirmed") is not True
            ):
                raise ValueError("A preview interaction is active or requires inspection")
            if state(manager, preview_id)["cancel_requested"]:
                raise ValueError("Preview closed during interaction inspection")
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        save(
            path(run_id, action=True),
            {
                "request": body.model_dump(mode="json"),
                "digest": digest(body),
                "preview_digest": saved["digest"],
            },
        )
        save(active_file, {"run_id": run_id, "preview_digest": saved["digest"]})
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.site_preview_action_job", run_id],
            cwd=get_settings().host_data_dir().resolve(),
            executor="site_preview_action",
            env=_environment(),
        )


def cancel_action(run_id):
    saved = load_request(run_id, action=True)
    with locked(path(run_id, "action.lock", action=True)):
        receipt = action_result(run_id)
        if receipt["state"] in {"frame", "rejected", "canceled"}:
            return True
        save(path(run_id, "cancel.json", action=True), {"requested": True})
        if receipt["state"] == "pending":
            save(path(run_id, "receipt.json", action=True), {"digest": saved["digest"], "state": "canceled"})
            return True
        return cancel_preview(saved["request"]["preview_run_id"])


def action_report(manager, run_id):
    record = manager.inspect(run_id)
    if (
        record["executor"] != "site_preview_action"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record.get("status") in {"canceled", "interrupted"}
        or record.get("cleanup_confirmed") is not True
    ):
        raise ValueError("Preview interaction requires confirmed completion")
    receipt = action_result(run_id)
    if receipt["state"] not in {"frame", "rejected"}:
        raise ValueError("Preview interaction has no confirmed result")
    return receipt


def report(manager, run_id):
    record = manager.inspect(run_id)
    if (
        record["executor"] != "site_preview"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record.get("status") in {"canceled", "interrupted"}
        or record.get("cleanup_confirmed") is not True
    ):
        raise ValueError("Preview requires confirmed completion")
    result = read(path(run_id, "report.json"))
    if result.get("request_digest") != load_request(run_id)["digest"]:
        raise ValueError("Preview report ownership mismatch")
    return result


def close_preview(manager, run_id):
    """Close only this reserved scope, including an interrupted dispatch journal."""
    if not path(run_id).exists():
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            owner = owned_path("runtime/site-preview-owner.json")
            if owner.exists() and read(owner).get("run_id") == run_id:
                return {"cleanup_confirmed": False, "reason": "Preview ownership journal requires inspection"}
            return {"cleanup_confirmed": True, "owned": False}
        raise ValueError("Preview request ownership missing; inspect before cleanup")
    load_request(run_id)
    confirmed = cancel_preview(run_id)
    try:
        record = manager.inspect(run_id)
    except ProcessNotOwned:
        return {"cleanup_confirmed": confirmed, "owned": True}
    if record["executor"] != "site_preview":
        raise ValueError("Refusing to stop another process owner")
    record = manager.cancel(run_id)
    return {
        "cleanup_confirmed": confirmed
        and not record["alive"]
        and not record.get("completion_pending")
        and record.get("cleanup_confirmed") is True,
        "owned": True,
    }
