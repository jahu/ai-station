"""Approved offline replacement, retained originals and durable crash recovery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from .host import assert_no_containers, assert_no_database_users, assert_no_native_groups, offline_guard
from .storage import (
    TERMINAL,
    RecoveryError,
    backup_connection,
    current_security,
    data_path,
    inspect_backup,
    migrate_copy,
    normalize_copy,
    regular_file,
    schema_head,
)


def file_hash(path: Path) -> str:
    regular_file(path)
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
        else:
            # A completed swap has no original WAL sidecars. A later writer
            # could leave new WAL transactions while preserving the main-file
            # digest; never finalize against an immutable view that hides them.
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = data_path(root, "db/ai-station.sqlite" + suffix, required=False)
                if sidecar.exists() and regular_file(sidecar).st_size:
                    raise RecoveryError(
                        "Database sidecar appeared after replacement; inspect before continuing"
                    )
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
    root: Path,
    backup_id: str,
    expected_sha256: str,
    *,
    password: str | None = None,
    legacy_owner: str | None = None,
    admin_recovery=None,
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
        if security is None and password is None and admin_recovery is None:
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
            options = {"password": password}
            if legacy_owner is not None:
                options["legacy_owner"] = legacy_owner
            if admin_recovery is not None:
                options["admin_recovery"] = admin_recovery
            actions = normalize_copy(stage, security, backup_id, **options)
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
            if target.exists() and security is not None:
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
                    try:
                        verify_standalone(rollback)
                    except RecoveryError:
                        # A damaged original is exactly why an operator may
                        # restore. Its raw bytes are retained above, but never
                        # advertise a structurally invalid rollback as usable.
                        rollback.unlink()
                    else:
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
