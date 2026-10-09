"""Explicit SQLite backups and inspect-only copy checks. Restore and image rollout stay unpublished."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.artifacts import adopt_existing, register_file
from app.config import get_settings
from app.db import alembic_config, session_scope, utcnow
from app.events import append_event
from app.models import Artifact, Run, Setting, Task
from app.operator_auth import public_status
from app.paths import PathBoundaryError, safe_join, validate_relative
from app.permissions import require
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import create_run, create_task, mark_failed, run_dict, transition
from app.state import ACTIVE, TERMINAL, RunStatus

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
DB = Annotated[Session, Depends(session_scope)]
SETUP_KEY = "maintenance"
PERMISSION = "manage_station"


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def database_file() -> Path:
    url = get_settings().sqlite_url()
    if not url.startswith("sqlite:///") or ":memory:" in url:
        raise ValueError("Only a SQLite file database can be backed up")
    return Path(url.removeprefix("sqlite:///"))


def schema_revisions(session: Session) -> tuple[str | None, str | None]:
    script = ScriptDirectory.from_config(alembic_config())
    heads = script.get_heads()
    head = heads[0] if len(heads) == 1 else None
    present = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return present, head


def stored(session: Session) -> dict:
    row = session.get(Setting, SETUP_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    return {"last_backup_run_id": value.get("last_backup_run_id")}


def remember_backup(session: Session, run_id: str) -> None:
    payload = {"last_backup_run_id": run_id}
    row = session.get(Setting, SETUP_KEY)
    if row is None:
        session.add(Setting(key=SETUP_KEY, value=payload))
    else:
        row.value = payload


def backup_relative(run_id: str) -> str:
    return validate_relative(f"backups/{run_id}.sqlite")


def needs_inspection(run: Run) -> bool:
    return run.status == RunStatus.INTERRUPTED.value and not run.metadata_json.get(
        "inspection_acknowledged_at"
    )


def interrupted_runs(session: Session, *, limit: int = 8) -> list[dict]:
    rows = session.execute(
        select(Run, Task.title)
        .join(Task, Run.task_id == Task.id)
        .where(Run.status == RunStatus.INTERRUPTED.value)
        .order_by(Run.finished_at.desc(), Run.id)
        .limit(50)
    ).all()
    items = []
    for run, title in rows:
        if not needs_inspection(run):
            continue
        items.append({**run_dict(run), "title": title, "replay": False, "restore": "unpublished"})
        if len(items) >= limit:
            break
    return items


def readiness(session: Session) -> dict:
    current, head = schema_revisions(session)
    path = database_file()
    data_dir = get_settings().data_dir.resolve()
    try:
        relative = str(path.resolve().relative_to(data_dir))
    except ValueError:
        relative = path.name
    active = int(session.scalar(select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))) or 0)
    journal = session.scalar(text("PRAGMA journal_mode"))
    bind = public_status(session)
    last_id = stored(session)["last_backup_run_id"]
    last = session.get(Run, last_id) if last_id else None
    awaiting = interrupted_runs(session)
    return {
        "schema_revision": current,
        "schema_head": head,
        "schema_current_matches_head": current == head and current is not None,
        "database": relative,
        "journal_mode": journal,
        "active_runs": active,
        "upgrade_blocked_by_active_runs": active > 0,
        "data_survives_compose_down": True,
        "compose_down_removes_bind_data": False,
        "application_data": "bind-mount",
        "restore": "unpublished",
        "image_rollout": "unpublished",
        "lan_bind_allowed": False,
        "lan_exposure": bind["lan_exposure"],
        "last_backup": run_dict(last) if last else None,
        "interrupted_runs": awaiting,
        "interrupted_run_count": len(awaiting),
        "summary": (
            "Upgrade readiness is inspect-only. Compose down without --volumes keeps the bind-mounted "
            "data directory. An explicit backup Run copies SQLite with VACUUM INTO and "
            "integrity-checks the copy. A successful copy can be re-checked in place without "
            "writing the live database. Restore, image rollout and LAN publish are unpublished. "
            "Do not treat preview :8765 as this checkout."
        ),
    }


def copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    quoted = str(destination.resolve()).replace("'", "''")
    connection = sqlite3.connect(str(source), timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute(f"VACUUM INTO '{quoted}'")
    finally:
        connection.close()


def integrity_ok(path: Path) -> str:
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        result = connection.execute("PRAGMA integrity_check").fetchone()
        return result[0] if result else "unknown"
    finally:
        connection.close()


def readonly_sqlite(path: Path) -> sqlite3.Connection:
    quoted = str(path.resolve()).replace("?", "%3F")
    connection = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        pass
    return connection


def integrity_readonly(path: Path) -> str:
    connection = None
    try:
        connection = readonly_sqlite(path)
        result = connection.execute("PRAGMA integrity_check").fetchone()
        return result[0] if result else "unknown"
    except sqlite3.Error as exc:
        return str(exc) or "unreadable"
    finally:
        if connection is not None:
            connection.close()


def backup_schema_revision(path: Path) -> str | None:
    connection = None
    try:
        connection = readonly_sqlite(path)
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return str(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()


def digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def sqlite_artifact(session: Session, run: Run) -> Artifact | None:
    return session.scalars(
        select(Artifact).where(
            Artifact.run_id == run.id,
            Artifact.original_filename == "ai-station.sqlite",
        )
    ).first()


def inspect_copy(session: Session, run: Run) -> dict:
    artifact = sqlite_artifact(session, run)
    if artifact is None or not artifact.relative_path:
        raise HTTPException(409, "Backup copy is not present")
    try:
        stored = safe_join(get_settings().data_dir, artifact.relative_path)
    except PathBoundaryError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not stored.is_file():
        raise HTTPException(409, "Backup copy is not present on disk")
    size, digest = digest_file(stored)
    check = integrity_readonly(stored)
    copy_schema = backup_schema_revision(stored)
    live_schema, _head = schema_revisions(session)
    hash_matches = digest == artifact.sha256 and size == artifact.size_bytes
    return {
        "run_id": run.id,
        "status": run.status,
        "integrity_check": check,
        "hash_matches": hash_matches,
        "size_bytes": size,
        "recorded_size_bytes": artifact.size_bytes,
        "sha256": digest,
        "recorded_sha256": artifact.sha256,
        "relative_path": artifact.relative_path,
        "schema_revision": copy_schema,
        "live_schema_revision": live_schema,
        "schema_matches_live": copy_schema == live_schema and copy_schema is not None,
        "restore": "unpublished",
        "image_rollout": "unpublished",
        "replay": False,
        "summary": (
            f"Copy integrity_check={check}; hash "
            f"{'matches' if hash_matches else 'differs'}; restore remains unpublished"
        ),
    }


class SqliteBackupExecutor:
    name = "sqlite_backup"

    @staticmethod
    def canceled(session: Session, run: Run) -> bool:
        session.refresh(run)
        if run.status == RunStatus.CANCEL_REQUESTED.value:
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            session.commit()
            return True
        session.commit()
        return run.status in TERMINAL

    def execute(self, session: Session, run: Run) -> str:
        destination = None
        try:
            require(run.effective_permissions, PERMISSION)
            if self.canceled(session, run):
                return "done"
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(
                session, run, RunStatus.RUNNING, event_type="executor.started", payload={"mode": "backup"}
            )
            session.commit()
            if self.canceled(session, run):
                return "done"
            source = database_file()
            if not source.is_file():
                mark_failed(session, run, "DatabaseMissing", "SQLite database file is not present")
                return "done"
            relative = backup_relative(run.id)
            destination = safe_join(get_settings().data_dir, relative)
            session.commit()
            session.expire_all()
            copy_database(source, destination)
            session.refresh(run)
            if self.canceled(session, run):
                destination.unlink(missing_ok=True)
                return "done"
            check = integrity_ok(destination)
            if check != "ok":
                destination.unlink(missing_ok=True)
                mark_failed(session, run, "IntegrityCheckFailed", f"Backup integrity_check returned {check}")
                return "done"
            sqlite = adopt_existing(
                session,
                relative_path=relative,
                artifact_type="archive",
                mime_type="application/vnd.sqlite3",
                original_filename="ai-station.sqlite",
                run_id=run.id,
            )
            report = {
                "integrity_check": check,
                "size_bytes": sqlite.size_bytes,
                "sha256": sqlite.sha256,
                "relative_path": relative,
                "schema_revision": schema_revisions(session)[0],
                "restore": "unpublished",
                "image_rollout": "unpublished",
                "checked_at": utcnow().isoformat(),
            }
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as report_file:
                json.dump(report, report_file)
                report_file.flush()
                register_file(
                    session,
                    source=Path(report_file.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="backup-report.json",
                    run_id=run.id,
                    metadata=report,
                )
            remember_backup(session, run.id)
            append_event(session, run.id, "backup.verified", report)
            run.summary = f"SQLite backup integrity_check={check}; restore remains unpublished"
            run.metadata_json = {**run.metadata_json, "backup": report}
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=report)
            return "done"
        except Exception as exc:
            session.rollback()
            if destination is not None:
                destination.unlink(missing_ok=True)
            failed = session.get(Run, run.id)
            if failed is not None and failed.status == RunStatus.CANCEL_REQUESTED.value:
                transition(session, failed, RunStatus.CANCELED, event_type="run.canceled", payload={})
            elif failed is not None and failed.status not in TERMINAL:
                mark_failed(session, failed, type(exc).__name__, str(exc))
            return "done"


def unpublished_image_inspect(*, docker: str, runner: str, summary: str) -> dict:
    return {
        "docker": docker,
        "runner": runner,
        "tag": {"name": "ai-station:local", "present": False, "id": None, "created": None},
        "containers": [],
        "matches_running": False,
        "self_container_id": None,
        "image_rollout": "unpublished",
        "restore": "unpublished",
        "summary": summary,
    }


def mark_self_container(payload: dict) -> dict:
    hostname = (os.environ.get("HOSTNAME") or "").strip().lower()
    self_id = None
    containers = []
    for row in payload.get("containers") or []:
        item = dict(row)
        cid = str(item.get("id") or "").lower()
        name = str(item.get("name") or "").lower()
        short = cid[:12]
        is_self = len(hostname) >= 8 and (
            cid.startswith(hostname) or hostname.startswith(short) or hostname == name
        )
        item["self"] = is_self
        if is_self:
            self_id = item.get("id")
        containers.append(item)
    payload["containers"] = containers
    payload["self_container_id"] = self_id
    payload["image_rollout"] = "unpublished"
    payload["restore"] = "unpublished"
    payload["runner"] = "available"
    return payload


@router.get("")
def status(session: DB):
    return readiness(session)


@router.get("/image")
def inspect_image():
    try:
        payload = RunnerClient(timeout=15).inspect_station_image()
    except RunnerUnavailable:
        return unpublished_image_inspect(
            docker="unavailable",
            runner="unavailable",
            summary=(
                "Host Runner is unavailable, so the compose image was not inspected. "
                "Image rollout stays unpublished."
            ),
        )
    if not isinstance(payload, dict):
        return unpublished_image_inspect(
            docker="unavailable",
            runner="available",
            summary="Host Runner returned an unreadable image inspect. Image rollout stays unpublished.",
        )
    return mark_self_container(payload)


@router.post("/backups", status_code=202)
def enqueue_backup(_body: EmptyBody, session: DB):
    if session.scalar(select(Run.id).where(Run.executor_type == "sqlite_backup", Run.status.in_(ACTIVE))):
        raise HTTPException(409, "Cancel the active backup Run before starting another")
    task = create_task(
        session,
        title="SQLite backup",
        prompt="Verified copy of the application database",
        capability="station.backup",
    )
    run = create_run(
        session,
        task,
        run_type="maintenance",
        capability="station.backup",
        executor_type="sqlite_backup",
        execution_target="container",
        parameters={},
        permissions=[PERMISSION],
        retry_class="inspect",
        triggered_by="user",
    )
    session.commit()
    return run_dict(run)


@router.get("/backups")
def list_backups(session: DB):
    runs = session.scalars(
        select(Run).where(Run.executor_type == "sqlite_backup").order_by(Run.created_at.desc()).limit(20)
    ).all()
    if not runs:
        return {"items": [], "restore": "unpublished"}
    artifacts = session.scalars(select(Artifact).where(Artifact.run_id.in_([row.id for row in runs]))).all()
    by_run: dict[str, list[dict]] = {}
    for artifact in artifacts:
        by_run.setdefault(artifact.run_id, []).append(
            {
                "id": artifact.id,
                "type": artifact.artifact_type,
                "filename": artifact.original_filename,
                "size_bytes": artifact.size_bytes,
                "relative_path": artifact.relative_path,
            }
        )
    return {
        "items": [
            {**run_dict(row), "artifacts": by_run.get(row.id, []), "restore": "unpublished"} for row in runs
        ],
        "restore": "unpublished",
        "image_rollout": "unpublished",
    }


@router.get("/backups/{run_id}")
def inspect_backup(run_id: UUID, session: DB):
    run = session.get(Run, str(run_id))
    if run is None or run.executor_type != "sqlite_backup":
        raise HTTPException(404, "Backup Run not found")
    if run.status != RunStatus.SUCCEEDED.value:
        raise HTTPException(409, "Only a successful backup Run can be inspected")
    return inspect_copy(session, run)


@router.post("/interrupted/{run_id}/acknowledge")
def acknowledge_interrupted(run_id: UUID, _body: EmptyBody, session: DB):
    run = session.get(Run, str(run_id))
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.INTERRUPTED.value:
        raise HTTPException(409, "Only interrupted Runs can be marked inspected")
    if not run.metadata_json.get("inspection_acknowledged_at"):
        run.metadata_json = {
            **run.metadata_json,
            "inspection_acknowledged_at": utcnow().isoformat(),
            "replay": False,
            "restore": "unpublished",
        }
        append_event(session, run.id, "recovery.inspection_acknowledged", {"replay": False, "restore": False})
        session.commit()
    return {**run_dict(run), "replay": False, "restore": "unpublished"}
