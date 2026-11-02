"""Consistent native files/VM-database restore. No HTTP, agents or native SQLite."""

import hashlib
import json
from pathlib import Path

import desktop_snapshot_files as files
import desktop_snapshots as snapshots
import desktop_versions as versions
from desktop_bridge import private_directory
from desktop_restore_files import FileRestore, exists
from macos_database_storage import RESTORE_ACTIONS, stable_identity

FENCE = "desktop-restore-pending.json"


def recoverable_version(value):
    # A failed restart must not make an existing installation impossible to
    # restore. This is recovery eligibility, never a claim of current readiness.
    return value["phase"] == "ready" or (value["phase"] == "starting" and value["last_ready_at"] is not None)


class Restoration:
    def __init__(self, storage, operation, backup=None, *, secrets_policy="review", recover_admin=False):
        self.storage = storage
        self.operation = snapshots.operation_id(operation)
        self.root, self.data = storage.root, storage.data
        parent = self.root / "restores"
        parent.mkdir(mode=0o700, exist_ok=True)
        private_directory(parent)
        self.folder = parent / operation
        self.folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.folder)
        request_path, state_path = self.folder / "request.json", self.folder / "state.json"
        if exists(request_path):
            self.request = json.loads(versions.read_private(request_path, 32768))
            if self.request.get("operation_id") != operation or self.request.get("schema") != 1:
                raise ValueError("The private restore request changed")
            if backup is not None and str(versions.canonical(backup)) != self.request["backup_path"]:
                raise ValueError("The selected restore source changed")
            if backup is not None and (
                secrets_policy != self.request["secrets_policy"]
                or recover_admin != self.request["recover_admin"]
            ):
                raise ValueError("The reviewed restore policy changed; resume its original request or abort")
        else:
            if (
                backup is None
                or secrets_policy not in {"review", "keep_current"}
                or type(recover_admin) is not bool
            ):
                raise ValueError("A new restore needs its selected backup and reviewed credential policy")
            snapshots.assert_finished(self.root, self.data)
            backup = versions.canonical(backup)
            if backup.is_relative_to(self.data) or self.data.is_relative_to(backup):
                raise ValueError("A full restore source must remain outside application data")
            source = snapshots.verify(backup)
            database = json.loads(versions.read_private(backup / "receipt.json", 16384))
            self.request = {
                "schema": 1,
                "operation_id": operation,
                "target": self.target(),
                "backup_path": str(backup),
                "backup_manifest_sha256": files.file_hash(backup / "snapshot.json"),
                "backup_id": source["operation_id"],
                "snapshot_identity": source["identity"],
                "database_sha256": database["database_sha256"],
                "secrets_policy": secrets_policy,
                "recover_admin": recover_admin,
            }
            files.write_json(request_path, self.request)
        self.identity = snapshots.digest(self.request)
        self.fence = {"schema": 1, "operation_id": operation, "identity": self.identity}
        if not exists(state_path):
            if self.fenced() or exists(FileRestore(self.data, operation).root / "request.json"):
                raise ValueError(
                    "Restore state is missing after preparation; retain originals for inspection"
                )
            files.write_json(
                state_path, {"phase": "preparing", "request_sha256": self.identity, "original_database": None}
            )
        self.state = json.loads(versions.read_private(state_path, 32768))
        if self.state.get("request_sha256") != self.identity or self.state.get("phase") not in {
            "preparing",
            "prepared",
            "publishing_files",
            "publishing_database",
            "applied",
            "aborting",
            "aborted",
        }:
            raise ValueError("The private restore state changed")

    def target(self):
        self.storage.owned()
        if self.storage.record["phase"] != "ready":
            raise ValueError("Restore requires ready attested database storage")
        data, namespace = versions.namespace(self.storage.config)
        current = versions.load(self.root)
        if (
            data != self.data
            or not recoverable_version(current)
            or current["package"] != self.storage.package
            or current["namespace_sha256"] != namespace
        ):
            raise ValueError("Restore requires the matching ready installation and verified package")
        return {
            "package": self.storage.package,
            "namespace_sha256": namespace,
            "storage_identity": stable_identity(self.storage.record),
            "version": current,
            "config_sha256": hashlib.sha256(versions.read_private(self.storage.config, 65536)).hexdigest(),
        }

    def save(self):
        files.write_json(self.folder / "state.json", self.state)

    def fences(self, *, create=False, clear=False):
        for root in (self.root, self.data / "runtime"):
            value = snapshots.pending(root, FENCE)
            if value is not None and value != self.fence:
                raise ValueError("A different native restore is pending")
            if snapshots.pending(root) is not None:
                raise ValueError("Finish the pending backup before restoring")
        for root in (self.root, self.data / "runtime"):
            value = snapshots.pending(root, FENCE)
            if create and value is None:
                files.write_json(root / FENCE, self.fence)
            elif clear and value is not None:
                (root / FENCE).unlink()
                files.sync(root)

    def fenced(self):
        return any(snapshots.pending(root, FENCE) is not None for root in (self.root, self.data / "runtime"))

    def check(self):
        if self.target() != self.request["target"]:
            raise ValueError("The restore target changed; no historical installation authority was adopted")
        item = self.storage.record["command"]
        if item is not None:
            if item["action"] in RESTORE_ACTIONS:
                if item["restore"] != self.context():
                    raise ValueError("Another native restore helper is pending")
            elif item["action"] != "fingerprint":
                raise ValueError("Finish the existing database operation before restoring")
        self.fences()

    def context(self):
        return {
            key: self.request[key]
            for key in (
                "operation_id",
                "backup_id",
                "snapshot_identity",
                "database_sha256",
                "backup_path",
                "recover_admin",
            )
        }

    def database(self, action, *, canceled=lambda: False):
        item = self.storage.record["command"]
        if item is not None:
            if item["action"] == "fingerprint":
                self.storage.fingerprint()  # Reconcile its exact read-only operation first.
            elif (
                item["action"] in RESTORE_ACTIONS
                and item["action"] != "restore_" + action
                and not item["interrupted"]
            ):
                self.storage.restore_database(item["action"].removeprefix("restore_"), self.context())
        return self.storage.restore_database(action, self.context(), canceled=canceled)

    def result(self):
        return {
            "status": self.state["phase"],
            "operation_id": self.operation,
            "backup_id": self.request["backup_id"],
            "snapshot_identity": self.request["snapshot_identity"],
            "database": self.state.get("database"),
            "original_files": str(self.data / "recovery" / ("desktop-" + self.operation) / "originals"),
        }

    def verify_database(self):
        report = self.state["database"]
        expected = {"main": report["database_sha256"], "-wal": None, "-journal": None}
        if report["phase"] != "applied" or self.storage.fingerprint() != expected:
            raise ValueError(
                "Restored database differs from its acknowledged publication; inspection required"
            )

    def completed(self):
        if self.state["phase"] not in {"applied", "aborted"}:
            return None
        if self.fenced():
            self.check()
            if self.state["phase"] == "applied":
                self.verify_database()
                FileRestore(self.data, self.operation).commit()
            elif self.storage.fingerprint() != self.state["original_database"]:
                raise ValueError("The database changed before aborted restore cleanup")
            self.fences(clear=True)
        return self.result()  # Historical completion never repeats after later app writes.

    def _prepare(self, *, canceled, progress):
        self.fences(create=True)
        if self.state["phase"] != "preparing":
            return self.result()
        if canceled():
            raise InterruptedError("Restore canceled before preparation")
        if self.state["original_database"] is None:
            self.state["original_database"] = self.storage.fingerprint()
            self.save()
        backup = Path(self.request["backup_path"])
        if (
            files.file_hash(backup / "snapshot.json") != self.request["backup_manifest_sha256"]
            or snapshots.verify(backup)["identity"] != self.request["snapshot_identity"]
        ):
            raise ValueError("The chosen full backup changed")
        progress("database", 0, 1)
        report = self.database("prepare", canceled=canceled)
        if report["phase"] != "prepared" or report["source"] != self.state["original_database"]:
            raise ValueError("The prepared restore differs from its original database/intent")
        progress("database", 1, 1)
        if canceled():
            raise InterruptedError("Restore canceled after database preparation")
        FileRestore(self.data, self.operation).prepare(
            backup,
            self.request["snapshot_identity"],
            secrets_policy=self.request["secrets_policy"],
            canceled=canceled,
            progress=lambda done, total: progress("files", done, total),
        )
        if self.storage.fingerprint() != self.state["original_database"]:
            raise ValueError("The original database changed before file publication")
        self.state["phase"] = "prepared"
        self.save()
        return self.result()

    def prepare(self, *, canceled=lambda: False, progress=lambda *_: None, owner_lock=None):
        if self.state["phase"] in {"applied", "aborted"} and not self.fenced():
            return self.result()
        with snapshots.offline(self.storage, owner_lock=owner_lock, allow_restore=True):
            self.check()
            finished = self.completed()
            if finished is not None:
                return finished
            return self._prepare(canceled=canceled, progress=progress)

    def apply(self, *, canceled=lambda: False, progress=lambda *_: None, owner_lock=None):
        if self.state["phase"] in {"applied", "aborted"} and not self.fenced():
            return self.result()
        with snapshots.offline(self.storage, owner_lock=owner_lock, allow_restore=True):
            self.check()
            finished = self.completed()
            if finished is not None:
                return finished
            if self.state["phase"] == "aborting":
                return self._abort()
            try:
                self._prepare(canceled=canceled, progress=progress)
                if self.state["phase"] in {"prepared", "publishing_files"}:
                    if canceled():
                        raise InterruptedError("Restore canceled before file publication")
                    if self.storage.fingerprint() != self.state["original_database"]:
                        raise ValueError("The original database changed before publication")
                    self.state["phase"] = "publishing_files"
                    self.save()

                    def file_progress(done, total):
                        progress("publishing_files", done, total)
                        if canceled():
                            raise InterruptedError("Restore canceled before database publication")

                    FileRestore(self.data, self.operation).publish(progress=file_progress)
                    if canceled():
                        raise InterruptedError("Restore canceled before database publication")
                    self.state["phase"] = "publishing_database"
                    self.save()  # From this point publication must be inspected/resumed, never killed/rolled back.
                if self.state["phase"] == "publishing_database":
                    progress("publishing_database", 0, 1)
                    FileRestore(
                        self.data, self.operation
                    ).publish()  # Recheck files before an uncertain/new DB publication.
                    report = self.database("publish")
                    self.state["database"] = report
                    self.save()
                    self.verify_database()
                    FileRestore(self.data, self.operation).commit()
                    snapshots.quiescent(self.storage)
                    self.state["phase"] = "applied"
                    self.save()
                    self.fences(clear=True)
                    progress("complete", 1, 1)
                return self.result()
            except InterruptedError:
                return self._abort()

    def _abort(self):
        if self.state["phase"] in {"publishing_database", "applied"}:
            raise ValueError(
                "Database publication may have started; resume or inspect instead of rolling back"
            )
        self.fences(create=True)
        if self.state["original_database"] is None:
            self.state["original_database"] = self.storage.fingerprint()
            self.save()
        item = self.storage.record["command"]
        if item is not None and item["action"] == "restore_prepare":
            self.storage.interrupt_restore(self.context())
        report = self.database("status")
        if report["phase"] in {"publishing", "applied"}:
            raise ValueError("Database publication needs inspection; files were not rolled back")
        if report["phase"] != "not_started":
            self.database("abort")
        if self.storage.fingerprint() != self.state["original_database"]:
            raise ValueError("The original database changed; retain the restore fence for inspection")
        self.state["phase"] = "aborting"
        self.save()
        owner = FileRestore(self.data, self.operation)
        if exists(owner.root / "request.json"):
            owner.abort()
        self.state["phase"] = "aborted"
        self.save()
        self.fences(clear=True)
        return self.result()

    def abort(self, *, owner_lock=None):
        if self.state["phase"] in {"applied", "aborted"} and not self.fenced():
            return self.result()
        with snapshots.offline(self.storage, owner_lock=owner_lock, allow_restore=True):
            self.check()
            finished = self.completed()
            if finished is not None:
                return finished
            return self._abort()
