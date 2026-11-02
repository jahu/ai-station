"""Private, offline installer backups; never an HTTP, Runner or agent capability."""

import hashlib
import json
import os
import platform
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import desktop_snapshot_files as files
import desktop_versions as versions
from desktop_bridge import private_directory
from desktop_update import cold_handoff
from desktop_update_owner import lock_file, require_lock
from macos_database_storage import stable_identity

FENCE = "desktop-snapshot-pending.json"
LIMIT = 4 * 1024**2


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def operation_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Use a canonical backup UUID")
    return value


def pending(root):
    path = root / FENCE
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(versions.read_private(path, 4096))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "operation_id", "identity"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or not isinstance(value["identity"], str)
        or not re.fullmatch(versions.HEX, value["identity"])
    ):
        raise ValueError("The pending backup receipt is invalid; inspect it before startup")
    operation_id(value["operation_id"])
    return value


def assert_finished(root, data):
    if pending(root) is not None or pending(data / "runtime") is not None:
        raise ValueError("Finish or cancel the pending private backup before starting AI Station")


def native_quiescent(data):
    """Read ownership only. Never construct a process manager or send signals."""
    path = data / "runtime/processes.json"
    if not path.exists() and not path.is_symlink():
        return
    records = json.loads(versions.read_private(path, 16 * 1024**2))
    if not isinstance(records, dict):
        raise ValueError("The native process inventory is invalid")
    system = platform.system()
    if system == "Darwin":
        from ai_station_runner.darwin_processes import group_alive
    elif system == "Linux":
        from ai_station_runner.processes import _group_alive as group_alive
    else:
        raise ValueError("Offline native process inspection is unavailable on this platform")
    for record in records.values():
        if not isinstance(record, dict) or (
            type(record.get("pid")) is not int
            or not 0 < record["pid"] < 2**31
            or record.get("process_group_id") != record["pid"]
            or not isinstance(record.get("boot_id"), str)
            or not record["boot_id"]
            or system == "Linux"
            and (type(record.get("start_ticks")) is not int or record["start_ticks"] <= 0)
        ):
            raise ValueError("A complete native process identity is required before backup")
        if group_alive(record):
            raise ValueError("Stop the owned native workload before making an offline backup")


def quiescent(storage):
    """Pinned daemon; inspect only mount/state metadata, never unrelated secrets."""
    item = storage.record["command"]
    if item is not None and item["phase"] == "finished":
        # rm may have completed before its acknowledgement was lost. Inspect the
        # exact ID before the normal guard, which requires an existing helper.
        storage.owned()
        _, present = storage.call(
            "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + item["container_id"]
        )
        if not present:
            storage.cleanup()
    storage.quiescent()
    _, raw = storage.call("container", "ls", "--all", "--quiet", "--no-trunc")
    ids = raw.splitlines()
    if len(ids) > 256 or any(not re.fullmatch(r"[a-f0-9]{64}", item) for item in ids):
        raise ValueError("The container inventory exceeds the offline backup bound")
    if ids:
        template = (
            '{"Id":{{json .Id}},"State":{"Running":{{json .State.Running}},'
            '"Paused":{{json .State.Paused}},"Restarting":{{json .State.Restarting}}},'
            '"Mounts":{{json .Mounts}}}'
        )
        _, raw = storage.call("container", "inspect", "--format", template, *ids)
        if len(raw.encode()) > LIMIT:
            raise ValueError("The container inventory exceeds the offline backup bound")
        rows = [json.loads(row) for row in raw.splitlines()]
        if len(rows) != len(ids) or {row.get("Id") for row in rows if isinstance(row, dict)} != set(ids):
            raise ValueError("The complete container inventory must be confirmed before backup")
        for row in rows:
            state, mounts = row.get("State"), row.get("Mounts")
            if (
                not isinstance(state, dict)
                or any(type(state.get(k)) is not bool for k in ("Running", "Paused", "Restarting"))
                or not isinstance(mounts, list)
            ):
                raise ValueError("Container state and mounts must be confirmed before backup")
            if not any(state.values()):
                continue
            for mount in mounts:
                if not isinstance(mount, dict) or not isinstance(mount.get("Type"), str):
                    raise ValueError("Container mount identity is unknown")
                if mount["Type"] != "bind":
                    continue
                source = mount.get("Source")
                if not isinstance(source, str) or not source.startswith("/"):
                    raise ValueError("The container bind source is unknown")
                source = Path(source).resolve()
                if source.is_relative_to(storage.data) or storage.data.is_relative_to(source):
                    raise ValueError("Stop containers using these application files before backup")
    native_quiescent(storage.data)


