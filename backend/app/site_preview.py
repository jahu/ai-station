"""Offline build inspection. UI/worker publication follows native lifecycle qualification."""

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals import run_public
from app.db import session_scope
from app.models import Artifact, ResourceLock, Run, Task
from app.paths import artifact_relative
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task
from app.state import TERMINAL
from app.task_control import cancel_task, lock_task

PERMISSIONS = ("filesystem_read", "browser_preview")
MAX_ARCHIVE = 34 * 1024 * 1024
MAX_FRAME = 8 * 1024 * 1024


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenPreview(StrictBody):
    client_request_id: UUID
    source_run_id: UUID
    artifact_id: UUID
    width: int = Field(default=1240, ge=320, le=1600, strict=True)
    height: int = Field(default=800, ge=240, le=1200, strict=True)
    maximum_runtime: int = Field(default=300, ge=5, le=900, strict=True)


class Click(StrictBody):
    kind: Literal["click"]
    x: int = Field(ge=0, le=1599, strict=True)
    y: int = Field(ge=0, le=1199, strict=True)


class Text(StrictBody):
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def literal(cls, value):
        if "\x00" in value:
            raise ValueError("Preview text cannot contain a null byte")
        return value


class Key(StrictBody):
    kind: Literal["key"]
    key: Literal[
        "Tab",
        "Enter",
        "Escape",
        "Backspace",
        "Delete",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Space",
    ]


class Scroll(StrictBody):
    kind: Literal["scroll"]
    delta_x: int = Field(ge=-1500, le=1500, strict=True)
    delta_y: int = Field(ge=-1500, le=1500, strict=True)


class SimpleAction(StrictBody):
    kind: Literal["reset", "snapshot"]


class Interact(StrictBody):
    client_request_id: UUID
    expected_revision: int = Field(ge=0, le=127, strict=True)
    action: Annotated[Click | Text | Key | Scroll | SimpleAction, Field(discriminator="kind")]


class ClosePreview(StrictBody):
    client_request_id: UUID


def capability():
    from app.config import get_settings

    if not getattr(get_settings(), "site_preview_enabled", False):
        return {
            "available": False,
            "reason": "Configure the optional offline preview executor before enabling site previews",
        }
    try:
        value = RunnerClient(timeout=2).request("GET", "/v1/site-preview/capabilities")
        ready = (
            value.get("available") is True
            and value.get("protocol") == 2
            and value.get("network") is False
            and value.get("gpu") is False
            and value.get("maximum_sessions") == 1
        )
        if not ready:
            return {
                "available": False,
                "reason": value.get("reason") or "Update and configure the offline preview Host Runner",
            }
        return value
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Host Runner preview executor is unavailable"}


def source_snapshot(session, run_id, artifact_id):
    source = session.get(Run, str(run_id))
    artifact = session.get(Artifact, str(artifact_id))
    if source is None or artifact is None:
        raise HTTPException(404, "Build source not found")
    task = session.get(Task, source.task_id)
    exported = source.metadata_json.get("build_export") or {}
    meta = artifact.metadata_json
    if (
        source.executor_type != "project_validation"
        or source.status != "succeeded"
        or not source.project_id
        or task is None
        or task.project_id != source.project_id
        or source.metadata_json.get("build_artifact_id") != artifact.id
        or exported.get("status") != "ready"
        or artifact.run_id != source.id
        or artifact.artifact_type != "archive"
        or artifact.mime_type != "application/zip"
        or artifact.relative_path != artifact_relative(artifact.id, ".zip")
        or type(artifact.size_bytes) is not int
        or not 0 < artifact.size_bytes <= MAX_ARCHIVE
        or not artifact.sha256
        or not re.fullmatch(r"[0-9a-f]{64}", artifact.sha256)
        or artifact.size_bytes != exported.get("size_bytes")
        or artifact.sha256 != exported.get("sha256")
        or meta.get("role") != "coding_build"
        or meta.get("project_id") != source.project_id
        or meta.get("validation_run_id") != source.id
        or meta.get("source_run_id") != source.parent_run_id
        or meta.get("worktree_run_id") != source.parameters.get("worktree_run_id")
        or not source.parameters.get("worktree_run_id")
        or meta.get("file_count") != exported.get("file_count")
        or type(meta.get("file_count")) is not int
        or not 0 < meta["file_count"] <= 1000
        or meta.get("uncompressed_bytes") != exported.get("uncompressed_bytes")
        or type(meta.get("uncompressed_bytes")) is not int
        or not 0 <= meta["uncompressed_bytes"] <= 32 * 1024 * 1024
    ):
        raise HTTPException(409, "Preview requires the exact archive from this successful project build")
    if source.parent_run_id:
        parent = session.get(Run, source.parent_run_id)
        if parent is None or parent.task_id != source.task_id or parent.project_id != source.project_id:
            raise HTTPException(409, "Build source lineage does not match its project Task")
    return {
        "artifact_id": artifact.id,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "validation_run_id": source.id,
        "source_run_id": source.parent_run_id,
        "source_task_id": source.task_id,
        "source_agent_id": source.agent_id,
        "project_id": source.project_id,
        "worktree_run_id": source.parameters["worktree_run_id"],
        "created_at": artifact.created_at.isoformat(),
    }


def viewport_action(body, frame):
    value = body.action.model_dump(mode="json")
    if value["kind"] == "click" and (value["x"] >= frame["width"] or value["y"] >= frame["height"]):
        raise HTTPException(422, "Click must stay inside the captured preview viewport")
    return value


# Handlers publish durable requests only. Native execution belongs to workers.
router = APIRouter(prefix="/api/site-previews", tags=["site previews"])
DB = Annotated[Session, Depends(session_scope)]


