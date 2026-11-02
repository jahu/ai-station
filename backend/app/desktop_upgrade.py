"""Trusted offline installer transaction. Never an HTTP/agent execution surface."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import sqlite3
import stat
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine

from app.db import alembic_config

MARKER = "desktop-upgrade-pending.json"


def regular(path):
    value = path.lstat()
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
        or value.st_mode & 0o022
    ):
        raise ValueError("Upgrade files must be ordinary owned files without shared write access")
    return value


def directory(path, *, private=False):
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_mode & (0o077 if private else 0o022)
    ):
        raise ValueError("Upgrade storage has unsafe ownership or permissions")


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path):
    regular(path)
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write(path, value):
    if path.exists() or path.is_symlink():
        regular(path)
    fd, name = tempfile.mkstemp(prefix=".upgrade-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encode(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def read(path):
    if regular(path).st_size > 65536:
        raise ValueError("Upgrade metadata exceeded its bound")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Upgrade metadata must be an object")
    return value


def canonical_root(root):
    root = Path(root).absolute()
    if root.resolve(strict=True) != root or os.geteuid() == 0:
        raise ValueError("Use a canonical ordinary-user application data directory")
    directory(root)
    for name in ("db", "runtime"):
        directory(root / name)
    return root


@contextmanager
def guard(root):
    root = canonical_root(root)
    descriptors = []
    try:
        for name in ("launcher.lock", "migrations.lock"):
            path = root / "runtime" / name
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            descriptors.append(fd)
            regular(path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(
                    "Stop the owned station and migration before updating its database"
                ) from None
        if (root / "runtime/recovery-pending.json").exists() or (
            root / "runtime/recovery-pending.json"
        ).is_symlink():
            raise RuntimeError("Finish the pending offline recovery before upgrading")
        yield root
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def fingerprint(root):
    main = root / "db/ai-station.sqlite"
    result = {"main": digest(main)}
    for suffix in ("-wal", "-journal", "-shm"):
        path = main.with_name(main.name + suffix)
        if path.exists() or path.is_symlink():
            info = regular(path)
            if suffix != "-shm":
                result[suffix] = digest(path) if info.st_size else None
        elif suffix != "-shm":
            result[suffix] = None
    if result["-journal"] is not None:
        raise ValueError("Inspect the unfinished SQLite journal before upgrading")
    return result


def verify(path, revision=None):
    regular(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if (
            db.execute("PRAGMA integrity_check").fetchone() != ("ok",)
            or db.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            raise ValueError("Upgrade database integrity or foreign keys did not verify")
        present = db.execute("SELECT version_num FROM alembic_version").fetchall()
        if len(present) != 1 or revision is not None and present != [(revision,)]:
            raise ValueError("Upgrade database revision did not verify")
        return present[0][0]


def copy(source, destination):
    destination.touch(mode=0o600, exist_ok=False)
    created = destination.lstat()
    try:
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(destination)) as target,
        ):
            original.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        sync(destination)
        sync(destination.parent)
    except BaseException:
        current = regular(destination)
        if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
            destination.unlink()  # Only the incomplete file created by this call.
        raise


def location(root, identity, *, create=False):
    if str(UUID(identity)) != identity:
        raise ValueError("Use a canonical upgrade operation UUID")
    store = root / "desktop-upgrades"
    if create:
        store.mkdir(mode=0o700, exist_ok=True)
    directory(store, private=True)
    folder = store / identity
    if folder.exists() or folder.is_symlink():
        directory(folder, private=True)
    return folder


def pending(root, identity):
    folder = location(root, identity)
    request = read(folder / "request.json")
    marker = read(root / "runtime" / MARKER)
    state = read(folder / "state.json")
    expected = hashlib.sha256(encode(request)).hexdigest()
    if (
        request.get("operation_id") != identity
        or state.get("request_identity") != expected
        or marker
        != {
            "operation_id": identity,
            "identity": expected,
        }
    ):
        raise ValueError("The pending upgrade belongs to different input; inspect retained records")
    return folder, request, state


def report(request, state):
    return {
        "operation_id": request["operation_id"],
        "phase": state["phase"],
        "schema_before": request["schema_before"],
        "schema_after": request["schema_after"],
        "backup_relative": f"desktop-upgrades/{request['operation_id']}/original.sqlite",
        "backup_verified": bool(state.get("backup_sha256")),
    }


def status(root, identity):
    root = canonical_root(root)
    folder = location(root, identity)
    request, state = read(folder / "request.json"), read(folder / "state.json")
    if (
        request.get("operation_id") != identity
        or state.get("request_identity") != hashlib.sha256(encode(request)).hexdigest()
    ):
        raise ValueError("The recorded upgrade identity changed")
    return report(request, state)


def finished(root, identity, phase):
    root = canonical_root(root)
    marker = root / "runtime" / MARKER
    if marker.exists() or marker.is_symlink():
        return None
    result = status(root, identity)
    return result if result["phase"] == phase else None


def prepare(root, identity, previous, target):
    if (
        any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in (previous, target))
        or previous == target
    ):
        raise ValueError("Choose different verified previous and target bundle identities")
    with guard(root) as root:
        folder = location(root, identity, create=True)
        marker = root / "runtime" / MARKER
        if marker.exists() or marker.is_symlink():
            folder, request, state = pending(root, identity)
            if (
                request["previous_bundle"] != previous
                or request["target_bundle"] != target
                or request["schema_after"] != ScriptDirectory.from_config(alembic_config()).get_current_head()
            ):
                raise ValueError("Upgrade input changed; no backup or migration was repeated")
            if state["phase"] == "prepared" and fingerprint(root) == request["source"]:
                if (
                    digest(folder / "original.sqlite") != state["backup_sha256"]
                    or digest(folder / "staged.sqlite") != state["staged_sha256"]
                ):
                    raise ValueError("Prepared upgrade bytes changed")
                return report(request, state)
            raise RuntimeError("Inspect the pending upgrade; resume publication or abort before trying again")
        folder.mkdir(mode=0o700)  # A previous operation is never overwritten.
        request = {
            "operation_id": identity,
            "previous_bundle": previous,
            "target_bundle": target,
            "source": fingerprint(root),
            "schema_before": verify(root / "db/ai-station.sqlite"),
            "schema_after": ScriptDirectory.from_config(alembic_config()).get_current_head(),
        }
        write(folder / "request.json", request)
        state = {"phase": "preparing", "request_identity": hashlib.sha256(encode(request)).hexdigest()}
        write(folder / "state.json", state)
        write(marker, {"operation_id": identity, "identity": hashlib.sha256(encode(request)).hexdigest()})
        original, stage = folder / "original.sqlite", folder / "staged.sqlite"
        copy(root / "db/ai-station.sqlite", original)
        verify(original, request["schema_before"])
        state["backup_sha256"] = digest(original)
        write(folder / "state.json", state)
        copy(original, stage)
        engine = create_engine(URL.create("sqlite", database=str(stage)))
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                config = alembic_config()
                config.attributes["connection"] = connection
                command.upgrade(config, "head")  # Existing explicit staging connection contract.
        finally:
            engine.dispose()
        verify(stage, request["schema_after"])
        if fingerprint(root) != request["source"]:
            raise ValueError("The original database changed; no staged version was published")
        sync(stage)
        state.update(phase="prepared", backup_sha256=digest(original), staged_sha256=digest(stage))
        write(folder / "state.json", state)
        return report(request, state)


def publish(root, identity):
    completed = finished(root, identity, "applied")
    if completed is not None:
        return completed  # Lost acknowledgement: inspect only, never replay.
    with guard(root) as root:
        folder, request, state = pending(root, identity)
        if state["phase"] not in {"prepared", "publishing", "applied"}:
            raise ValueError("Only a fully prepared upgrade can be published")
        if digest(folder / "original.sqlite") != state["backup_sha256"]:
            raise ValueError("The retained pre-update backup changed")
        observed = fingerprint(root)
        original = request["source"]
        target = root / "db/ai-station.sqlite"
        if state["phase"] == "prepared":
            if observed != original:
                raise ValueError("Original database changed; upgrade publication was refused")
            stage = folder / "staged.sqlite"
            if digest(stage) != state["staged_sha256"]:
                raise ValueError("Staged database changed; nothing was replaced")
            verify(stage, request["schema_after"])
            state["phase"] = "publishing"
            write(folder / "state.json", state)
        if observed["main"] == state["staged_sha256"] and observed["-wal"] is None:
            verify(target, request["schema_after"])
        elif observed["main"] == original["main"] and observed["-wal"] in {original["-wal"], None}:
            stage = folder / "staged.sqlite"
            if digest(stage) != state["staged_sha256"]:
                raise ValueError("Staged database changed; nothing was replaced")
            verify(stage, request["schema_after"])
            for suffix in ("-wal", "-shm", "-journal"):
                path = target.with_name(target.name + suffix)
                if path.exists() or path.is_symlink():
                    regular(path)
                    path.unlink()
            os.replace(stage, target)
            sync(target.parent)
            verify(target, request["schema_after"])
        else:
            raise ValueError("Database changed during publication; retain the pending upgrade for inspection")
        state["phase"] = "applied"
        write(folder / "state.json", state)
        (root / "runtime" / MARKER).unlink()
        sync(root / "runtime")
        return report(request, state)


def abort(root, identity):
    completed = finished(root, identity, "aborted")
    if completed is not None:
        return completed
    with guard(root) as root:
        folder, request, state = pending(root, identity)
        if (
            state["phase"] not in {"preparing", "prepared", "aborted"}
            or fingerprint(root) != request["source"]
        ):
            raise ValueError("Publication began or data changed; do not roll back without inspection")
        state["phase"] = "aborted"
        write(folder / "state.json", state)
        (root / "runtime" / MARKER).unlink()
        sync(root / "runtime")
        return report(request, state)


def main():
    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish", "abort", "status"))
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--previous-bundle")
    parser.add_argument("--target-bundle")
    args = parser.parse_args()
    from app.config import get_settings

    os.umask(0o077)
    settings = get_settings()
    root = settings.data_dir
    if settings.sqlite_url() != f"sqlite:///{root / 'db/ai-station.sqlite'}":
        raise ValueError("Desktop upgrades require the standard app-owned SQLite database")
    if args.action == "prepare":
        result = prepare(root, args.operation_id, args.previous_bundle, args.target_bundle)
    else:
        if args.previous_bundle is not None or args.target_bundle is not None:
            parser.error("Bundle coordinates belong only to preparation")
        result = {"publish": publish, "abort": abort, "status": status}[args.action](root, args.operation_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
