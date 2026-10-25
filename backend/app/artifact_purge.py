"""User-confirmed, resumable removal of owned bytes with retained provenance."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.approvals import latest_approval, request_run_approval, run_public
from app.config import get_settings
from app.db import session_scope, utcnow
from app.events import append_event
from app.models import Artifact, Run, Task
from app.paths import validate_relative
from app.permissions import require
from app.runs import create_run, mark_failed, transition
from app.serialize import iso
from app.state import TERMINAL, RunStatus

router = APIRouter(prefix="/api/library")
DB = Annotated[Session, Depends(session_scope)]
ACTION = "artifact.delete_permanently"


class SelectedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    expected_updated_at: datetime | None


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    scope: Literal["selected", "trash"] = "selected"
    items: list[SelectedArtifact] = Field(default_factory=list, max_length=5000)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _visible():
    return (
        Artifact.purged_at.is_(None),
        Artifact.metadata_json["internal_media"].as_boolean().is_not(True),
        Artifact.metadata_json["internal_data_output"].as_boolean().is_not(True),
    )


@router.get("/trash-count")
def trash_count(session: DB):
    return {
        "count": session.scalar(
            select(func.count()).select_from(Artifact).where(*_visible(), Artifact.trashed_at.is_not(None))
        )
    }


def _snapshot(row: Artifact) -> dict:
    return {
        "id": row.id,
        "name": row.title or row.original_filename or row.id,
        "version": iso(row.library_updated_at),
        "trashed_at": iso(row.trashed_at),
        "path": row.relative_path,
        "thumbnail": row.thumbnail_relative_path,
        "sha256": row.sha256,
        "size": row.size_bytes,
    }


def _receipt(session: Session, task_id: str, request_hash: str):
    task = session.get(Task, task_id)
    if task is None:
        return None
    if task.metadata_json.get("purge_request_hash") != request_hash:
        raise HTTPException(409, "This request identity already belongs to different work")
    run = session.scalar(select(Run).where(Run.task_id == task_id, Run.executor_type == "artifact_purge"))
    if run is None:
        raise HTTPException(409, "Deletion receipt is incomplete")
    return run_public(session, run)


@router.post("/purges", status_code=202)
def prepare_purge(body: PurgeRequest, session: DB):
    """Freeze a complete selection; no files are removed before explicit approval."""
    request_hash = _digest(body.model_dump(mode="json", exclude={"request_id"}))
    task_id = str(body.request_id)
    existing = _receipt(session, task_id, request_hash)
    if existing:
        return existing
    if body.scope == "trash":
        if body.items:
            raise HTTPException(422, "Empty Trash takes its complete scope from the server")
        rows = list(
            session.scalars(
                select(Artifact)
                .where(*_visible(), Artifact.trashed_at.is_not(None))
                .order_by(Artifact.created_at, Artifact.id)
            )
        )
    else:
        ids = [str(item.id) for item in body.items]
        if not ids or len(ids) != len(set(ids)):
            raise HTTPException(422, "Select distinct artifacts to delete")
        found = {
            row.id: row for row in session.scalars(select(Artifact).where(*_visible(), Artifact.id.in_(ids)))
        }
        if len(found) != len(ids):
            raise HTTPException(409, "A selected artifact is no longer available; reload Library")
        rows = [found[item] for item in ids]
        if any(
            row.library_updated_at != item.expected_updated_at
            for row, item in zip(rows, body.items, strict=True)
        ):
            raise HTTPException(409, "A selected artifact changed; reload it before confirming deletion")
    if not rows:
        raise HTTPException(409, "Trash is already empty")
    for row in rows:
        if row.purge_run_id:
            owner = session.get(Run, row.purge_run_id)
            if owner is None or owner.status not in TERMINAL:
                raise HTTPException(409, "A selected artifact already has an active deletion")
    items = [_snapshot(row) for row in rows]
    try:
        task = Task(
            id=task_id,
            title=f"Permanently delete {len(items)} artifacts",
            prompt="Delete only the explicitly confirmed Library selection",
            capability="library.purge",
            metadata_json={"purge_request_hash": request_hash},
        )
        session.add(task)
        session.flush()
        run = create_run(
            session,
            task,
            run_type="maintenance",
            capability="library.purge",
            executor_type="artifact_purge",
            execution_target="container",
            permissions=["artifact_delete"],
            retry_class="inspect",
            parameters={"scope": body.scope, "items": items, "scope_hash": _digest(items)},
        )
        approval = request_run_approval(
            session,
            run,
            action=ACTION,
            reason="Permanent deletion cannot be undone. History and lineage remain available.",
            payload={
                "count": len(items),
                "scope": body.scope,
                "scope_hash": _digest(items),
                "items": [{"id": item["id"], "name": item["name"]} for item in items],
            },
        )
        approval.risk = "high"
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _receipt(session, task_id, request_hash)
        if existing:
            return existing
        raise
    return run_public(session, run)


@router.get("/purges")
def list_purges(session: DB):
    return [
        run_public(session, row)
        for row in session.scalars(
            select(Run).where(Run.executor_type == "artifact_purge").order_by(Run.created_at.desc()).limit(20)
        )
    ]


def _unlink_owned(relative: str, *, thumbnail: bool, expected_hash: str = "", expected_size=None):
    """Pin every directory with NOFOLLOW; never resolve a symlink into another tree."""
    parts = validate_relative(relative).split("/")
    if len(parts) < 2 or parts[0] != ("thumbnails" if thumbnail else "artifacts"):
        raise ValueError("Deletion is restricted to owned artifacts and thumbnails")
    directory = os.open(get_settings().data_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                return
            os.close(directory)
            directory = child
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Only regular artifact files can be deleted")
            if expected_size is not None and before.st_size != expected_size:
                raise ValueError("Artifact bytes changed since confirmation")
            if expected_hash and hashlib.file_digest(source, "sha256").hexdigest() != expected_hash:
                raise ValueError("Artifact hash changed since confirmation")
            after = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Artifact changed during deletion")
            os.unlink(parts[-1], dir_fd=directory)
    finally:
        os.close(directory)


def _shared(session: Session, artifact_id: str, path: str) -> bool:
    return bool(
        session.scalar(
            select(Artifact.id)
            .where(
                Artifact.id != artifact_id,
                Artifact.purged_at.is_(None),
                or_(Artifact.relative_path == path, Artifact.thumbnail_relative_path == path),
            )
            .limit(1)
        )
        or session.scalar(select(Run.id).where(or_(Run.stdout_log == path, Run.stderr_log == path)).limit(1))
    )


class ArtifactPurgeExecutor:
    name = "artifact_purge"

    def execute(self, session: Session, run: Run) -> str:
        require(run.effective_permissions, "artifact_delete")
        session.refresh(run)
        if run.status == RunStatus.CANCEL_REQUESTED.value:
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        items = run.parameters.get("items", [])
        approval = latest_approval(session, run.id)
        if (
            not items
            or approval is None
            or approval.resolution != "granted"
            or approval.action != ACTION
            or (
                approval.payload.get("scope_hash") != _digest(items)
                or run.parameters.get("scope_hash") != _digest(items)
            )
        ):
            raise ValueError("Permanent deletion requires approval for the exact frozen selection")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        if run.metadata_json.get("cancel_on_resume"):
            transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
        else:
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        outcomes = dict(run.metadata_json.get("purge_outcomes") or {})
        for item in items:
            session.refresh(run)
            if run.status == RunStatus.CANCEL_REQUESTED.value:
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            if outcomes.get(item["id"], {}).get("state") == "deleted":
                continue
            try:
                retained = self._remove_item(session, run, item)
                outcome = {"state": "deleted", "retained_shared_paths": retained}
            except (OSError, ValueError) as exc:
                session.rollback()
                outcome = {"state": "failed", "error": str(exc)[:500]}
            outcomes[item["id"]] = outcome
            session.refresh(run)
            run.metadata_json = {**run.metadata_json, "purge_outcomes": dict(outcomes)}
            append_event(
                session,
                run.id,
                "artifact.purge_completed" if outcome["state"] == "deleted" else "artifact.purge_failed",
                {"artifact_id": item["id"], **outcome},
            )
            session.commit()
        session.refresh(run)
        if run.status == RunStatus.CANCEL_REQUESTED.value:
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        elif any(value["state"] == "failed" for value in outcomes.values()):
            mark_failed(
                session,
                run,
                "ArtifactDeletionFailed",
                "Some artifacts could not be deleted. Inspect individual results before retrying.",
            )
        else:
            run.summary = f"Permanently deleted {len(items)} artifacts; history retained"
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"

    def _remove_item(self, session, run, item):
        row = session.get(Artifact, item["id"], populate_existing=True)
        if row is None:
            raise ValueError("Artifact record is unavailable")
        if row.purged_at:
            return []
        if row.purge_run_id != run.id:
            if _snapshot(row) != item:
                raise ValueError("Artifact changed after confirmation; nothing was deleted")
            previous = session.get(Run, row.purge_run_id) if row.purge_run_id else None
            if row.purge_run_id and (previous is None or previous.status not in TERMINAL):
                raise ValueError("Artifact belongs to another active deletion")
            changed = session.execute(
                update(Artifact)
                .where(
                    Artifact.id == row.id,
                    Artifact.library_updated_at == row.library_updated_at,
                    Artifact.purged_at.is_(None),
                    Artifact.purge_run_id == row.purge_run_id,
                )
                .values(
                    purge_run_id=run.id, trashed_at=row.trashed_at or utcnow(), library_updated_at=utcnow()
                )
            )
            if changed.rowcount != 1:
                raise ValueError("Artifact changed while starting deletion")
            session.commit()  # Durable intent precedes the first filesystem side effect.
            session.refresh(row)
        elif (row.relative_path, row.thumbnail_relative_path, row.sha256, row.size_bytes) != (
            item["path"],
            item["thumbnail"],
            item["sha256"],
            item["size"],
        ):
            raise ValueError("Deletion intent no longer matches owned bytes")
        retained = []
        targets = [(item["path"], False)]
        if len(item["sha256"]) != 64:
            raise ValueError("Deletion requires a verified artifact content hash")
        if item["thumbnail"]:
            if item["thumbnail"] != f"thumbnails/{row.id}.jpg":
                raise ValueError("Unexpected thumbnail ownership")
            targets.append((item["thumbnail"], True))
        protected = {path: _shared(session, row.id, path) for path, _ in targets}
        row_id = row.id
        source_run_id = row.run_id
        session.commit()  # Hashing/unlink never holds a SQLite transaction.
        for path, thumbnail in targets:
            if protected[path]:
                retained.append(path)
            else:
                _unlink_owned(
                    path,
                    thumbnail=thumbnail,
                    expected_hash="" if thumbnail else item["sha256"],
                    expected_size=None if thumbnail else item["size"],
                )
        row = session.get(Artifact, row_id, populate_existing=True)
        row.purged_at = utcnow()
        row.library_updated_at = utcnow()
        if source_run_id:
            append_event(
                session,
                source_run_id,
                "artifact.permanently_deleted",
                {"artifact_id": row_id, "purge_run_id": run.id},
            )
        session.commit()
        return retained
