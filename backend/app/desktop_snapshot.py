"""Fixed offline DB export; native installer only, no HTTP or agent operation."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from uuid import UUID

from app import desktop_storage as storage

OUTPUT = Path("/export")


def ordinary(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o022
    ):
        os.close(fd)
        raise ValueError("Snapshot files must remain ordinary owned non-shared-write files")
    return fd


def digest(path):
    with os.fdopen(ordinary(path), "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_fixed(source, target):
    with os.fdopen(ordinary(source), "rb") as reader:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())


def export_database(value, operation, image_id):
    """Clone raw DB/WAL first; SQLite never writes to the mounted source volume."""
    if str(UUID(operation)) != operation:
        raise ValueError("Use a canonical snapshot UUID")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Snapshot provenance requires the fixed verified image ID")
    before = storage.fingerprint(value)
    if OUTPUT.resolve() != OUTPUT:
        raise ValueError("Snapshot output cannot cross a symlink")
    fd = os.open(OUTPUT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077 or os.listdir(fd):
            raise ValueError("Snapshot output must be a new empty private owned directory")
    finally:
        os.close(fd)
    # One private helper owns this fresh clone. Shared-host SQLite is not used
    # for interprocess coordination; source exclusion is proved by the native owner.
    stage = OUTPUT / "staging"
    stage.mkdir(mode=0o700)
    source = storage.ROOT / "ai-station.sqlite"
    clone = stage / source.name
    copy_fixed(source, clone)
    if before["database"]["-wal"] is not None:
        copy_fixed(source.with_name(source.name + "-wal"), clone.with_name(clone.name + "-wal"))
    if digest(clone) != before["database"]["main"]:
        raise ValueError("Database changed while cloning the snapshot")
    if (
        before["database"]["-wal"] is not None
        and digest(clone.with_name(clone.name + "-wal")) != before["database"]["-wal"]
    ):
        raise ValueError("WAL changed while cloning the snapshot")
    if storage.fingerprint(value) != before:
        raise ValueError("Database bytes changed during snapshot preparation")
    target = OUTPUT / "database.sqlite"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(clone)) as original, closing(sqlite3.connect(target)) as destination:
        original.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
        if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Snapshot database integrity check failed")
        if destination.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Snapshot database foreign-key check failed")
        revision = destination.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(revision) != 1 or not isinstance(revision[0][0], str):
            raise ValueError("Snapshot database has no unambiguous schema revision")
    with os.fdopen(ordinary(target), "rb") as completed:
        os.fsync(completed.fileno())
    if storage.fingerprint(value) != before:
        raise ValueError("Database changed before export publication")
    report = {
        "schema": 1,
        "operation_id": operation,
        "image_id": image_id,
        "storage": value,
        "source": before["database"],
        "database_sha256": digest(target),
        "database_bytes": target.stat().st_size,
        "database_revision": revision[0][0],
    }
    # Remove only our fixed staging names, never a recursive arbitrary tree.
    for name in (source.name, source.name + "-wal", source.name + "-shm", source.name + "-journal"):
        (stage / name).unlink(missing_ok=True)
    stage.rmdir()
    sync_directory(OUTPUT)
    encoded = json.dumps(report, sort_keys=True).encode() + b"\n"
    descriptor = os.open(OUTPUT / "receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as receipt:
        receipt.write(encoded)
        receipt.flush()
        os.fsync(receipt.fileno())
    sync_directory(OUTPUT)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export",))
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    args = parser.parse_args()
    value = storage.binding(args.storage_id, args.namespace, args.uid, args.gid)
    print(json.dumps(export_database(value, args.operation_id, args.image_id), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
