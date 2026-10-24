"""Host-side SQLite recovery helpers. Never replace a database from an HTTP worker."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
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


def assert_no_database_users(root: Path) -> None:
    identities = set()
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = data_path(root, "db/ai-station.sqlite" + suffix, required=False)
        if path.exists():
            info = regular_file(path)
            identities.add((info.st_dev, info.st_ino))
    for process in Path("/proc").iterdir():
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
