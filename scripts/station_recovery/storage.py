"""Read-only backup checks and private SQLite staging/normalization."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = ("succeeded", "failed", "canceled", "interrupted")
TABLES = ("tasks", "runs", "conversations", "agents", "memories", "artifacts", "projects")


class RecoveryError(ValueError):
    pass


def data_path(root: Path, relative: str, *, required=True) -> Path:
    """Existing application files must not redirect recovery through links."""
    root = root.resolve(strict=True)
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {".", ".."} for part in parts):
        raise RecoveryError("Recovery paths must stay relative to the application data directory")
    current = root
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if required:
                raise RecoveryError("Required application file is missing") from None
            continue
        if stat.S_ISLNK(info.st_mode):
            raise RecoveryError("Recovery does not follow application-file symlinks")
        if info.st_uid != os.getuid():
            raise RecoveryError("Recovery requires user-owned application files")
    return current


def regular_file(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise RecoveryError("Recovery requires an ordinary user-owned file without hard links")
    return info


def migration_config() -> Config:
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    return config


def schema_head() -> str:
    heads = ScriptDirectory.from_config(migration_config()).get_heads()
    if len(heads) != 1:
        raise RecoveryError("Recovery requires one application schema head")
    return heads[0]


def supported_revisions() -> set[str]:
    return {
        revision.revision
        for revision in ScriptDirectory.from_config(migration_config()).walk_revisions(
            base="base", head=schema_head()
        )
    }


@contextmanager
def backup_connection(root: Path, backup_run_id: str):
    backup_run_id = str(UUID(backup_run_id))
    path = data_path(root, f"backups/{backup_run_id}.sqlite")
    info = regular_file(path)
    if not info.st_size:
        raise RecoveryError("Choose a nonempty SQLite backup")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = data_path(root, f"backups/{backup_run_id}.sqlite{suffix}", required=False)
        if sidecar.exists() and sidecar.stat().st_size:
            raise RecoveryError("Choose a complete standalone SQLite backup without live sidecars")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    connection = None
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise RecoveryError("Backup identity changed during inspection")
        if os.read(fd, 16) != b"SQLite format 3\x00":
            raise RecoveryError("Backup is not a SQLite copy")
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        # A held descriptor pins the inspected inode even if the name is replaced.
        uri = "file:" + quote(f"/proc/self/fd/{fd}", safe="/") + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        yield connection, path, digest.hexdigest(), opened.st_size
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise RecoveryError("Backup bytes changed during inspection")
    except sqlite3.Error as exc:
        raise RecoveryError("Backup is not a readable, compatible SQLite copy") from exc
    finally:
        if connection is not None:
            connection.close()
        os.close(fd)


def inspect_backup(root: Path, backup_run_id: str) -> dict:
    """Read a standalone backup and its retained artifacts without creating files."""
    root = root.resolve(strict=True)
    with backup_connection(root, backup_run_id) as (connection, path, digest, size):
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RecoveryError("Backup integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RecoveryError("Backup foreign-key check failed")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        head = schema_head()
        ancestors = supported_revisions()
        if not revision or revision[0] not in ancestors:
            raise RecoveryError("Backup schema revision is not compatible with this application checkout")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] if table in tables else 0
            for table in TABLES
        }
        missing = 0
        files = connection.execute("SELECT relative_path FROM artifacts") if "artifacts" in tables else ()
        for (relative,) in files:
            candidate = data_path(root, relative, required=False)
            if not candidate.exists():
                missing += 1
            else:
                regular_file(candidate)
        active = (
            connection.execute(
                "SELECT count(*) FROM runs WHERE status NOT IN (?,?,?,?)", TERMINAL
            ).fetchone()[0]
            if "runs" in tables
            else 0
        )
        enabled = (
            connection.execute("SELECT count(*) FROM agents WHERE enabled=1").fetchone()[0]
            if "agents" in tables
            else 0
        )
        return {
            "backup_run_id": str(UUID(backup_run_id)),
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": digest,
            "size_bytes": size,
            "schema_revision": revision[0],
            "target_schema_revision": head,
            "migration_required": revision[0] != head,
            "counts": counts,
            "missing_artifact_files": missing,
            "agents_to_pause": enabled,
            "runs_requiring_inspection": active,
            "sessions_will_be_revoked": True,
            "automatic_replay": False,
            "database_only": True,
            "applied": False,
        }


def migrate_copy(path: Path) -> None:
    """Alembic receives the staging connection explicitly, never the live engine."""
    from alembic import command
    from sqlalchemy import URL, create_engine

    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def current_security(path: Path) -> dict | None:
    """Read only present credentials/rate limits; never revive older security state."""
    from contextlib import closing

    if not path.exists():
        return None
    regular_file(path)
    try:
        with closing(
            sqlite3.connect("file:" + quote(str(path), safe="/") + "?mode=ro", uri=True)
        ) as connection:
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision and revision[0] not in supported_revisions():
                raise RecoveryError(
                    "Use a checkout compatible with the current database schema before recovery"
                )
            rows = dict(
                connection.execute(
                    "SELECT key,value FROM settings WHERE key IN ('operator_auth','operator_login_budget','private_ui_access')"
                )
            )
            security = {
                key: json.loads(rows[key]) if key in rows else None
                for key in ("operator_auth", "operator_login_budget", "private_ui_access")
            }
            from station_recovery.accounts import current_authority

            security["account_authority"] = current_authority(connection)
            security["account_attempts"] = {
                key: json.loads(value)
                for key, value in connection.execute(
                    "SELECT key,value FROM settings WHERE key IN ('account_attempts:login','account_attempts:security','account_attempts:admin')"
                )
            }
            return security
    except RecoveryError:
        raise
    except (sqlite3.Error, ValueError, TypeError):
        return None


def normalize_copy(
    path: Path,
    security: dict | None,
    backup_id: str,
    *,
    password: str | None = None,
    legacy_owner: str | None = None,
    admin_recovery=None,
) -> dict:
    """A restored copy cannot resume work, schedules, sessions or invitation tokens."""
    from app.db import utcnow
    from app.events import append_event
    from app.models import (
        Agent,
        Approval,
        ResourceLock,
        Run,
        RuntimeInstance,
        Setting,
        StationNode,
        WorkerRow,
    )
    from app.operator_auth import save_secret
    from sqlalchemy import URL, create_engine, delete, select
    from sqlalchemy.orm import Session

    if password is not None and not 12 <= len(password) <= 200:
        raise RecoveryError("A new operator password must contain 12 to 200 characters")
    if security is None and password is None and admin_recovery is None:
        raise RecoveryError("Unreadable current credentials require a fresh operator password for recovery")
    engine = create_engine(URL.create("sqlite", database=str(path)))
    now = utcnow()
    actions = {
        "agents_paused": 0,
        "runs_interrupted": 0,
        "sessions_revoked": 0,
        "node_tokens_revoked": 0,
        "approvals_denied": 0,
    }
    try:
        with Session(engine) as session:
            from station_recovery.accounts import preserve_authority

            account_actions = preserve_authority(
                session,
                (security or {}).get("account_authority"),
                now,
                password=password,
                legacy_owner=legacy_owner,
                admin_recovery=admin_recovery,
            )
            for agent in session.scalars(select(Agent)):
                actions["agents_paused"] += int(agent.enabled)
                agent.enabled, agent.next_run_at, agent.updated_at = False, None, now
                if agent.last_status and agent.last_status not in TERMINAL:
                    agent.last_status = "interrupted"
            for run in session.scalars(select(Run).where(Run.status.not_in(TERMINAL))):
                previous = run.status
                run.status, run.finished_at, run.worker_id, run.lease_expires_at = (
                    "interrupted",
                    now,
                    None,
                    None,
                )
                run.retry_class = "inspect"
                run.error_type, run.error_message = (
                    "OfflineRecovery",
                    "Restored from backup; inspect before continuing. No work was replayed.",
                )
                metadata = {
                    key: value
                    for key, value in run.metadata_json.items()
                    if key != "inspection_acknowledged_at"
                }
                run.metadata_json = {
                    **metadata,
                    "offline_recovery": {"backup_run_id": backup_id, "previous_status": previous},
                }
                append_event(
                    session,
                    run.id,
                    "run.interrupted",
                    {"reason": "offline_recovery", "backup_run_id": backup_id, "previous_status": previous},
                )
                actions["runs_interrupted"] += 1
            for lock in session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))):
                lock.released_at = now
            for approval in session.scalars(select(Approval).where(Approval.resolution == "pending")):
                approval.resolution, approval.resolved_at = "denied", now
                approval.payload = {**approval.payload, "offline_recovery": {"backup_run_id": backup_id}}
                if approval.run_id:
                    append_event(
                        session,
                        approval.run_id,
                        "approval.denied",
                        {"reason": "offline_recovery", "approval_id": approval.id},
                    )
                actions["approvals_denied"] += 1
            for instance in session.scalars(select(RuntimeInstance)):
                instance.status = "stopped" if instance.ownership == "managed" else "unknown"
                instance.updated_at = now
            for node in session.scalars(select(StationNode).where(StationNode.ownership == "remote")):
                if node.token_hash:
                    actions["node_tokens_revoked"] += 1
                node.token_hash = node.token_salt = ""
                node.status, node.revoked_at = "revoked", now
            saved_private = session.get(Setting, "private_ui_access")
            backup_private = (
                dict(saved_private.value) if saved_private and isinstance(saved_private.value, dict) else {}
            )
            current_private = (security or {}).get("private_ui_access")
            private_policy = current_private if isinstance(current_private, dict) else backup_private
            private_required = (
                private_policy.get("enabled") is True or private_policy.get("password_required") is True
            )
            account_ready = bool(
                account_actions.get("accounts_preserved") or account_actions.get("administrator_recovered")
            )
            if (
                private_required
                and not (security or {}).get("operator_auth")
                and password is None
                and not account_ready
            ):
                raise RecoveryError(
                    "Private recovery requires a fresh operator password when current credentials are missing"
                )
            for setting in list(session.scalars(select(Setting))):
                if setting.key == "operator_session" or setting.key.startswith("operator_session:"):
                    session.delete(setting)
                    actions["sessions_revoked"] += 1
                elif setting.key in {
                    "operator_auth",
                    "operator_login_budget",
                    "scheduler_heartbeat",
                    "private_ui_access",
                }:
                    session.delete(setting)
            session.execute(delete(WorkerRow))
            session.flush()
            for key, value in (security or {}).items():
                if key in {"operator_auth", "operator_login_budget"} and value is not None:
                    if key == "operator_auth" and admin_recovery is not None:
                        continue
                    session.add(Setting(key=key, value=value))
            for key in ("account_attempts:login", "account_attempts:security", "account_attempts:admin"):
                previous = session.get(Setting, key)
                if previous is not None:
                    session.delete(previous)
            session.flush()
            for key, value in (security or {}).get("account_attempts", {}).items():
                if key in {"account_attempts:login", "account_attempts:security", "account_attempts:admin"}:
                    session.add(Setting(key=key, value=value))
            if backup_private or current_private:
                revisions = [p.get("revision", 0) for p in (backup_private, private_policy)]
                number = max((v for v in revisions if type(v) is int and v >= 0), default=0) + 1
                session.add(
                    Setting(
                        key="private_ui_access",
                        value={
                            "revision": number,
                            "enabled": False,
                            "origin": None,
                            "node_id": None,
                            "pending_run_id": None,
                            "password_required": private_required,
                        },
                    )
                )
            session.flush()
            if password is not None:
                save_secret(session, password)
            session.commit()
        return {
            **actions,
            **account_actions,
            "operator_password_reset": password is not None,
            "automatic_replay": False,
        }
    finally:
        engine.dispose()
