"""Fixed image-local restoration transaction; no HTTP/Runner or native SQL entry."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID

from app import desktop_snapshot as snapshot
from app import desktop_storage as storage
from app import desktop_upgrade as upgrade

INPUT = Path("/restore/database.sqlite")
AUTHORITY = Path("/recovery-authority/administrator.json")
MARKER = ".ai-station-restore-pending.json"
STORE = "desktop-restores"
PHASES = {"preparing", "prepared", "publishing", "applied", "aborted"}


def recovery():
    # Only pure, fixed recovery helpers are packaged here, never host Docker/proc
    # guards. Their repository-relative migration root becomes /app in the image.
    path = str(Path(__file__).resolve().parents[2] / "desktop")
    if path not in sys.path:
        sys.path.insert(0, path)
    from station_recovery import accounts
    from station_recovery import storage as helpers

    return accounts, helpers


def identity(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Use a canonical restore UUID")
    return value


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("A fixed restore SHA256 is required")
    return value


def encoded_hash(value):
    return hashlib.sha256(upgrade.encode(value)).hexdigest()


def private_read(path):
    if upgrade.regular(path).st_mode & 0o077:
        raise ValueError("Restore journals must remain private owned files")
    return upgrade.read(path)


@contextmanager
def guard(value):
    storage.inspect(value)
    if storage.ROOT.resolve() != storage.ROOT:
        raise ValueError("The restore volume cannot be redirected")
    path = storage.ROOT / ".desktop-restore.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        before = upgrade.regular(path)
        opened = os.fstat(fd)
        if before.st_mode & 0o077 or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Restore lock ownership changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another offline restore helper is active") from None
        yield
    finally:
        os.close(fd)


def folder(operation, *, create=False):
    identity(operation)
    parent = storage.ROOT / STORE
    if create:
        parent.mkdir(mode=0o700, exist_ok=True)
    upgrade.directory(parent, private=True)
    path = parent / operation
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    upgrade.directory(path, private=True)
    if path.resolve() != path:
        raise ValueError("Restore staging cannot cross a symlink")
    return path


def copy_raw(source, target, expected):
    if snapshot.digest(source) != expected:
        raise ValueError("Restore input bytes changed before copying")
    if target.exists() or target.is_symlink():
        if snapshot.digest(target) != expected:
            raise ValueError("Retained restore bytes changed")
        return
    scratch = target.with_name(target.name + ".part")
    if scratch.exists() or scratch.is_symlink():
        upgrade.regular(scratch)
        scratch.unlink()  # Fixed unpublished scratch of this journaled operation.
    snapshot.copy_fixed(source, scratch)
    if snapshot.digest(scratch) != expected or snapshot.digest(source) != expected:
        raise ValueError("Restore input bytes changed while copying")
    os.replace(scratch, target)
    upgrade.sync(target.parent)


def administrator(enabled):
    if type(enabled) is not bool:
        raise ValueError("Choose an explicit administrator recovery policy")
    if not enabled:
        return None
    value = private_read(AUTHORITY)
    if (
        set(value) != {"username", "password", "reset_mfa"}
        or value["reset_mfa"] is not True
        or not isinstance(value["username"], str)
        or not isinstance(value["password"], str)
        or not 12 <= len(value["password"]) <= 200
    ):
        raise ValueError("Administrator recovery requires an explicit private MFA reset request")
    from app.account_credentials import username_identity

    username_identity(value["username"])
    accounts, _ = recovery()
    return accounts.AdminRecovery(username=value["username"], password=value["password"], reset_mfa=True)


def check_stage(path, revision):
    import sqlite3

    upgrade.verify(path, revision)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        if (
            db.execute("SELECT count(*) FROM agents WHERE enabled=1").fetchone()[0]
            or db.execute("SELECT count(*) FROM approvals WHERE resolution='pending'").fetchone()[0]
            or db.execute(
                "SELECT count(*) FROM runs WHERE status NOT IN ('succeeded','failed','canceled','interrupted')"
            ).fetchone()[0]
        ):
            raise ValueError("Restored work, schedules and approvals must remain stopped")


def load(value, operation, image_id):
    path = folder(operation)
    request, state = (private_read(path / name) for name in ("request.json", "state.json"))
    if (
        set(request)
        != {
            "schema",
            "operation_id",
            "backup_id",
            "snapshot_identity",
            "database_sha256",
            "image_id",
            "storage",
            "source",
            "schema_after",
            "administrator",
        }
        or type(request["schema"]) is not int
        or request["schema"] != 1
        or request["operation_id"] != operation
        or request["image_id"] != image_id
        or request["storage"] != value
        or not isinstance(state, dict)
        or state.get("request_sha256") != encoded_hash(request)
        or state.get("phase") not in PHASES
    ):
        raise ValueError("The private restore transaction binding changed")
    identity(request["backup_id"])
    for key in ("snapshot_identity", "database_sha256"):
        sha(request[key])
    source = request["source"]
    if (
        not isinstance(source, dict)
        or set(source) != {"main", "-wal", "-journal"}
        or source["-journal"] is not None
    ):
        raise ValueError("The restore source fingerprint changed")
    sha(source["main"])
    if source["-wal"] is not None:
        sha(source["-wal"])
    return path, request, state


def marker(request):
    return {"schema": 1, "operation_id": request["operation_id"], "request_sha256": encoded_hash(request)}


def require_marker(request, *, create=False):
    path = storage.ROOT / MARKER
    if path.exists() or path.is_symlink():
        if private_read(path) != marker(request):
            raise ValueError("Another restore transaction is pending")
    elif create:
        upgrade.write(path, marker(request))
    else:
        raise ValueError("The pending restore marker is missing")


def report(request, state):
    return {
        "schema": 1,
        "operation_id": request["operation_id"],
        "backup_id": request["backup_id"],
        "snapshot_identity": request["snapshot_identity"],
        "image_id": request["image_id"],
        "storage": request["storage"],
        "source": request["source"],
        "phase": state["phase"],
        "database_revision": request["schema_after"],
        "database_sha256": state.get("staged_sha256"),
        "actions": state.get("actions"),
    }


def finish(request, state):
    path = storage.ROOT / MARKER
    if path.exists() or path.is_symlink():
        require_marker(request)
        current = storage.fingerprint(request["storage"])["database"]
        expected = (
            {"main": state["staged_sha256"], "-wal": None, "-journal": None}
            if state["phase"] == "applied"
            else request["source"]
        )
        if current != expected:
            raise ValueError("Database changed before restore completion; retain the pending marker")
        path.unlink()
        upgrade.sync(storage.ROOT)
    return report(request, state)


def prepare(
    value, operation, backup_id, snapshot_identity, database_sha256, image_id, *, recover_admin=False
):
    identity(operation)
    identity(backup_id)
    sha(snapshot_identity)
    sha(database_sha256)
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Restore requires the fixed verified image identity")
    recovery_request = administrator(recover_admin)
    _, helpers = recovery()
    with guard(value):
        parent = folder(operation, create=True)
        request_path, state_path = parent / "request.json", parent / "state.json"
        if request_path.exists() or request_path.is_symlink():
            request = private_read(request_path)
            if any(
                request.get(key) != item
                for key, item in {
                    "backup_id": backup_id,
                    "snapshot_identity": snapshot_identity,
                    "database_sha256": database_sha256,
                    "operation_id": operation,
                    "image_id": image_id,
                    "storage": value,
                    "schema_after": helpers.schema_head(),
                }.items()
            ):
                raise ValueError("Restore input changed; the original operation was not replayed")
            admin = request.get("administrator")
            if (admin is None) != (recovery_request is None):
                raise ValueError("The administrator recovery policy changed")
            if recovery_request is not None:
                from app.account_credentials import password_matches

                if (
                    not isinstance(admin, dict)
                    or admin.get("username") != recovery_request.username
                    or not password_matches(admin.get("verifier"), recovery_request.password)
                ):
                    raise ValueError("The private administrator recovery request changed")
            if not state_path.exists() and not state_path.is_symlink():
                upgrade.write(state_path, {"phase": "preparing", "request_sha256": encoded_hash(request)})
            parent, request, state = load(value, operation, image_id)
            if state["phase"] in {"applied", "aborted"}:
                return finish(request, state)
            if state["phase"] == "prepared":
                require_marker(request)
                if (
                    storage.fingerprint(value)["database"] != request["source"]
                    or snapshot.digest(parent / "staged.sqlite") != state["staged_sha256"]
                ):
                    raise ValueError("Prepared restore bytes changed")
                check_stage(parent / "staged.sqlite", request["schema_after"])
                return report(request, state)
            if state["phase"] != "preparing":
                raise ValueError("Restore publication started; inspect/resume it before preparation")
        else:
            existing = storage.ROOT / MARKER
            if existing.exists() or existing.is_symlink():
                raise ValueError("Another restore transaction is pending")
            authority = None
            if recovery_request is not None:
                from app.account_credentials import make_password_record

                authority = {
                    "username": recovery_request.username,
                    "verifier": make_password_record(recovery_request.password),
                }
            request = {
                "schema": 1,
                "operation_id": operation,
                "backup_id": backup_id,
                "snapshot_identity": snapshot_identity,
                "database_sha256": database_sha256,
                "image_id": image_id,
                "storage": value,
                "source": storage.fingerprint(value)["database"],
                "schema_after": helpers.schema_head(),
                "administrator": authority,
            }
            upgrade.write(request_path, request)
            state = {"phase": "preparing", "request_sha256": encoded_hash(request)}
            upgrade.write(state_path, state)
        require_marker(request, create=True)
        if storage.fingerprint(value)["database"] != request["source"]:
            raise ValueError("The current database changed during restore preparation")
        if INPUT.resolve() != INPUT or snapshot.digest(INPUT) != database_sha256:
            raise ValueError("The selected standalone backup bytes changed")
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = INPUT.with_name(INPUT.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise ValueError("Restore requires a standalone backup without sidecars")
        sizes = sum(
            upgrade.regular(storage.ROOT / ("ai-station.sqlite" + suffix)).st_size
            for suffix, expected in (("", request["source"]["main"]), ("-wal", request["source"]["-wal"]))
            if expected is not None
        )
        if shutil.disk_usage(storage.ROOT).free < 3 * (sizes + upgrade.regular(INPUT).st_size) + 64 * 1024**2:
            raise ValueError("Restore needs space for staging and retained original database copies")
        current = parent / "authority"
        current.mkdir(mode=0o700, exist_ok=True)
        upgrade.directory(current, private=True)
        for suffix, expected in (("", request["source"]["main"]), ("-wal", request["source"]["-wal"])):
            if expected is not None:
                copy_raw(
                    storage.ROOT / ("ai-station.sqlite" + suffix),
                    parent / ("original.sqlite" + suffix),
                    expected,
                )
                copy_raw(
                    parent / ("original.sqlite" + suffix), current / ("ai-station.sqlite" + suffix), expected
                )
        security = helpers.current_security(current / "ai-station.sqlite")
        if security is None and recovery_request is None:
            raise ValueError("Unreadable current authority requires explicit administrator recovery")
        stage = parent / "staged.sqlite"
        # Only unpublished, operation-owned scratch may be reconstructed.
        for suffix in ("", "-wal", "-shm", "-journal"):
            scratch = stage.with_name(stage.name + suffix)
            if scratch.exists() or scratch.is_symlink():
                upgrade.regular(scratch)
                scratch.unlink()
        copy_raw(INPUT, stage, database_sha256)
        helpers.migrate_copy(stage)
        actions = helpers.normalize_copy(stage, security, backup_id, admin_recovery=recovery_request)
        # Normalize the private stage into one standalone file before hashing.
        import sqlite3

        with closing(sqlite3.connect(stage)) as db:
            if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise ValueError("The restored staging database is still busy")
            db.execute("PRAGMA journal_mode=DELETE")
        check_stage(stage, request["schema_after"])
        upgrade.sync(stage)
        upgrade.sync(parent)
        if (
            storage.fingerprint(value)["database"] != request["source"]
            or snapshot.digest(INPUT) != database_sha256
        ):
            raise ValueError("Restore inputs changed before preparation completed")
        state.update(phase="prepared", staged_sha256=snapshot.digest(stage), actions=actions)
        upgrade.write(state_path, state)
        return report(request, state)


def publish(value, operation, image_id):
    with guard(value):
        parent, request, state = load(value, operation, image_id)
        if state["phase"] == "applied":
            return finish(request, state)
        if state["phase"] not in {"prepared", "publishing"}:
            raise ValueError("Only a fully prepared restore can be published")
        require_marker(request)
        for suffix, expected in (("", request["source"]["main"]), ("-wal", request["source"]["-wal"])):
            if expected is not None and snapshot.digest(parent / ("original.sqlite" + suffix)) != expected:
                raise ValueError("The retained original restore bytes changed")
        observed = storage.fingerprint(value)["database"]
        stage, target = parent / "staged.sqlite", storage.ROOT / "ai-station.sqlite"
        if state["phase"] == "prepared":
            if observed != request["source"]:
                raise ValueError("Current database changed; restore publication refused")
            if snapshot.digest(stage) != state["staged_sha256"]:
                raise ValueError("Prepared restore bytes changed")
            check_stage(stage, request["schema_after"])
            upgrade.require_atomic_stage(stage, target)
            state["phase"] = "publishing"
            upgrade.write(parent / "state.json", state)
        if observed["main"] == state["staged_sha256"] and observed["-wal"] is None:
            check_stage(target, request["schema_after"])
        elif observed["main"] == request["source"]["main"] and observed["-wal"] in {
            None,
            request["source"]["-wal"],
        }:
            if snapshot.digest(stage) != state["staged_sha256"]:
                raise ValueError("Prepared restore bytes changed")
            check_stage(stage, request["schema_after"])
            upgrade.require_atomic_stage(stage, target)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = target.with_name(target.name + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    upgrade.regular(sidecar)
                    sidecar.unlink()
            os.replace(stage, target)
            upgrade.sync(storage.ROOT)
            check_stage(target, request["schema_after"])
        else:
            raise ValueError("Database changed during restore publication; retain it for inspection")
        if snapshot.digest(target) != state["staged_sha256"]:
            raise ValueError("The restored database bytes changed before acknowledgement")
        state["phase"] = "applied"
        upgrade.write(parent / "state.json", state)
        return finish(request, state)


def abort(value, operation, image_id):
    with guard(value):
        parent, request, state = load(value, operation, image_id)
        if state["phase"] == "aborted":
            return finish(request, state)
        require_marker(request)
        if (
            state["phase"] not in {"preparing", "prepared"}
            or storage.fingerprint(value)["database"] != request["source"]
        ):
            raise ValueError("Publication began or the database changed; do not roll back automatically")
        state["phase"] = "aborted"
        upgrade.write(parent / "state.json", state)
        return finish(request, state)


def status(value, operation, image_id):
    with guard(value):
        _, request, state = load(value, operation, image_id)
        return report(request, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish", "abort", "status"))
    for name in ("operation-id", "image-id", "storage-id", "namespace"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--backup-id")
    parser.add_argument("--snapshot-identity")
    parser.add_argument("--database-sha256")
    parser.add_argument("--recover-admin", action="store_true")
    args = parser.parse_args()
    if os.environ.get("AI_STATION_DATABASE_URL"):
        raise ValueError("Offline restoration refuses an external database URL override")
    os.umask(0o077)
    value = storage.binding(args.storage_id, args.namespace, args.uid, args.gid)
    if args.action == "prepare":
        result = prepare(
            value,
            args.operation_id,
            args.backup_id,
            args.snapshot_identity,
            args.database_sha256,
            args.image_id,
            recover_admin=args.recover_admin,
        )
    else:
        if args.backup_id or args.snapshot_identity or args.database_sha256 or args.recover_admin:
            raise ValueError("Only restore preparation accepts backup/recovery parameters")
        result = {"publish": publish, "abort": abort, "status": status}[args.action](
            value, args.operation_id, args.image_id
        )
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
