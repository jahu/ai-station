"""Host-side SQLite recovery helpers. Never replace a database from an HTTP worker."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent
MAX_BACKUP_BYTES = 512 * 1024 * 1024
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


@contextmanager
def backup_connection(root: Path, backup_run_id: str):
    backup_run_id = str(UUID(backup_run_id))
    path = data_path(root, f"backups/{backup_run_id}.sqlite")
    info = regular_file(path)
    if not 0 < info.st_size <= MAX_BACKUP_BYTES:
        raise RecoveryError("Backup must contain 1 byte to 512 MiB")
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
        ancestors = {
            r.revision
            for r in ScriptDirectory.from_config(migration_config()).walk_revisions(base="base", head=head)
        }
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
            rows = dict(
                connection.execute(
                    "SELECT key,value FROM settings WHERE key IN ('operator_auth','operator_login_budget')"
                )
            )
            return {
                key: json.loads(rows[key]) if key in rows else None
                for key in ("operator_auth", "operator_login_budget")
            }
    except (sqlite3.Error, ValueError, TypeError):
        return None


def normalize_copy(path: Path, security: dict | None, backup_id: str, *, password: str | None = None) -> dict:
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
    if security is None and password is None:
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
            for setting in list(session.scalars(select(Setting))):
                if setting.key == "operator_session" or setting.key.startswith("operator_session:"):
                    session.delete(setting)
                    actions["sessions_revoked"] += 1
                elif setting.key in {"operator_auth", "operator_login_budget", "scheduler_heartbeat"}:
                    session.delete(setting)
            session.execute(delete(WorkerRow))
            session.flush()
            for key, value in (security or {}).items():
                if key in {"operator_auth", "operator_login_budget"} and value is not None:
                    session.add(Setting(key=key, value=value))
            session.flush()
            if password is not None:
                save_secret(session, password)
            session.commit()
        return {**actions, "operator_password_reset": password is not None, "automatic_replay": False}
    finally:
        engine.dispose()


def assert_no_containers(root: Path) -> None:
    """Inspect mounts, not project names that an accidentally changed env can hide."""
    try:
        listing = subprocess.run(
            ["docker", "ps", "--all", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        ids = listing.stdout.split()
        if not ids:
            return
        if len(ids) > 256:
            raise RecoveryError("Container inventory exceeds the recovery inspection bound")
        template = '{"State":{"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},"Restarting":{{json .State.Restarting}}},"Mounts":{{json .Mounts}}}'
        inspected = subprocess.run(
            ["docker", "inspect", "--format", template, *ids],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if len(inspected.stdout.encode()) > 4 * 1024 * 1024:
            raise RecoveryError("Container inventory exceeds the recovery inspection bound")
        # Request only state/mount metadata, never unrelated container secrets.
        containers = [json.loads(line) for line in inspected.stdout.splitlines() if line.strip()]
    except RecoveryError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryError("Docker inspection must succeed before offline recovery") from exc
    for container in containers:
        state = container.get("State", {})
        if not any(state.get(key) for key in ("Running", "Paused", "Restarting")):
            continue
        for mount in container.get("Mounts", []):
            if not mount.get("Source"):
                continue
            source = Path(mount["Source"]).resolve()
            if source == root or source in root.parents or root in source.parents:
                raise RecoveryError(
                    "Stop containers using this data directory, including owned models and previews"
                )


def assert_no_native_groups(root: Path) -> None:
    from ai_station_runner.processes import _group_alive

    journal = data_path(root, "runtime/processes.json", required=False)
    if not journal.exists():
        return
    if regular_file(journal).st_size > 16 * 1024 * 1024:
        raise RecoveryError("Native process inventory exceeds its recovery bound")
    try:
        records = json.loads(journal.read_bytes())
        if not isinstance(records, dict):
            raise ValueError("Invalid process inventory")
        for record in records.values():
            if not isinstance(record, dict) or not record.get("boot_id") or not record.get("start_ticks"):
                raise ValueError("Unconfirmed process identity")
            if _group_alive(record):
                raise RecoveryError("Stop the owned native workload before restoring its database")
    except RecoveryError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("Native process ownership must be inspected before recovery") from exc


def process_entries():
    return Path("/proc").iterdir()


def assert_no_database_users(root: Path) -> None:
    identities = set()
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = data_path(root, "db/ai-station.sqlite" + suffix, required=False)
        if path.exists():
            info = regular_file(path)
            identities.add((info.st_dev, info.st_ino))
    for process in process_entries():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            for descriptor in (process / "fd").iterdir():
                try:
                    info = descriptor.stat()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if (info.st_dev, info.st_ino) in identities:
                    raise RecoveryError("An application database connection is still open")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            # Protected desktop/PAM processes are not SQLite executors in this
            # architecture. Owned Chromium jobs are covered by the preceding
            # container and native-group guards. Do not require stopping the
            # operator's desktop merely because its descriptors are private.
            try:
                if (process / "comm").read_text().strip() in {
                    "(sd-pam)",
                    "systemd",
                    "chrome",
                    "chromium",
                    "chromium-browser",
                }:
                    continue
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError:
                pass
            raise RecoveryError(
                f"Open database users could not be confirmed for PID {process.name}; recovery stays offline"
            ) from exc


@contextmanager
def offline_guard(root: Path):
    """Cooperate with normal startup; no process/container is stopped by recovery."""
    root = root.resolve(strict=True)
    path = data_path(root, "runtime/launcher.lock", required=False)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_uid != os.getuid():
            raise RecoveryError("Recovery requires the ordinary user-owned launcher lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("Stop the AI Station supervisor before restoring its database") from exc
        assert_no_containers(root)
        assert_no_native_groups(root)
        assert_no_database_users(root)
        yield
    finally:
        os.close(fd)


def file_hash(path: Path) -> str:
    if regular_file(path).st_size > MAX_BACKUP_BYTES:
        raise RecoveryError("Recovery file exceeds its size bound")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def read_private_json(path: Path) -> dict:
    info = regular_file(path)
    if info.st_size > 64 * 1024 or info.st_mode & 0o077:
        raise RecoveryError("Recovery records require bounded private user-owned files")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Invalid recovery record")
        return value
    except (ValueError, UnicodeError) as exc:
        raise RecoveryError("Recovery record is unreadable; inspect it before continuing") from exc


def owned_directory(root: Path, relative: str) -> Path:
    path = data_path(root, relative, required=False)
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise RecoveryError("Recovery requires application-owned directories")
    return path


def copy_private(source: Path, destination: Path) -> None:
    expected = file_hash(source)
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        target_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(target_fd, "wb") as target, os.fdopen(source_fd, "rb", closefd=False) as original:
            shutil.copyfileobj(original, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
    finally:
        os.close(source_fd)
    if file_hash(destination) != expected or file_hash(source) != expected:
        raise RecoveryError("Source bytes changed while preserving the original database")


def verify_standalone(path: Path, *, normalized=False) -> None:
    from contextlib import closing

    uri = "file:" + quote(str(path), safe="/") + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RecoveryError("Staged recovery integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RecoveryError("Staged recovery foreign-key check failed")
        if normalized:
            if connection.execute("SELECT version_num FROM alembic_version").fetchone() != (schema_head(),):
                raise RecoveryError("Staged recovery schema did not reach the expected revision")
            active = connection.execute(
                "SELECT count(*) FROM runs WHERE status NOT IN (?,?,?,?)", TERMINAL
            ).fetchone()[0]
            agents = connection.execute("SELECT count(*) FROM agents WHERE enabled=1").fetchone()[0]
            pending = connection.execute(
                "SELECT count(*) FROM approvals WHERE resolution='pending'"
            ).fetchone()[0]
            if active or agents or pending:
                raise RecoveryError("Staged recovery must not resume work, agents or approvals")


def checkpoint(path: Path, *, allow_corrupt=False) -> None:
    from contextlib import closing

    if not path.exists():
        return
    try:
        with closing(
            sqlite3.connect("file:" + quote(str(path), safe="/") + "?mode=rw", uri=True, timeout=1)
        ) as connection:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row and row[0]:
                raise RecoveryError("Database is still locked; recovery did not replace it")
            connection.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if not allow_corrupt or code not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            raise RecoveryError("Database could not be confirmed offline for recovery") from exc


def receipt_identity(report: dict) -> str:
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"phase", "applied", "finished_at", "aborted_at"}
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def current_fingerprint(root: Path) -> dict:
    main = data_path(root, "db/ai-station.sqlite", required=False)
    wal = data_path(root, "db/ai-station.sqlite-wal", required=False)
    return {
        "main": file_hash(main) if main.exists() else None,
        "wal": file_hash(wal) if wal.exists() and wal.stat().st_size else None,
    }


def _finish_prepared(root: Path, recovery_id: str, *, abort=False) -> dict:
    recovery_id = str(UUID(recovery_id))
    pending_path = data_path(root, "runtime/recovery-pending.json")
    pending = read_private_json(pending_path)
    if pending.get("recovery_id") != recovery_id:
        raise RecoveryError("Recovery identity differs from the pending operation")
    receipt_path = data_path(root, f"recovery/{recovery_id}/receipt.json")
    report = read_private_json(receipt_path)
    if report.get("recovery_id") != recovery_id or receipt_identity(report) != pending.get("identity_sha256"):
        raise RecoveryError("Recovery record changed after its original approval")
    target = data_path(root, "db/ai-station.sqlite", required=False)
    current_hash = file_hash(target) if target.exists() else None
    if abort:
        if current_hash != report["original_main_sha256"]:
            raise RecoveryError(
                "Recovery already applied or database changed; inspect the retained rollback copy"
            )
        report.update(phase="aborted", applied=False, aborted_at=datetime.now(UTC).isoformat())
    else:
        if current_hash != report["staged_sha256"]:
            stage_relative = f"db/.restore-{recovery_id}.sqlite"
            stage = data_path(root, stage_relative)
            if (
                report["stage_relative"] != stage_relative
                or current_hash != report["original_main_sha256"]
                or file_hash(stage) != report["staged_sha256"]
            ):
                raise RecoveryError("Prepared recovery changed; no database was replaced")
            verify_standalone(stage, normalized=True)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = data_path(root, "db/ai-station.sqlite" + suffix, required=False)
                if sidecar.exists():
                    if file_hash(sidecar) != report["replace_sidecars"].get(suffix):
                        raise RecoveryError("Database sidecar changed; inspect before continuing")
                    sidecar.unlink()
            os.replace(stage, target)
            sync_directory(target.parent)
        verify_standalone(target, normalized=True)
        report.update(phase="applied", applied=True, finished_at=datetime.now(UTC).isoformat())
    private_json(receipt_path, report)
    if abort:
        stage = data_path(root, f"db/.restore-{recovery_id}.sqlite", required=False)
        if stage.exists():
            if file_hash(stage) != report["staged_sha256"]:
                raise RecoveryError("Prepared staging copy changed; inspect before cleanup")
            stage.unlink()
    pending_path.unlink()
    sync_directory(pending_path.parent)
    return report


def resume_recovery(root: Path, recovery_id: str, *, abort=False) -> dict:
    root = root.resolve(strict=True)
    with offline_guard(root):
        return _finish_prepared(root, recovery_id, abort=abort)


def restore_database(
    root: Path, backup_id: str, expected_sha256: str, *, password: str | None = None
) -> dict:
    from contextlib import closing

    root = root.resolve(strict=True)
    inspected = inspect_backup(root, backup_id)
    if expected_sha256 != inspected["sha256"]:
        raise RecoveryError("Backup digest changed; inspect the intended copy again before applying it")
    if inspected["missing_artifact_files"]:
        raise RecoveryError("The SQLite copy needs its original application artifact files before recovery")
    with offline_guard(root):
        pending_path = data_path(root, "runtime/recovery-pending.json", required=False)
        if pending_path.exists():
            raise RecoveryError("Finish or abort the existing pending recovery before starting another")
        target = data_path(root, "db/ai-station.sqlite", required=False)
        security = current_security(target)
        baseline = current_fingerprint(root)
        if security is None and password is None:
            raise RecoveryError(
                "Unreadable current credentials require a fresh operator password for recovery"
            )
        original_files = [
            data_path(root, "db/ai-station.sqlite" + suffix, required=False)
            for suffix in ("", "-wal", "-shm", "-journal")
        ]
        required_bytes = (
            3 * (inspected["size_bytes"] + sum(p.stat().st_size for p in original_files if p.exists()))
            + 64 * 1024 * 1024
        )
        if shutil.disk_usage(root).free < required_bytes:
            raise RecoveryError("Recovery needs space for staging and retained original database copies")
        recovery_id = str(uuid4())
        owned_directory(root, "db")
        owned_directory(root, "recovery")
        folder = owned_directory(root, f"recovery/{recovery_id}")
        stage = data_path(root, f"db/.restore-{recovery_id}.sqlite", required=False)
        stage_fd = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(stage_fd)
        prepared = False
        try:
            with backup_connection(root, backup_id) as (source, _, digest, _):
                if digest != expected_sha256:
                    raise RecoveryError("Backup changed before staging")
                with closing(sqlite3.connect(stage)) as staged:
                    source.backup(staged)
            migrate_copy(stage)
            actions = normalize_copy(stage, security, backup_id, password=password)
            checkpoint(stage)
            verify_standalone(stage, normalized=True)
            if current_fingerprint(root) != baseline:
                raise RecoveryError("Current database changed during preparation; no restore was applied")
            for original in original_files:
                if original.exists():
                    copy_private(
                        original,
                        folder / ("original.sqlite" + original.name.removeprefix("ai-station.sqlite")),
                    )
            rollback_id = None
            if target.exists():
                rollback = data_path(root, f"backups/{recovery_id}.sqlite", required=False)
                fd = os.open(rollback, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                try:
                    with (
                        closing(
                            sqlite3.connect("file:" + quote(str(target), safe="/") + "?mode=ro", uri=True)
                        ) as current,
                        closing(sqlite3.connect(rollback)) as saved,
                    ):
                        current.backup(saved)
                    checkpoint(rollback)
                    verify_standalone(rollback)
                    rollback_id = recovery_id
                except sqlite3.Error as exc:
                    if getattr(exc, "sqlite_errorcode", 0) & 0xFF not in {
                        sqlite3.SQLITE_CORRUPT,
                        sqlite3.SQLITE_NOTADB,
                    }:
                        raise RecoveryError("Original database could not be preserved for rollback") from exc
                    rollback.unlink(missing_ok=True)
            assert_no_containers(root)
            assert_no_native_groups(root)
            assert_no_database_users(root)
            if current_fingerprint(root) != baseline:
                raise RecoveryError("Current database changed while preserving its rollback copy")
            checkpoint(target, allow_corrupt=True)
            sidecars = {
                suffix: file_hash(p)
                for suffix in ("-wal", "-shm", "-journal")
                if (p := data_path(root, "db/ai-station.sqlite" + suffix, required=False)).exists()
            }
            report = {
                **inspected,
                "recovery_id": recovery_id,
                "phase": "prepared",
                "applied": False,
                "created_at": datetime.now(UTC).isoformat(),
                "stage_relative": stage.relative_to(root).as_posix(),
                "staged_sha256": file_hash(stage),
                "original_main_sha256": file_hash(target) if target.exists() else None,
                "replace_sidecars": sidecars,
                "rollback_backup_id": rollback_id,
                "actions": actions,
                "original_files": {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()},
            }
            private_json(folder / "receipt.json", report)
            private_json(
                pending_path, {"recovery_id": recovery_id, "identity_sha256": receipt_identity(report)}
            )
            prepared = True
            return _finish_prepared(root, recovery_id)
        finally:
            if not prepared and not pending_path.exists():
                for suffix in ("", "-wal", "-shm", "-journal"):
                    p = Path(str(stage) + suffix)
                    if p.exists():
                        regular_file(p)
                        p.unlink()


def pending_recovery(root: Path) -> dict:
    marker = read_private_json(data_path(root, "runtime/recovery-pending.json"))
    recovery_id = str(UUID(marker["recovery_id"]))
    report = read_private_json(data_path(root, f"recovery/{recovery_id}/receipt.json"))
    if receipt_identity(report) != marker.get("identity_sha256"):
        raise RecoveryError("Pending recovery record changed; inspect it before continuing")
    return report


def uuid_argument(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use the UUID shown in backup or recovery history") from exc


def password_from_file(path: Path) -> str:
    path = path.expanduser().resolve(strict=True)
    info = regular_file(path)
    if info.st_mode & 0o077 or info.st_size > 1024:
        raise RecoveryError("The operator password file must be private (0600) and contain one password")
    try:
        password = path.read_text(encoding="utf-8").rstrip("\r\n")
    except UnicodeError as exc:
        raise RecoveryError("The private password file must contain UTF-8 text") from exc
    if not 12 <= len(password) <= 200 or "\n" in password or "\r" in password:
        raise RecoveryError("The private password file must contain one password of 12 to 200 characters")
    return password


def main(argv=None) -> int:
    from dotenv import dotenv_values
    from sqlalchemy.exc import SQLAlchemyError

    parser = argparse.ArgumentParser(
        description="Inspect a SQLite backup or explicitly restore it while AI Station is stopped."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backup-run", type=uuid_argument, help="Inspect this application-owned backup UUID")
    mode.add_argument("--finish", type=uuid_argument, help="Finish an approved, interrupted recovery")
    mode.add_argument(
        "--abort",
        type=uuid_argument,
        help="Abort a prepared recovery only while the original database remains",
    )
    mode.add_argument(
        "--pending", action="store_true", help="Inspect the pending recovery without changing files"
    )
    parser.add_argument("--data-root", type=Path, help="Override the configured application data directory")
    parser.add_argument(
        "--apply", action="store_true", help="Explicitly apply the inspected backup; default is read-only"
    )
    parser.add_argument("--expected-sha256", help="The exact backup digest you reviewed before --apply")
    parser.add_argument(
        "--operator-password-file",
        type=Path,
        help="Private new-password file, required when current credentials cannot be read",
    )
    args = parser.parse_args(argv)
    if args.apply and (not args.backup_run or not args.expected_sha256):
        parser.error("--apply requires --backup-run and its reviewed --expected-sha256")
    if (args.expected_sha256 or args.operator_password_file) and not args.apply:
        parser.error("--expected-sha256 and --operator-password-file require --apply")
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "host-runner")]
    configuration = {**dotenv_values(ROOT / ".env"), **os.environ}
    root = args.data_root or Path(configuration.get("AI_STATION_DATA_HOST_PATH") or ROOT / "data")
    root = root.expanduser()
    if not root.is_absolute():
        root = ROOT / root
    try:
        root = root.resolve(strict=True)
        # Pure domain helpers must resolve any settings against this explicit
        # host data root, including when invoked from an isolated checkout.
        os.environ["AI_STATION_DATA_DIR"] = str(root)
        if args.pending:
            result = pending_recovery(root)
        elif args.finish or args.abort:
            result = resume_recovery(root, args.finish or args.abort, abort=bool(args.abort))
        elif not args.apply:
            result = inspect_backup(root, args.backup_run)
        else:
            password = (
                password_from_file(args.operator_password_file) if args.operator_password_file else None
            )
            current = data_path(root, "db/ai-station.sqlite", required=False)
            if current_security(current) is None and password is None and sys.stdin.isatty():
                password = getpass.getpass("New operator password (current credentials are unreadable): ")
                if password != getpass.getpass("Confirm new operator password: "):
                    raise RecoveryError("New operator passwords did not match")
            result = restore_database(root, args.backup_run, args.expected_sha256, password=password)
        print(json.dumps({"data_root": str(root), **result}, indent=2, ensure_ascii=False))
        return 0
    except RecoveryError as exc:
        print(
            json.dumps({"error": str(exc), "inspect_pending": "./scripts/restore.sh --pending"}),
            file=sys.stderr,
        )
    except (OSError, ValueError, KeyError, sqlite3.Error, SQLAlchemyError):
        print(
            json.dumps(
                {
                    "error": "Recovery could not confirm local files or database state. Inspect before continuing.",
                    "inspect_pending": "./scripts/restore.sh --pending",
                }
            ),
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