@contextmanager
def offline(storage, *, owner_lock=None, require_quiescent=True):
    import fcntl

    with cold_handoff(storage.root, owner_lock=owner_lock):
        runtime = storage.data / "runtime"
        private_directory(runtime)
        fd = lock_file(runtime, "launcher.lock", create=True)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Stop the station supervisor before backup") from None
            require_lock(runtime, "launcher.lock", fd)
            # An upgrade/recovery cannot be co-owned by this operation.
            for name in (
                "desktop-upgrade-pending.json",
                "desktop-upgrade-dispatch-pending.json",
                "recovery-pending.json",
            ):
                path = runtime / name
                if path.exists() or path.is_symlink():
                    raise ValueError("Finish the existing upgrade/recovery before backup")
            if require_quiescent:
                quiescent(storage)
            yield
            require_lock(runtime, "launcher.lock", fd)
        finally:
            os.close(fd)


class Snapshot:
    """One cold installation/export identity, including interrupted helper recovery."""

    def __init__(self, storage, operation):
        self.storage = storage
        self.operation = operation_id(operation)
        self.root, self.data = storage.root, storage.data
        item = storage.record["command"]
        if item is not None:
            recovering_reader = (
                item["action"] == "fingerprint"
                and item["image"] == storage.package["image_id"]
                and (pending(self.root) or {}).get("operation_id") == operation
                and (self.root / "snapshots" / operation / "request.json").is_file()
            )
            if not recovering_reader and (item["action"] != "export" or item["export_id"] != operation):
                raise ValueError("Finish the other owned database operation before backup")
        if storage.record["phase"] != "ready":
            raise ValueError("The database volume is not ready for backup")
        storage.owned()
        self.config = versions.read_private(storage.config, 65536)
        version = versions.load(self.root)
        data, namespace = versions.namespace(storage.config)
        if (
            data != self.data
            or version["phase"] != "ready"
            or version["package"] != storage.package
            or version["namespace_sha256"] != namespace
        ):
            raise ValueError("Backup requires this ready, verified installation and package")
        self.request = {
            "schema": 1,
            "operation_id": operation,
            "package": storage.package,
            "namespace_sha256": namespace,
            "storage_identity": stable_identity(storage.record),
            "storage_binding": storage.binding(),
            "version": version,
            "config_sha256": hashlib.sha256(self.config).hexdigest(),
        }
        self.identity = digest(self.request)
        self.fence = {"schema": 1, "operation_id": operation, "identity": self.identity}
        folder = self.root / "snapshots"
        folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(folder)
        self.journal = folder / operation
        self.journal.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.journal)
        request = self.journal / "request.json"
        if request.exists() or request.is_symlink():
            if json.loads(versions.read_private(request, 16384)) != self.request:
                raise ValueError("The installation changed since this backup began")
        else:
            files.write_json(request, self.request)
        self.output = self.root / "database-exports" / operation

    def fences(self, *, create=False, clear=False):
        for root in (self.root, self.data / "runtime"):
            value = pending(root)
            if value is not None and value != self.fence:
                raise ValueError("A different backup is pending; nothing was changed")
        for root in (self.root, self.data / "runtime"):
            value = pending(root)
            if create and value is None:
                files.write_json(root / FENCE, self.fence)
            elif clear and value is not None:
                (root / FENCE).unlink()
                files.sync(root)

    def export(self, *, canceled=lambda: False, progress=lambda *_: None, owner_lock=None):
        with offline(self.storage, owner_lock=owner_lock):
            if (self.journal / "canceled.json").exists() or (self.journal / "canceled.json").is_symlink():
                raise ValueError("This backup was canceled; use a new backup identity")
            self.fences()
            if (self.output / "snapshot.json").exists() or (self.output / "snapshot.json").is_symlink():
                result = verify(self.output)
                if result["identity"] != self.identity:
                    raise ValueError("The completed backup identity changed")
                self.fences(clear=True)
                return result
            self.fences(create=True)
            if canceled():
                raise InterruptedError("Backup canceled; originals and partial output kept")
            if (
                self.storage.record["command"] is not None
                and self.storage.record["command"]["action"] == "fingerprint"
            ):
                self.storage.fingerprint()
            progress("database", 0, 1)
            report = self.storage.export_database(self.operation)
            quiescent(self.storage)
            progress("database", 1, 1)
            # A resumed files copy can never silently pair an old DB with newer data.
            if self.storage.fingerprint() != report["source"]:
                raise ValueError("The source database changed since this backup began")
            if versions.read_private(self.storage.config, 65536) != self.config:
                raise ValueError("The installation configuration changed during backup")
            metadata = self.output / "installation.json"
            if metadata.exists() or metadata.is_symlink():
                if json.loads(versions.read_private(metadata, 16384)) != self.request:
                    raise ValueError("The saved installation identity changed")
            else:
                files.write_json(metadata, self.request)
            config = self.output / "desktop.env"
            if config.exists() or config.is_symlink():
                if versions.read_private(config, 65536) != self.config:
                    raise ValueError("The saved installation configuration changed")
            else:
                files.write_bytes(config, self.config)
            retained = files.export_files(
                self.data,
                self.output,
                self.identity,
                canceled=canceled,
                progress=lambda done, total: progress("files", done, total),
            )
            quiescent(self.storage)
            if canceled():
                raise InterruptedError("Backup canceled before publication; partial output kept")
            if self.storage.fingerprint() != report["source"]:
                raise ValueError("The source database changed during backup")
            if versions.read_private(self.storage.config, 65536) != self.config:
                raise ValueError("The installation configuration changed during backup")
            result = {
                "schema": 1,
                "identity": self.identity,
                "operation_id": self.operation,
                "database_receipt_sha256": files.file_hash(self.output / "receipt.json"),
                "files_manifest_sha256": files.file_hash(self.output / "files.json"),
                "files_request_sha256": files.file_hash(self.output / "files-request.json"),
                "installation_sha256": files.file_hash(metadata),
                "config_sha256": self.request["config_sha256"],
                "file_count": sum(item["kind"] == "file" for item in retained["entries"]),
            }
            files.write_json(self.output / "snapshot.json", result)
            result = verify(self.output)
            self.fences(clear=True)
            return result

    def cancel(self, *, owner_lock=None):
        # Cancel never publishes data. A new external file/DB client must not
        # prevent releasing this backup's fence, and is never stopped here.
        with offline(self.storage, owner_lock=owner_lock, require_quiescent=False):
            self.fences()
            if (self.output / "snapshot.json").exists():
                result = verify(self.output)
                self.fences(clear=True)
                return {"status": "completed", "snapshot": result}
            if self.storage.record["command"] is not None:
                if self.storage.record["command"]["action"] == "fingerprint":
                    self.storage.fingerprint()  # Reconcile only this backup's fixed read-only helper.
                else:
                    self.storage.cancel_export(self.operation)
            files.write_json(self.journal / "canceled.json", self.fence)
            self.fences(clear=True)
            return {"status": "canceled", "operation_id": self.operation}


