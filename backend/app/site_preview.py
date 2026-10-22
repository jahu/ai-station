"""Offline build inspection. UI/worker publication follows native lifecycle qualification."""

import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Artifact, Run, Task
from app.paths import artifact_relative
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable

PERMISSIONS = ("filesystem_read", "browser_preview")
MAX_ARCHIVE = 34 * 1024 * 1024
MAX_FRAME = 8 * 1024 * 1024
VIEWER_EXECUTORS = ("site_preview", "site_preview_action", "site_preview_close")


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


def project_write_condition():
    """Only these immutable inspection executors may coexist with project writes."""
    return Run.executor_type.not_in(VIEWER_EXECUTORS)


def viewport_action(body, frame):
    value = body.action.model_dump(mode="json")
    if value["kind"] == "click" and (value["x"] >= frame["width"] or value["y"] >= frame["height"]):
        raise HTTPException(422, "Click must stay inside the captured preview viewport")
    return value
