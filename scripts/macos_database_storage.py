"""Persistent native-installer DB ownership. Never removes or imports a volume."""

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

import desktop_versions as versions
from desktop_bridge import private_directory
from macos_transport_probe import bind_mount, command

RECEIPT = "database-storage.json"
MEMORY = 128 * 1024**2
LABEL = "ai-station.desktop-database"
RESTORE_ACTIONS = tuple("restore_" + v for v in ("prepare", "publish", "abort", "status"))
RESTORE_MEMORY = 512 * 1024**2


def restore_request(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "operation_id",
            "backup_id",
            "snapshot_identity",
            "database_sha256",
            "backup_path",
            "recover_admin",
        }
        or type(value["recover_admin"]) is not bool
        or not isinstance(value["backup_path"], str)
        or not value["backup_path"].startswith("/")
        or "\x00" in value["backup_path"]
        or str(Path(value["backup_path"])) != value["backup_path"]
        or ".." in Path(value["backup_path"]).parts
    ):
        raise ValueError("The fixed restore request is invalid")
    for key in ("operation_id", "backup_id"):
        if not isinstance(value[key], str) or str(UUID(value[key])) != value[key]:
            raise ValueError("Restore identities must be canonical UUIDs")
    for key in ("snapshot_identity", "database_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key]):
            raise ValueError("The fixed restore hash is invalid")
    return value


def write(path, value):
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        versions.read_private(path, 16384)
    descriptor, name = tempfile.mkstemp(prefix=".database-owner-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as target:
            json.dump(value, target, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_record(r, coordinates):
    if (
        not isinstance(r, dict)
        or set(r)
        != {*coordinates, "storage_id", "name", "initialization_image", "phase", "volume", "command"}
        or {k: r.get(k) for k in coordinates} != coordinates
        or type(r["schema"]) is not int
        or not isinstance(r["storage_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", r["storage_id"])
        or r["name"] != "ai-station-database-" + r["storage_id"]
        or not isinstance(r["initialization_image"], str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", r["initialization_image"])
        or r["phase"] not in ("creating", "created", "initialized", "ready")
        or (r["volume"] is None) != (r["phase"] == "creating")
    ):
        raise ValueError("The private database storage binding changed; existing bytes preserved")
    item = r["command"]
    if item is not None and (
        not isinstance(item, dict)
        or set(item)
        != {"attempt", "action", "image", "phase", "container_id"}
        | ({"export_id"} if item.get("action") == "export" else set())
        | ({"restore", "restore_result", "interrupted"} if item.get("action") in RESTORE_ACTIONS else set())
        or not isinstance(item["attempt"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", item["attempt"])
        or item["action"] not in ("initialize", "inspect", "fingerprint", "empty", "export", *RESTORE_ACTIONS)
        or item["action"] == "export"
        and (
            not isinstance(item["export_id"], str)
            or not re.fullmatch(r"[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}", item["export_id"])
        )
        or not isinstance(item["image"], str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", item["image"])
        or item["phase"] not in ("creating", "created", "starting", "finished")
        or item["container_id"] is not None
        and (
            not isinstance(item["container_id"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["container_id"])
        )
        or item["phase"] != "creating"
        and item["container_id"] is None
        or (item["action"], r["phase"])
        not in (
            (
                ("initialize", "initialized"),
                ("inspect", "ready"),
                ("fingerprint", "ready"),
                ("empty", "ready"),
                ("export", "ready"),
                *((action, "ready") for action in RESTORE_ACTIONS),
            )
            if item["phase"] == "finished"
            else (
                ("initialize", "created"),
                ("inspect", "initialized"),
                ("inspect", "ready"),
                ("fingerprint", "ready"),
                ("empty", "ready"),
                ("export", "ready"),
                *((action, "ready") for action in RESTORE_ACTIONS),
            )
        )
    ):
        raise ValueError("The database helper identity requires inspection")
    if item is not None and item["action"] in RESTORE_ACTIONS:
        restore_request(item["restore"])
        if (
            type(item["interrupted"]) is not bool
            or item["interrupted"]
            and (item["action"] != "restore_prepare" or item["phase"] != "finished")
            or item["restore_result"] is not None
            and not isinstance(item["restore_result"], dict)
            or item["phase"] == "finished"
            and not item["interrupted"]
            and item["restore_result"] is None
            or item["interrupted"]
            and item["restore_result"] is not None
        ):
            raise ValueError("The restore helper completion receipt changed")


def stable_identity(record):
    """Immutable storage coordinates only; helper journals never relocate data."""
    volume = record["volume"]
    if (
        not isinstance(volume, dict)
        or set(volume) != {"Name", "Driver", "Scope", "CreatedAt", "Mountpoint"}
        or volume["Name"] != record["name"]
        or volume["Driver"] != "local"
        or volume["Scope"] != "local"
        or not isinstance(volume["CreatedAt"], str)
        or not volume["CreatedAt"]
        or not isinstance(volume["Mountpoint"], str)
        or not volume["Mountpoint"].startswith("/")
    ):
        raise ValueError("The database volume receipt is invalid")
    frozen = {
        k: record[k]
        for k in (
            "schema",
            "storage_id",
            "namespace_sha256",
            "uid",
            "gid",
            "engine",
            "architecture",
            "volume",
        )
    }
    return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()


def reference(root, base_namespace):
    """Read private coordinates without contacting Docker or native SQLite."""
    folder = root / "database-storage"
    if not folder.exists() and not folder.is_symlink():
        return None
    private_directory(folder)
    path = folder / RECEIPT
    if not path.exists() and not path.is_symlink():
        raise ValueError("The private database storage folder has no ownership receipt")
    record = json.loads(versions.read_private(path, 16384))
    engine = record.get("engine") if isinstance(record, dict) else None
    if (
        not isinstance(engine, list)
        or len(engine) != 3
        or not all(isinstance(v, str) for v in engine)
        or not engine[0].startswith("/")
        or not engine[1].startswith("unix:///")
        or not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", engine[2])
        or record.get("architecture") not in ("amd64", "arm64")
    ):
        raise ValueError("The database engine receipt is invalid")
    coordinates = {
        "schema": 1,
        "namespace_sha256": base_namespace,
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "engine": engine,
        "architecture": record["architecture"],
    }
    validate_record(record, coordinates)
    if record["phase"] != "ready":
        raise ValueError("Database storage is not ready for version activation")
    return stable_identity(record)


class DatabaseStorage:
    """Caller holds the native installation owner lock throughout preparation."""

    def __init__(self, root, config, engine, package):
        self.root, self.config = root, config
        self.package = versions.package_identity(package)
        self.architecture = {"x86_64": "amd64", "arm64": "arm64"}.get(package.get("architecture"))
        if self.architecture is None or engine.identity is None:
            raise ValueError("Database storage requires a verified package and pinned local engine")
        binary, endpoint = engine.identity
        if tuple(engine.prefix) != (binary, "--host", endpoint):
            raise ValueError("The database Docker connection must remain pinned")
        self.data, self.namespace = versions.base_namespace(config)
        if config.parent != root or root.is_relative_to(self.data):
            raise ValueError("Database receipts must remain outside mounted application data")
        private_directory(root)
        self.folder = root / "database-storage"
        self.folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.folder)
        client = self.folder / "client"
        client.mkdir(mode=0o700, exist_ok=True)
        private_directory(client)
        if (client / "config.json").exists() or (client / "config.json").is_symlink():
            if json.loads(versions.read_private(client / "config.json", 1024)) != {}:
                raise ValueError("The private database Docker configuration changed")
        else:
            write(client / "config.json", {})
        self.argv = [*engine.prefix, "--config", str(client)]
        self.environment = {"PATH": str(Path(binary).parent) + os.pathsep + os.defpath, "LANG": "C"}
        _, raw = self.call("info", "--format", "{{json .ID}}")
        daemon = json.loads(raw)
        if not isinstance(daemon, str) or not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", daemon):
            raise ValueError("The local Docker daemon identity is invalid")
        self.coordinates = {
            "schema": 1,
            "namespace_sha256": self.namespace,
            "uid": os.geteuid(),
            "gid": os.getegid(),
            "engine": [binary, endpoint, daemon],
            "architecture": self.architecture,
        }
        if any(not 0 < self.coordinates[k] < 2**31 for k in ("uid", "gid")):
            raise ValueError("Run the native installer as an ordinary user")
        self.path = self.folder / RECEIPT
        self.fresh = not (self.path.exists() or self.path.is_symlink())
        if self.fresh:
            if (self.data / "db").exists() and list((self.data / "db").iterdir()):
                raise ValueError(
                    "Existing host database bytes require an explicit import; nothing was changed"
                )
            identity = uuid4().hex
            self.record = self.coordinates | {
                "storage_id": identity,
                "name": "ai-station-database-" + identity,
                "initialization_image": self.package["image_id"],
                "phase": "creating",
                "volume": None,
                "command": None,
            }
            self.save()
        else:
            self.record = json.loads(versions.read_private(self.path, 16384))
        self.validate()

    def placeholder(self):
        # Precreate the empty nested mountpoint as the native user. Otherwise
        # Docker creates a root-owned directory inside the host data bind.
        # It is never the active database and may not contain stale DB bytes.
        path = self.data / "db"
        path.mkdir(mode=0o700, exist_ok=True)
        private_directory(path)
        if list(path.iterdir()):
            raise ValueError("The host database mountpoint must remain empty; existing bytes preserved")

    def call(self, *args, **kwargs):
        return command([*self.argv, *args], env=self.environment, **kwargs)

    def validate(self):
        validate_record(self.record, self.coordinates)

    def save(self):
        write(self.path, self.record)

    def consistent(self):
        self.validate()
        if versions.base_namespace(self.config) != (self.data, self.namespace):
            raise ValueError("The selected data directory changed")
        self.placeholder()
        if json.loads(versions.read_private(self.path, 16384)) != self.record:
            raise ValueError("The private database receipt changed")
        _, raw = self.call("info", "--format", "{{json .ID}}")
        if json.loads(raw) != self.coordinates["engine"][2]:
            raise ValueError("The pinned Docker daemon changed")

    def owned(self):
        self.consistent()
        _, raw = self.call("volume", "inspect", self.record["name"])
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError("The persistent database volume is missing or ambiguous")
        v = rows[0]
        if (
            v.get("Name") != self.record["name"]
            or v.get("Driver") != "local"
            or v.get("Scope") != "local"
            or v.get("Options") not in (None, {})
            or v.get("Labels") != {LABEL: self.record["storage_id"], LABEL + ".namespace": self.namespace}
            or not isinstance(v.get("CreatedAt"), str)
            or not v["CreatedAt"]
            or not isinstance(v.get("Mountpoint"), str)
            or not v["Mountpoint"].startswith("/")
        ):
            raise ValueError("Unknown database volume; nothing was adopted or modified")
        observed = {k: v[k] for k in ("Name", "Driver", "Scope", "CreatedAt", "Mountpoint")}
        if self.record["volume"] is not None and self.record["volume"] != observed:
            raise ValueError("The persistent database volume was replaced; replacement preserved")
        return observed

    def recover_creation(self):
        """Explicit lost-ACK inspection of the nonce-bound pending volume; no create/retry."""
        if self.record["phase"] != "creating":
            raise ValueError("There is no pending volume creation")
        self.record["volume"] = self.owned()
        self.record["phase"] = "created"
        self.save()
        self.fresh = False

    def binding(self):
        return {k: self.record[k] for k in ("schema", "storage_id", "namespace_sha256", "uid", "gid")}

    def mount(self, *, readonly=False):
        self.owned()
        return (
            "type=volume,source="
            + self.record["name"]
            + ",target=/database,volume-nocopy"
            + (",readonly" if readonly else "")
        )

    def application_mount(self):
        self.owned()
        return "type=volume,source=" + self.record["name"] + ",target=/data/db,volume-nocopy"

    def quiescent(self, *, allowed=()):
        """Trusted callers may exempt only their independently verified fixed helper IDs."""
        self.owned()
        if any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in allowed):
            raise ValueError("Invalid owned helper reference")
        permitted = set(allowed)
        item = self.record["command"]
        if item is not None:
            permitted.add(self.inspect_container(item)["Id"])
        _, users = self.call(
            "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "volume=" + self.record["name"]
        )
        if any(v not in permitted for v in users.splitlines()):
            raise ValueError("Another container references the database; nothing was stopped")

    def result(self, action, raw):
        value = json.loads(raw)
        if action in RESTORE_ACTIONS:
            return self.restore_result(action, value)
        if action == "export":
            expected = self.export_result(self.record["command"]["export_id"])
            if value != expected or expected["image_id"] != self.record["command"]["image"]:
                raise ValueError("The snapshot acknowledgement differs from its private files/image")
            return expected
        if action == "empty":
            if (
                not isinstance(value, dict)
                or set(value) != {"storage", "empty"}
                or value["storage"] != self.binding()
                or value["empty"] is not True
            ):
                raise ValueError("The fixed empty-database acknowledgement changed")
            return value
        if action != "fingerprint":
            if value != self.binding():
                raise ValueError("The database ownership acknowledgement changed")
            return value
        if (
            not isinstance(value, dict)
            or set(value) != {"storage", "database"}
            or value["storage"] != self.binding()
            or not isinstance(value["database"], dict)
            or set(value["database"]) != {"main", "-wal", "-journal"}
            or not isinstance(value["database"]["main"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["database"]["main"])
            or value["database"]["-journal"] is not None
            or value["database"]["-wal"] is not None
            and (
                not isinstance(value["database"]["-wal"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["database"]["-wal"])
            )
        ):
            raise ValueError("The fixed database fingerprint acknowledgement changed")
        return value

    def restore_result(self, action, value):
        item = self.record["command"]
        request = item["restore"]
        if action == "restore_status" and isinstance(value, dict) and value.get("phase") == "not_started":
            expected = {
                "schema": 1,
                "operation_id": request["operation_id"],
                "image_id": item["image"],
                "storage": self.binding(),
                "phase": "not_started",
            }
            if (
                set(value) != {*expected, "source"}
                or {key: value.get(key) for key in expected} != expected
                or type(value["schema"]) is not int
            ):
                raise ValueError("The unstarted restore acknowledgement changed")
            self.result("fingerprint", json.dumps({"storage": value["storage"], "database": value["source"]}))
            return value
        expected = {
            "schema": 1,
            "operation_id": request["operation_id"],
            "backup_id": request["backup_id"],
            "snapshot_identity": request["snapshot_identity"],
            "image_id": item["image"],
            "storage": self.binding(),
        }
        phases = {
            "restore_prepare": {"prepared", "applied", "aborted"},
            "restore_publish": {"applied"},
            "restore_abort": {"aborted"},
            "restore_status": {"preparing", "prepared", "publishing", "applied", "aborted"},
        }
        if (
            not isinstance(value, dict)
            or set(value) != {*expected, "source", "phase", "database_revision", "database_sha256", "actions"}
            or {key: value.get(key) for key in expected} != expected
            or type(value["schema"]) is not int
            or value["phase"] not in phases[action]
            or not isinstance(value["database_revision"], str)
            or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value["database_revision"])
            or value["database_sha256"] is not None
            and (
                not isinstance(value["database_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["database_sha256"])
            )
            or value["actions"] is not None
            and (
                not isinstance(value["actions"], dict)
                or value["actions"].get("automatic_replay") is not False
            )
            or value["phase"] in {"prepared", "publishing", "applied"}
            and (value["database_sha256"] is None or value["actions"] is None)
        ):
            raise ValueError("The fixed restore acknowledgement changed")
        self.result("fingerprint", json.dumps({"storage": value["storage"], "database": value["source"]}))
        return value

    def restore_backup(self, request):
        path = versions.canonical(Path(request["backup_path"]))
        private_directory(path)
        if path.is_relative_to(self.data) or self.data.is_relative_to(path):
            raise ValueError("The standalone restore source must stay outside application data")
        from desktop_upgrade_image import data_digest

        receipt = json.loads(versions.read_private(path / "receipt.json", 16384))
        if (
            not isinstance(receipt, dict)
            or receipt.get("operation_id") != request["backup_id"]
            or receipt.get("database_sha256") != request["database_sha256"]
            or data_digest(path / "database.sqlite") != request["database_sha256"]
        ):
            raise ValueError("The selected restore database changed")
        return path

    def restore_authority(self, request):
        path = self.root / "restores" / request["operation_id"] / "authority"
        private_directory(path)
        if {p.name for p in path.iterdir()} != {"administrator.json"}:
            raise ValueError("Use only the fixed private administrator recovery file")
        versions.read_private(path / "administrator.json", 4096)
        return path

    def restore_database(self, action, request):
        request = restore_request(request)
        action = "restore_" + action
        if action not in RESTORE_ACTIONS:
            raise ValueError("Choose a fixed database restore action")
        self.owned()
        item = self.record["command"]
        if item is not None:
            if item["action"] not in RESTORE_ACTIONS or item["restore"] != request:
                raise ValueError("Another database helper is pending")
            if item["interrupted"]:
                self.interrupt_restore(request)
                item = None
            elif item["action"] != action:
                raise ValueError("Finish the previous fixed restore helper first")
            elif item["phase"] == "finished":
                result = self.restore_result(action, item["restore_result"])
                self.cleanup()
                self.quiescent()
                return result
        self.quiescent()
        if action == "restore_prepare" and (item is None or item["phase"] in {"creating", "created"}):
            self.restore_backup(request)
            if request["recover_admin"]:
                self.restore_authority(request)
        result = self.helper(action, restore=request)
        self.quiescent()
        return result

    def interrupt_restore(self, request):
        """Stop only a verified staging helper; publication must be inspected/resumed."""
        request = restore_request(request)
        self.owned()
        item = self.record["command"]
        if item is None or item["action"] != "restore_prepare" or item["restore"] != request:
            raise ValueError("Only this owned restore preparation may be interrupted")
        present = True
        if item["phase"] == "finished":
            _, observed = self.call(
                "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + item["container_id"]
            )
            if observed not in ("", item["container_id"]):
                raise ValueError("The owned restore helper inventory changed")
            present = bool(observed)
        if present:
            current = self.inspect_container(item)
            item["container_id"] = current["Id"]
            if current["State"]["Running"]:
                self.call("container", "stop", "--time", "5", current["Id"])
                if self.inspect_container(item)["State"]["Running"]:
                    raise ValueError("The owned restore staging helper is still stopping")
        item.update(phase="finished", interrupted=True, restore_result=None)
        self.save()
        self.cleanup()
        return {"operation_id": request["operation_id"], "status": "inspection_required"}

    def export_path(self, operation):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise ValueError("Use a canonical export UUID")
        path = self.root / "database-exports"
        private_directory(path)
        path /= operation
        private_directory(path)
        return path

    def export_result(self, operation):
        path = self.export_path(operation)
        value = json.loads(versions.read_private(path / "receipt.json", 16384))
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema",
                "operation_id",
                "image_id",
                "storage",
                "source",
                "database_sha256",
                "database_bytes",
                "database_revision",
            }
            or type(value["schema"]) is not int
            or value["schema"] != 1
            or value["operation_id"] != operation
            or not isinstance(value["image_id"], str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", value["image_id"])
            or value["storage"] != self.binding()
            or type(value["database_bytes"]) is not int
            or value["database_bytes"] < 1
            or not isinstance(value["database_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["database_sha256"])
            or not isinstance(value["database_revision"], str)
            or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value["database_revision"])
        ):
            raise ValueError("The private database snapshot receipt changed")
        # Reuse the strict fixed-source hash shape, without opening SQLite natively.
        self.result("fingerprint", json.dumps({"storage": value["storage"], "database": value["source"]}))
        from desktop_upgrade_image import data_digest, data_info

        database = path / "database.sqlite"
        if (
            data_info(database).st_size != value["database_bytes"]
            or data_digest(database) != value["database_sha256"]
        ):
            raise ValueError("The exported database bytes changed")
        return value

    def valid_helper_mounts(self, item, mounts):
        exporting = item["action"] == "export"
        restoring = item["action"] in RESTORE_ACTIONS
        preparing = item["action"] == "restore_prepare"
        targets = {"/database"}
        if exporting:
            targets.add("/export")
        if preparing:
            targets.add("/restore")
            if item["restore"]["recover_admin"]:
                targets.add("/recovery-authority")
        if not isinstance(mounts, list) or len(mounts) != len(targets):
            return False
        if any(not isinstance(m, dict) for m in mounts):
            return False
        destinations = {m.get("Destination"): m for m in mounts}
        if set(destinations) != targets:
            return False
        database = destinations["/database"]
        if (
            database.get("Type") != "volume"
            or database.get("Name") != self.record["name"]
            or database.get("Source") != self.record["volume"]["Mountpoint"]
            or database.get("RW") is not (item["action"] == "initialize" or restoring)
        ):
            return False
        if exporting:
            output = destinations["/export"]
            if (
                output.get("Type") != "bind"
                or output.get("Source") != str(self.export_path(item["export_id"]))
                or output.get("RW") is not True
            ):
                return False
        if preparing:
            # Ownership must remain inspectable if a removable backup or the
            # private password file disappears after dispatch. Content/private
            # path checks run before creating/starting a new staging helper.
            sources = {"/restore": Path(item["restore"]["backup_path"])}
            if item["restore"]["recover_admin"]:
                sources["/recovery-authority"] = (
                    self.root / "restores" / item["restore"]["operation_id"] / "authority"
                )
            for target, source in sources.items():
                mount = destinations[target]
                if (
                    mount.get("Type") != "bind"
                    or mount.get("Source") != str(source)
                    or mount.get("RW") is not False
                ):
                    return False
        return True

    def export_database(self, operation):
        """A standalone DB snapshot only; full files export/restore is separate."""
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise ValueError("Use a canonical export UUID")
        self.owned()
        pending = self.record["command"]
        if pending is not None and (pending["action"] != "export" or pending["export_id"] != operation):
            raise ValueError("Another database helper is pending")
        folder = self.root / "database-exports"
        folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(folder)
        path = folder / operation
        if pending is None and path.exists():
            self.export_path(operation)
            if list(path.iterdir()):
                return self.export_result(operation)  # Completed or partial, never replay a write.
        elif pending is None:
            path.mkdir(mode=0o700)
        self.export_path(operation)
        if pending is not None and pending["phase"] == "finished":
            value = self.export_result(operation)
            self.cleanup()
        else:
            self.quiescent()
            value = self.helper("export", export_id=operation)
        self.quiescent()
        return value

    def cancel_export(self, operation):
        """Stop only this exact owned helper; keep completed/partial export bytes."""
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise ValueError("Use a canonical export UUID")
        self.owned()
        item = self.record["command"]
        if item is None or item["action"] != "export" or item["export_id"] != operation:
            raise ValueError("There is no matching owned database export to cancel")
        present = True
        if item["phase"] == "finished":
            _, observed = self.call(
                "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + item["container_id"]
            )
            if observed not in ("", item["container_id"]):
                raise ValueError("The owned export inventory changed")
            present = bool(observed)
        if present:
            current = self.inspect_container(item)
            item["container_id"] = current["Id"]
            if current["State"]["Running"]:
                self.call("container", "stop", "--time", "5", current["Id"])
                if self.inspect_container(item)["State"]["Running"]:
                    raise ValueError("The owned export is still stopping; nothing else was signaled")
        if item["phase"] != "finished":
            item["phase"] = "finished"
            self.save()
        # Root/file/marker validation still applies; no SQLite is opened natively.
        completed = (self.export_path(operation) / "receipt.json").exists()
        value = self.export_result(operation) if completed else None
        if not completed:
            write(
                self.export_path(operation) / "canceled.json",
                {"schema": 1, "operation_id": operation, "storage": self.binding()},
            )
        self.cleanup()
        return {
            "operation_id": operation,
            "status": "completed" if completed else "canceled",
            "database": value,
        }

    def arguments(self, action):
        if action in RESTORE_ACTIONS:
            item = self.record["command"]
            request = item["restore"]
            args = [
                "-B",
                "-m",
                "app.desktop_restore",
                action.removeprefix("restore_"),
                "--operation-id",
                request["operation_id"],
                "--image-id",
                item["image"],
                *self.arguments("inspect")[3:],
            ]
            if action == "restore_prepare":
                args += [
                    "--backup-id",
                    request["backup_id"],
                    "--snapshot-identity",
                    request["snapshot_identity"],
                    "--database-sha256",
                    request["database_sha256"],
                ]
                if request["recover_admin"]:
                    args.append("--recover-admin")
            return args
        if action == "export":
            ordinary = self.arguments("inspect")
            return [
                "-B",
                "-m",
                "app.desktop_snapshot",
                "export",
                "--operation-id",
                self.record["command"]["export_id"],
                "--image-id",
                self.record["command"]["image"],
                *ordinary[3:],
            ]
        return [
            "-IB",
            "/app/backend/app/desktop_storage.py",
            action,
            "--storage-id",
            self.record["storage_id"],
            "--namespace",
            self.namespace,
            "--uid",
            str(self.record["uid"]),
            "--gid",
            str(self.record["gid"]),
        ]

    def inspect_container(self, item):
        _, raw = self.call(
            "container", "inspect", item["container_id"] or "ai-station-database-" + item["attempt"]
        )
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("The owned database helper is missing")
        v = rows[0]
        cfg, host, state = (v.get(k, {}) for k in ("Config", "HostConfig", "State"))
        initialize = item["action"] == "initialize"
        mounts = v.get("Mounts")
        if (
            not isinstance(v.get("Id"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", v["Id"])
            or item["container_id"] is not None
            and v["Id"] != item["container_id"]
            or v.get("Name") != "/ai-station-database-" + item["attempt"]
            or v.get("Image") != item["image"]
            or cfg.get("Image") != item["image"]
            or cfg.get("User") != ("0:0" if initialize else f"{self.record['uid']}:{self.record['gid']}")
            or cfg.get("Entrypoint") != ["python"]
            or cfg.get("Cmd") != self.arguments(item["action"])
            or (cfg.get("Labels") or {}).get(LABEL) != self.record["storage_id"]
            or (cfg.get("Labels") or {}).get(LABEL + ".attempt") != item["attempt"]
            or host.get("NetworkMode") != "none"
            or host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True
            or host.get("CapDrop") != ["ALL"]
            or (
                host.get("CapAdd") not in (["CHOWN"], ["CAP_CHOWN"])
                if initialize
                else host.get("CapAdd") not in (None, [])
            )
            or host.get("SecurityOpt") not in (["no-new-privileges"], ["no-new-privileges:true"])
            or host.get("AutoRemove") is not False
            or host.get("RestartPolicy", {}).get("Name") != "no"
            or host.get("Memory") != (RESTORE_MEMORY if item["action"] in RESTORE_ACTIONS else MEMORY)
            or host.get("MemorySwap") != (RESTORE_MEMORY if item["action"] in RESTORE_ACTIONS else MEMORY)
            or host.get("PidsLimit") != 16
            or host.get("NanoCpus") != 1_000_000_000
            or host.get("PidMode") != ""
            or host.get("IpcMode") != "private"
            or host.get("Devices")
            or host.get("DeviceRequests")
            or host.get("PortBindings")
            or host.get("Binds")
            or host.get("Tmpfs")
            or not self.valid_helper_mounts(item, mounts)
            or state.get("Status") not in ("created", "running", "exited")
            or state.get("Running") is not (state.get("Status") == "running")
            or type(state.get("ExitCode")) is not int
            or type(state.get("OOMKilled")) is not bool
        ):
            raise ValueError("Database helper identity or isolation changed; nothing was signaled")
        return v

    def helper(self, action, *, export_id=None, restore=None):
        if action in RESTORE_ACTIONS:
            restore_request(restore)
        elif restore is not None:
            raise ValueError("Only fixed restore commands accept a restore request")
        if action == "export":
            if not isinstance(export_id, str) or str(UUID(export_id)) != export_id:
                raise ValueError("Use a canonical export UUID")
        elif export_id is not None:
            raise ValueError("Only the fixed snapshot action accepts an export UUID")
        if (action, self.record["phase"]) not in (
            ("initialize", "created"),
            ("inspect", "initialized"),
            ("inspect", "ready"),
            ("fingerprint", "ready"),
            ("empty", "ready"),
            ("export", "ready"),
            *((value, "ready") for value in RESTORE_ACTIONS),
        ):
            raise ValueError("Only the fixed helper for the current storage phase may run")
        self.owned()
        item = self.record["command"]
        if item is None:
            image = (
                self.record["initialization_image"] if action == "initialize" else self.package["image_id"]
            )
            _, raw = self.call("image", "inspect", image)
            images = json.loads(raw)
            if (
                not isinstance(images, list)
                or len(images) != 1
                or any(
                    images[0].get(k) != v
                    for k, v in {"Id": image, "Os": "linux", "Architecture": self.architecture}.items()
                )
            ):
                raise ValueError("The database helper requires the verified local image")
            item = {
                "attempt": uuid4().hex,
                "action": action,
                "image": image,
                "phase": "creating",
                "container_id": None,
            }
            if action == "export":
                item["export_id"] = export_id
            if action in RESTORE_ACTIONS:
                item.update(restore=dict(restore), restore_result=None, interrupted=False)
            self.record["command"] = item
            self.save()
            args = [
                "container",
                "create",
                "--name",
                "ai-station-database-" + item["attempt"],
                "--label",
                LABEL + "=" + self.record["storage_id"],
                "--label",
                LABEL + ".attempt=" + item["attempt"],
                "--pull",
                "never",
                "--user",
                "0:0" if action == "initialize" else f"{self.record['uid']}:{self.record['gid']}",
                "--network",
                "none",
                "--restart",
                "no",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                str(RESTORE_MEMORY if action in RESTORE_ACTIONS else MEMORY),
                "--memory-swap",
                str(RESTORE_MEMORY if action in RESTORE_ACTIONS else MEMORY),
                "--pids-limit",
                "16",
                "--cpus",
                "1",
                "--no-healthcheck",
                "--mount",
                self.mount(readonly=action != "initialize" and action not in RESTORE_ACTIONS),
                "--entrypoint",
                "python",
            ]
            if action == "export":
                args += ["--mount", bind_mount(self.export_path(export_id), "/export")]
            if action == "restore_prepare":
                args += ["--mount", bind_mount(self.restore_backup(restore), "/restore") + ",readonly"]
                if restore["recover_admin"]:
                    args += [
                        "--mount",
                        bind_mount(self.restore_authority(restore), "/recovery-authority") + ",readonly",
                    ]
            if action == "initialize":
                args += ["--cap-add", "CHOWN"]
            _, identifier = self.call(*args, image, *self.arguments(action))
            if not re.fullmatch(r"[a-f0-9]{64}", identifier):
                raise ValueError("The database helper creation acknowledgement is uncertain")
            item["container_id"] = identifier
        elif (
            item["action"] != action
            or action == "export"
            and item["export_id"] != export_id
            or action in RESTORE_ACTIONS
            and item["restore"] != restore
        ):
            raise ValueError("Another database helper is pending")
        v = self.inspect_container(item)
        if item["phase"] == "creating":
            item.update(container_id=v["Id"], phase="created")
            self.save()
        if item["phase"] == "created":
            if action in ("initialize", "fingerprint", "empty", "export", *RESTORE_ACTIONS):
                self.quiescent()
            if action == "restore_prepare":
                self.restore_backup(restore)
                if restore["recover_admin"]:
                    self.restore_authority(restore)
            item["phase"] = "starting"
            self.save()
            self.call("container", "start", item["container_id"])
        deadline = time.monotonic() + 30
        while True:
            v = self.inspect_container(item)
            state = v["State"]
            if state["Status"] == "created":
                raise ValueError("The helper start acknowledgement is uncertain; it was not restarted")
            if not state["Running"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("The owned database helper is still running; inspect it before retrying")
            time.sleep(0.1)
        if state["ExitCode"] != 0 or state["OOMKilled"]:
            raise ValueError("The database helper failed; its bytes and pending receipt were preserved")
        _, raw = self.call("container", "logs", item["container_id"])
        result = self.result(action, raw)
        if action in RESTORE_ACTIONS:
            item["restore_result"] = result
        # Advance ownership before cleanup; a lost removal ACK can be reconciled
        # by exact ID, without ever reinitializing the persistent volume.
        self.record["phase"] = "initialized" if action == "initialize" else "ready"
        item["phase"] = "finished"
        self.save()
        self.cleanup()
        return result

    def cleanup(self):
        """Remove only a verified finished helper; persistent volume is untouched."""
        item = self.record["command"]
        if item is None or item["phase"] != "finished":
            raise ValueError("Only a finished owned database helper may be removed")
        self.owned()
        _, present = self.call(
            "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + item["container_id"]
        )
        if present:
            if present != item["container_id"]:
                raise ValueError("The database helper inventory changed")
            self.inspect_container(item)
            self.call("container", "rm", item["container_id"])
        self.record["command"] = None
        self.save()

    def prepare(self):
        if self.record["command"] is not None and self.record["command"]["phase"] == "finished":
            self.cleanup()
        if self.record["phase"] == "creating":
            if not self.fresh:
                raise ValueError(
                    "Volume creation acknowledgement is pending; inspect and resume the saved setup first"
                )
            self.fresh = False
            self.consistent()
            _, name = self.call(
                "volume",
                "create",
                "--driver",
                "local",
                "--label",
                LABEL + "=" + self.record["storage_id"],
                "--label",
                LABEL + ".namespace=" + self.namespace,
                self.record["name"],
            )
            if name != self.record["name"]:
                raise ValueError("The volume creation acknowledgement is uncertain")
            self.recover_creation()
        if self.record["phase"] == "created":
            self.helper("initialize")
        self.helper("inspect")
        self.owned()
        return self.record["name"]

    def fingerprint(self):
        if self.record["command"] is not None and self.record["command"]["phase"] == "finished":
            self.cleanup()
        self.quiescent()
        result = self.helper("fingerprint")
        self.quiescent()
        return result["database"]

    def identity(self, *, allow_pending_readonly=False):
        pending = self.record["command"]
        if type(allow_pending_readonly) is not bool:
            raise ValueError("Choose an explicit pending-reader policy")
        if (
            self.record["phase"] != "ready"
            or pending is not None
            and not (allow_pending_readonly and pending["action"] in ("inspect", "fingerprint", "empty"))
        ):
            raise ValueError("Database storage is not ready")
        self.owned()
        return stable_identity(self.record)

    def assert_empty(self):
        """Only the fixed image can prove a marker-only VM volume before first start."""
        if self.record["command"] is not None and self.record["command"]["phase"] == "finished":
            self.cleanup()
        self.quiescent()
        self.helper("empty")
        self.quiescent()