def verify(output):
    """Offline inspection is independent of the live source and never opens SQLite."""
    output = versions.canonical(output)
    private_directory(output)
    result = json.loads(versions.read_private(output / "snapshot.json", 16384))
    expected = {
        "schema",
        "identity",
        "operation_id",
        "database_receipt_sha256",
        "files_manifest_sha256",
        "files_request_sha256",
        "installation_sha256",
        "config_sha256",
        "file_count",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected
        or type(result["schema"]) is not int
        or result["schema"] != 1
    ):
        raise ValueError("The full backup manifest is invalid")
    if {path.name for path in output.iterdir()} != {
        "snapshot.json",
        "receipt.json",
        "database.sqlite",
        "files.json",
        "files-request.json",
        "installation.json",
        "desktop.env",
        "files",
        "files-staging",
    }:
        raise ValueError("The full backup file inventory changed")
    private_directory(output / "files-staging")
    if list((output / "files-staging").iterdir()):
        raise ValueError("Unpublished backup staging files remain")
    operation_id(result["operation_id"])
    for key in expected - {"schema", "file_count", "operation_id"}:
        if not isinstance(result[key], str) or not re.fullmatch(versions.HEX, result[key]):
            raise ValueError("The backup manifest hash is invalid")
    for name, key in (
        ("receipt.json", "database_receipt_sha256"),
        ("files.json", "files_manifest_sha256"),
        ("files-request.json", "files_request_sha256"),
        ("installation.json", "installation_sha256"),
        ("desktop.env", "config_sha256"),
    ):
        if files.file_hash(output / name) != result[key]:
            raise ValueError("The full backup metadata changed")
    request = json.loads(versions.read_private(output / "installation.json", 16384))
    report = json.loads(versions.read_private(output / "receipt.json", 16384))
    if (
        digest(request) != result["identity"]
        or request.get("operation_id") != result["operation_id"]
        or request.get("config_sha256") != result["config_sha256"]
        or not isinstance(report, dict)
        or report.get("operation_id") != result["operation_id"]
        or report.get("storage") != request.get("storage_binding")
        or report.get("image_id") != request.get("package", {}).get("image_id")
        or type(report.get("database_bytes")) is not int
        or (output / "database.sqlite").lstat().st_size != report["database_bytes"]
        or files.file_hash(output / "database.sqlite") != report.get("database_sha256")
    ):
        raise ValueError("The backup database/installation binding changed")
    retained = files.verify_files(output, result["identity"])
    if type(result["file_count"]) is not int or result["file_count"] != sum(
        item["kind"] == "file" for item in retained["entries"]
    ):
        raise ValueError("The retained file count changed")
    return result