def get_preview(session, run_id):
    run = session.get(Run, str(run_id))
    if run is None or run.executor_type != "site_preview":
        raise HTTPException(404, "Preview not found")
    return run


def replay(session, executor, request_id, body):
    previous = session.scalar(
        select(Run).where(
            Run.executor_type == executor, Run.parameters["client_request_id"].as_string() == str(request_id)
        )
    )
    if previous and previous.parameters.get("request") != body.model_dump(mode="json"):
        raise HTTPException(409, "This request identity already belongs to another preview operation")
    return previous


@router.get("/capabilities")
def preview_capability():
    return capability()


@router.get("")
def previews(session: DB, source_task_id: UUID | None = None, limit: int = Query(20, ge=1, le=100)):
    query = select(Run).where(Run.executor_type == "site_preview")
    if source_task_id:
        query = query.where(Run.parameters["source"]["source_task_id"].as_string() == str(source_task_id))
    return [
        run_public(session, run)
        for run in session.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit))
    ]


@router.get("/{run_id}")
def preview_detail(run_id: UUID, session: DB):
    return run_public(session, get_preview(session, run_id))


@router.post("", status_code=202)
def open_preview(body: OpenPreview, session: DB):
    source = source_snapshot(session, body.source_run_id, body.artifact_id)
    lock_task(session, session.get(Task, source["source_task_id"]))
    prior = replay(session, "site_preview", body.client_request_id, body)
    if prior:
        return run_public(session, prior)
    caps = capability()
    if not caps["available"]:
        raise HTTPException(503, caps["reason"])
    runner_id = caps.get("runner_id")
    if not isinstance(runner_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", runner_id):
        raise HTTPException(503, "Host Runner preview identity is misconfigured")
    active = session.scalar(
        select(Run).where(Run.executor_type == "site_preview", Run.status.not_in(TERMINAL)).limit(1)
    )
    if active:
        raise HTTPException(
            409, "Another preview is open. Close preview " + active.id + " before starting a new one"
        )
    key = "site-preview:" + runner_id
    held = session.scalar(
        select(ResourceLock).where(ResourceLock.resource_key == key, ResourceLock.released_at.is_(None))
    )
    if held:
        raise HTTPException(409, "An interrupted preview still requires cleanup: " + held.run_id)
    task = create_task(
        session,
        title="Inspect website build",
        prompt="Open an offline, read-only view of the selected static build.",
        capability="site.preview",
        project_id=source["project_id"],
    )
    run = create_run(
        session,
        task,
        run_type="preview",
        capability="site.preview",
        executor_type="site_preview",
        project_id=source["project_id"],
        permissions=list(PERMISSIONS),
        parameters={
            "source": source,
            "request": body.model_dump(mode="json"),
            "client_request_id": str(body.client_request_id),
            "runner_id": runner_id,
        },
        requested_resources={"ram_mib": 1536, "exclusive": key},
        retry_class="inspect",
    )
    session.commit()
    return run_public(session, run)


@router.post("/{run_id}/actions", status_code=202)
def interact(run_id: UUID, body: Interact, session: DB):
    parent = get_preview(session, run_id)
    task = session.get(Task, parent.task_id)
    lock_task(session, task)
    prior = replay(session, "site_preview_action", body.client_request_id, body)
    if prior:
        if prior.parent_run_id != parent.id:
            raise HTTPException(409, "Interaction identity belongs to another preview")
        return run_public(session, prior)
    session.refresh(parent)
    frame = parent.metadata_json.get("frame")
    if parent.status != "running" or task.metadata_json.get("stop_requested_at") or not frame:
        raise HTTPException(409, "Preview is not ready for interaction")
    if frame["revision"] != body.expected_revision:
        raise HTTPException(409, "Preview changed; use the current frame before interacting")
    viewport_action(body, frame)
    if session.scalar(
        select(Run.id)
        .where(
            Run.task_id == parent.task_id,
            Run.executor_type == "site_preview_action",
            Run.status.not_in(TERMINAL),
        )
        .limit(1)
    ):
        raise HTTPException(409, "Wait for the current preview interaction")
    run = create_run(
        session,
        task,
        run_type="preview",
        capability="site.preview.action",
        executor_type="site_preview_action",
        parent_run_id=parent.id,
        project_id=parent.project_id,
        permissions=list(PERMISSIONS),
        operation_key="action:" + str(body.client_request_id),
        parameters={
            "preview_run_id": parent.id,
            "request": body.model_dump(mode="json"),
            "client_request_id": str(body.client_request_id),
        },
        retry_class="inspect",
    )
    session.commit()
    return run_public(session, run)


@router.post("/{run_id}/close", status_code=202)
def close_preview(run_id: UUID, body: ClosePreview, session: DB):
    parent = get_preview(session, run_id)
    lock_task(session, session.get(Task, parent.task_id))
    prior = replay(session, "site_preview_close", body.client_request_id, body)
    if prior:
        if prior.parameters["preview_run_id"] != parent.id:
            raise HTTPException(409, "Close identity belongs to another preview")
        return run_public(session, prior)
    cancel_task(session, session.get(Task, parent.task_id))
    task = create_task(
        session,
        title="Close website preview",
        prompt="Confirm cleanup of the selected owned preview only.",
        capability="site.preview.close",
        project_id=parent.project_id,
    )
    run = create_run(
        session,
        task,
        run_type="preview",
        capability="site.preview.close",
        executor_type="site_preview_close",
        project_id=parent.project_id,
        permissions=list(PERMISSIONS),
        parameters={
            "preview_run_id": parent.id,
            "request": body.model_dump(mode="json"),
            "client_request_id": str(body.client_request_id),
        },
        retry_class="inspect",
    )
    session.commit()
    return run_public(session, run)
