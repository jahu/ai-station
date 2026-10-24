"""Host-side SQLite recovery helpers. Never replace a database from an HTTP worker."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

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


def schema_head() -> str:
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
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
        if revision != (schema_head(),):
            raise RecoveryError("Use an application checkout matching this backup's schema revision")
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES
        }
        missing = 0
        for (relative,) in connection.execute("SELECT relative_path FROM artifacts"):
            candidate = data_path(root, relative, required=False)
            if not candidate.exists():
                missing += 1
            else:
                regular_file(candidate)
        active = connection.execute(
            "SELECT count(*) FROM runs WHERE status NOT IN (?,?,?,?)", TERMINAL
        ).fetchone()[0]
        enabled = connection.execute("SELECT count(*) FROM agents WHERE enabled=1").fetchone()[0]
        return {
            "backup_run_id": str(UUID(backup_run_id)),
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": digest,
            "size_bytes": size,
            "schema_revision": revision[0],
            "counts": counts,
            "missing_artifact_files": missing,
            "agents_to_pause": enabled,
            "runs_requiring_inspection": active,
            "sessions_will_be_revoked": True,
            "automatic_replay": False,
            "database_only": True,
            "applied": False,
        }
