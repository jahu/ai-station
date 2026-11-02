"""Fixed offline installer image commands; no web, Runner or arbitrary shell API."""

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

import desktop_versions as versions
from desktop_bridge import private_directory, read_json
from macos_transport_probe import bind_mount, command, private_file

FENCE = "desktop-upgrade-dispatch-pending.json"
MEMORY = 512 * 1024**2
ACTIONS = ("prepare", "publish", "abort", "status")


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, value):
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        private_file(path)
    descriptor, name = tempfile.mkstemp(prefix=".image-upgrade-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as target:
            json.dump(value, target, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
        sync(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def data_info(path):
    # Existing container-created SQLite files can be 0644 within the private
    # data root. Keep the backend's non-shared-write policy for these files;
    # installer receipts/configuration still require mode 0600.
    versions.canonical(path)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o022
    ):
        raise ValueError("Upgrade database files must remain ordinary owned non-shared-write files")
    return info


def data_digest(path):
    original = data_info(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        opened = os.fstat(source.fileno())
        if (
            (original.st_dev, original.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
        ):
            raise ValueError("The database identity changed during activation")
        return hashlib.file_digest(source, "sha256").hexdigest()


class UpgradeImage:
    """Caller holds the consented native handoff for this entire transaction."""

    def __init__(self, root, config, engine, previous, target, operation_id):
        from dotenv import dotenv_values

        if str(UUID(operation_id)) != operation_id:
            raise ValueError("Use a canonical desktop upgrade UUID")
        self.previous, self.target = map(versions.package_identity, (previous, target))
        if self.previous["bundle_id"] == self.target["bundle_id"]:
            raise ValueError("The desktop upgrade needs different verified bundles")
        self.architecture = {"x86_64": "amd64", "arm64": "arm64"}.get(target.get("architecture"))
        if self.architecture is None or engine.identity is None:
            raise ValueError("The desktop upgrade needs a verified architecture and local Docker connection")
        binary, endpoint = engine.identity
        if tuple(engine.prefix) != (binary, "--host", endpoint):
            raise ValueError("The upgrade Docker connection must remain pinned")
        self.root, self.config, self.identity = root, config, operation_id
        self.data, self.namespace = versions.namespace(config)
        if config.parent != root or root.is_relative_to(self.data):
            raise ValueError("Installer receipts must stay outside mounted application data")
        private_directory(root)
        from macos_database_storage import RECEIPT as STORAGE_RECEIPT
        from macos_database_storage import DatabaseStorage

        storage_path = self.storage_path = root / "database-storage" / STORAGE_RECEIPT
        self.storage = (
            DatabaseStorage(root, config, engine, target)
            if storage_path.exists() or storage_path.is_symlink()
            else None
        )
        self.runtime = self.data / "runtime"
        private_directory(self.runtime)
        self.project = dotenv_values(config, interpolate=False)["COMPOSE_PROJECT_NAME"]
        self.folder = root / "image-upgrades"
        self.folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.folder)
        self.folder /= operation_id
        self.folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.folder)
        expected = {
            "schema": 1,
            "operation_id": operation_id,
            "previous": self.previous,
            "target": self.target,
            "namespace_sha256": self.namespace,
            "project": self.project,
            "architecture": self.architecture,
            "engine": list(engine.identity),
            **(
                {"database_storage": self.storage.identity(allow_pending_readonly=True)}
                if self.storage
                else {}
            ),
        }
        path = self.folder / "request.json"
        if path.exists() or path.is_symlink():
            self.request = read_json(path)
            if {k: self.request.get(k) for k in expected} != expected or set(self.request) != {
                *expected,
                "previous_receipt",
                "activation_owner",
            }:
                raise ValueError("The image upgrade belongs to different package/storage/engine input")
        else:
            receipt = versions.load(root)
            if (
                receipt["phase"] != "ready"
                or receipt["package"] != self.previous
                or receipt["namespace_sha256"] != self.namespace
                or self.target["source_epoch"] < self.previous["source_epoch"]
            ):
                raise ValueError("The previous desktop version is not ready for this upgrade")
            self.request = expected | {"previous_receipt": receipt, "activation_owner": uuid4().hex}
            write(path, self.request)
            write(self.folder / "state.json", {"commands": {}, "current": None, "final": None})
        client = self.folder / "client"
        client.mkdir(mode=0o700, exist_ok=True)
        private_directory(client)
        client_config = client / "config.json"
        if client_config.exists() or client_config.is_symlink():
            if read_json(client_config) != {}:
                raise ValueError("The private upgrade Docker configuration changed")
        else:
            write(client_config, {})
        self.argv = [*engine.prefix, "--config", str(client)]
        self.environment = {"PATH": str(Path(binary).parent) + os.pathsep + os.defpath, "LANG": "C"}
        digest = hashlib.sha256(json.dumps(self.request, sort_keys=True).encode()).hexdigest()
        self.fence = {"operation_id": operation_id, "request_sha256": digest}
        self.consistent()

    def state(self):
        value = read_json(self.folder / "state.json")
        if (
            set(value) != {"commands", "current", "final"}
            or not isinstance(value["commands"], dict)
            or len(value["commands"]) > 64
            or value["current"] is not None
            and (not isinstance(value["current"], str) or value["current"] not in value["commands"])
        ):
            raise ValueError("The private image command journal needs inspection")
        for attempt, item in value["commands"].items():
            if (
                not re.fullmatch(r"[a-f0-9]{32}", attempt)
                or not isinstance(item, dict)
                or set(item)
                not in (
                    {"attempt", "action", "name", "phase", "container_id", "result", "cleanup_complete"},
                    {
                        "attempt",
                        "action",
                        "name",
                        "phase",
                        "container_id",
                        "result",
                        "cleanup_complete",
                        "exit_code",
                    },
                )
                or item["attempt"] != attempt
                or item["action"] not in ACTIONS
                or item["name"] != "ai-station-upgrade-" + attempt
                or item["phase"] not in ("creating", "created", "starting", "finished")
                or type(item["cleanup_complete"]) is not bool
                or item["cleanup_complete"]
                and item["phase"] != "finished"
                or item["container_id"] is not None
                and (
                    not isinstance(item["container_id"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", item["container_id"])
                )
                or item["phase"] != "creating"
                and item["container_id"] is None
                or item["phase"] == "finished"
                and type(item.get("exit_code")) is not int
                or item["result"] is not None
                and item["phase"] != "finished"
            ):
                raise ValueError("The recorded image command identity changed")
            if item["result"] is not None:
                self.result(json.dumps(item["result"]), item["action"])
        if value["current"] is None and any(
            not item["cleanup_complete"] for item in value["commands"].values()
        ):
            raise ValueError("An unfinished image command lost its pending identity")
        if value["final"] is not None:
            self.result(json.dumps(value["final"]), "status")
            if value["current"] is not None or value["final"]["phase"] not in ("applied", "aborted"):
                raise ValueError("The final image upgrade receipt is invalid")
        return value

    def save(self, state):
        write(self.folder / "state.json", state)

    def consistent(self):
        if (self.storage_path.exists() or self.storage_path.is_symlink()) != (self.storage is not None):
            raise ValueError("The desktop database storage receipt changed")
        if versions.namespace(self.config) != (self.data, self.namespace):
            raise ValueError("The desktop storage changed during image upgrade")
        if read_json(self.folder / "request.json") != self.request:
            raise ValueError("The image upgrade request changed")
        if (
            self.storage
            and self.storage.identity(allow_pending_readonly=True) != self.request["database_storage"]
        ):
            raise ValueError("The image upgrade database volume changed")

    def call(self, *args, **kwargs):
        return command([*self.argv, *args], env=self.environment, **kwargs)

    def quiescent(self):
        self.consistent()
        _, output = self.call(
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=" + self.project,
        )
        if output:
            raise RuntimeError("The configured Compose project still has containers; inspect its shutdown")
        if self.storage:
            state = self.state()
            allowed = ()
            if state["current"] is not None:
                item = state["commands"][state["current"]]
                if item["container_id"] is not None:
                    allowed = (self.inspect(item)["Id"],)
            self.storage.quiescent(allowed=allowed)

    def valid_mounts(self, mounts):
        expected = {"/data": ("bind", str(self.data))}
        if self.storage:
            self.storage.owned()
            expected["/data/db"] = ("volume", self.storage.record["volume"]["Mountpoint"])
        if not isinstance(mounts, list) or len(mounts) != len(expected):
            return False
        if any(not isinstance(m, dict) for m in mounts):
            return False
        if {m.get("Destination") for m in mounts} != set(expected):
            return False
        for m in mounts:
            kind, source = expected[m["Destination"]]
            if m.get("Type") != kind or m.get("Source") != source or m.get("RW") is not True:
                return False
            if kind == "volume" and (
                m.get("Name") != self.storage.record["name"] or m.get("Driver") != "local"
            ):
                return False
        return True

    def image(self):
        _, output = self.call("image", "inspect", self.target["image_id"])
        values = json.loads(output)
        if (
            not isinstance(values, list)
            or len(values) != 1
            or (
                values[0].get("Id") != self.target["image_id"]
                or values[0].get("Os") != "linux"
                or values[0].get("Architecture") != self.architecture
            )
        ):
            raise ValueError("The upgrade image is not the verified bundled architecture")

    def arguments(self, action):
        args = ["-m", "app.desktop_upgrade", action, "--operation-id", self.identity]
        if action == "prepare":
            args += [
                "--previous-bundle",
                self.previous["bundle_id"],
                "--target-bundle",
                self.target["bundle_id"],
            ]
        return args

    def inspect(self, item):
        reference = item.get("container_id") or item["name"]
        _, raw = self.call("container", "inspect", reference)
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != 1:
            raise ValueError("Unexpected upgrade container inventory")
        value = values[0]
        cfg, host, process = (value.get(k, {}) for k in ("Config", "HostConfig", "State"))
        labels = cfg.get("Labels") or {}
        mounts = value.get("Mounts")
        identifier = value.get("Id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or item.get("container_id") is not None
            and identifier != item["container_id"]
            or value.get("Name") != "/" + item["name"]
            or value.get("Image") != self.target["image_id"]
            or cfg.get("Image") != self.target["image_id"]
            or cfg.get("User") != f"{os.geteuid()}:{os.getegid()}"
            or cfg.get("Entrypoint") != ["python"]
            or cfg.get("Cmd") != self.arguments(item["action"])
            or labels.get("ai-station.desktop-upgrade") != self.identity
            or labels.get("ai-station.desktop-upgrade-attempt") != item["attempt"]
            or host.get("NetworkMode") != "none"
            or host.get("PidMode") != ""
            or host.get("IpcMode") != "private"
            or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=67108864"}
            or host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True
            or host.get("AutoRemove") is not False
            or host.get("RestartPolicy", {}).get("Name") != "no"
            or host.get("Memory") != MEMORY
            or host.get("MemorySwap") != MEMORY
            or host.get("PidsLimit") != 32
            or host.get("NanoCpus") != 1_000_000_000
            or host.get("CapDrop") != ["ALL"]
            or host.get("SecurityOpt") not in (["no-new-privileges"], ["no-new-privileges:true"])
            or host.get("Devices")
            or host.get("DeviceRequests")
            or host.get("PortBindings")
            or not self.valid_mounts(mounts)
            or type(process.get("Running")) is not bool
            or type(process.get("ExitCode")) is not int
            or process.get("Status") not in ("created", "running", "exited")
            or process["Running"] != (process["Status"] == "running")
            or type(process.get("OOMKilled")) is not bool
        ):
            raise ValueError("Upgrade container identity or isolation changed; nothing was signaled")
        return value

    def result(self, raw, action):
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "operation_id",
                "phase",
                "schema_before",
                "schema_after",
                "backup_relative",
                "backup_verified",
            }
            or value["operation_id"] != self.identity
            or value["phase"] not in ("preparing", "prepared", "publishing", "applied", "aborted")
            or action != "status"
            and value["phase"] != {"prepare": "prepared", "publish": "applied", "abort": "aborted"}[action]
            or value["backup_relative"] != f"desktop-upgrades/{self.identity}/original.sqlite"
            or type(value["backup_verified"]) is not bool
            or action in ("prepare", "publish")
            and not value["backup_verified"]
            or any(
                not isinstance(value[k], str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value[k])
                for k in ("schema_before", "schema_after")
            )
        ):
            raise ValueError("The offline upgrade returned an invalid transaction receipt")
        return value

    def mark_pending(self):
        path = self.runtime / FENCE
        if path.exists() or path.is_symlink():
            if read_json(path) != self.fence:
                raise ValueError("Another image upgrade owns the startup fence")
        else:
            write(path, self.fence)

    def cleanup(self, item):
        identifier = item["container_id"]
        _, present = self.call(
            "container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + identifier
        )
        if not present:
            return  # Exact known ID was already removed; never a reserved-name guess.
        if present != identifier:
            raise ValueError("The upgrade container inventory changed")
        value = self.inspect(item)
        if value["State"]["Running"]:
            raise RuntimeError("The upgrade container is still running; cleanup was not attempted")
        self.call("container", "rm", identifier)

    def resume(self, *, timeout=180):
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError("Use a positive bounded image upgrade timeout")
        self.consistent()
        state = self.state()
        attempt = state["current"]
        if attempt is None:
            return state["final"]
        if read_json(self.runtime / FENCE) != self.fence:
            raise ValueError("The image upgrade startup fence changed")
        item = state["commands"][attempt]
        if item["phase"] == "finished":
            self.cleanup(item)
        else:
            value = self.inspect(item)  # Also adopts a lost create ACK by exact name/labels/command.
            item["container_id"] = value["Id"]
            if item["phase"] == "creating":
                if value["State"]["Status"] != "created":
                    raise ValueError("An unacknowledged upgrade creation already ran; inspect it")
                item["phase"] = "created"
                self.save(state)
            if item["phase"] == "created":
                self.quiescent()
                if self.storage:
                    self.storage.prepare()  # Read-only marker verification; never initialize ready storage.
                    self.quiescent()
                item["phase"] = "starting"  # Durable before the one permitted start request.
                self.save(state)
                self.call("container", "start", item["container_id"])
            deadline = time.monotonic() + timeout
            while True:
                value = self.inspect(item)
                process = value["State"]
                if process["Status"] == "created":
                    raise RuntimeError(
                        "The start acknowledgement is uncertain; the command was not restarted"
                    )
                if not process["Running"]:
                    break
                if time.monotonic() >= deadline:
                    # Only the fully verified owned container, never the CLI PID or a broad name.
                    self.call("container", "stop", "--time", "15", item["container_id"])
                    raise RuntimeError("The offline upgrade timed out; inspect its retained transaction")
                time.sleep(0.1)
            item["exit_code"] = process["ExitCode"]
            if process["ExitCode"] == 0 and not process["OOMKilled"]:
                _, output = self.call("container", "logs", item["container_id"])
                item["result"] = self.result(output, item["action"])
            item["phase"] = "finished"
            self.save(state)
            self.cleanup(item)
        item["cleanup_complete"] = True
        state["current"] = None
        self.save(state)
        if item.get("result") is None:
            raise RuntimeError("The offline upgrade failed; inspect or abort its retained transaction")
        return item["result"]

    def run(self, action, *, timeout=180):
        if action not in ACTIONS:
            raise ValueError("Only fixed offline desktop upgrade actions are allowed")
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError("Use a positive bounded image upgrade timeout")
        state = self.state()
        if state["final"] is not None:
            return state["final"]  # Lost final ACK: no engine operation or replay.
        if state["current"] is not None:
            if state["commands"][state["current"]]["action"] != action:
                raise RuntimeError("Inspect the pending image command before starting another")
            return self.resume(timeout=timeout)
        if action != "status":
            prior = [v for v in state["commands"].values() if v["action"] == action]
            if prior:
                if prior[-1].get("result") is None:
                    raise RuntimeError("The previous command failed; it was not repeated")
                return prior[-1]["result"]
        if len(state["commands"]) >= 64:
            raise RuntimeError("The upgrade has too many retained attempts; inspect its history")
        self.quiescent()
        self.image()
        self.mark_pending()
        attempt = uuid4().hex
        item = {
            "attempt": attempt,
            "action": action,
            "name": "ai-station-upgrade-" + attempt,
            "phase": "creating",
            "container_id": None,
            "result": None,
            "cleanup_complete": False,
        }
        state["commands"][attempt] = item
        state["current"] = attempt
        self.save(state)
        _, identifier = self.call(
            "container",
            "create",
            "--name",
            item["name"],
            "--label",
            "ai-station.desktop-upgrade=" + self.identity,
            "--label",
            "ai-station.desktop-upgrade-attempt=" + attempt,
            "--platform",
            "linux/" + self.architecture,
            "--pull",
            "never",
            "--user",
            f"{os.geteuid()}:{os.getegid()}",
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
            str(MEMORY),
            "--memory-swap",
            str(MEMORY),
            "--pids-limit",
            "32",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=67108864",
            "--no-healthcheck",
            "--mount",
            bind_mount(self.data, "/data"),
            *(["--mount", self.storage.application_mount()] if self.storage else []),
            "--env",
            "AI_STATION_DATA_DIR=/data",
            "--entrypoint",
            "python",
            self.target["image_id"],
            *self.arguments(action),
        )
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("The upgrade creation acknowledgement needs inspection")
        item["container_id"], item["phase"] = identifier, "created"
        self.save(state)
        return self.resume(timeout=timeout)

    def finish(self, *, activate):
        """Publish native version identity before allowing normal startup again."""
        self.consistent()
        state = self.state()
        if state["current"] is not None:
            raise RuntimeError("Finish the pending image command before activation")
        fence_path = self.runtime / FENCE
        if state["final"] is not None and not (fence_path.exists() or fence_path.is_symlink()):
            return state["final"]
        if type(activate) is not bool:
            raise ValueError("Choose explicit target activation or confirmed abort")
        action, phase = ("publish", "applied") if activate else ("abort", "aborted")
        results = [
            v
            for v in state["commands"].values()
            if v["action"] == action and v["cleanup_complete"] and v.get("result")
        ]
        if not results or results[-1]["result"]["phase"] != phase:
            raise ValueError("The image transaction has not confirmed publication/abort")
        if read_json(self.runtime / FENCE) != self.fence:
            raise ValueError("The startup fence belongs to another upgrade")
        self.quiescent()
        transaction = versions.canonical(self.data / "desktop-upgrades" / self.identity)
        private_directory(transaction)
        backend_request = read_json(transaction / "request.json")
        backend_state = read_json(transaction / "state.json")
        request_hash = hashlib.sha256(
            json.dumps(backend_request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = results[-1]["result"]
        if (
            backend_request.get("operation_id") != self.identity
            or backend_request.get("previous_bundle") != self.previous["bundle_id"]
            or backend_request.get("target_bundle") != self.target["bundle_id"]
            or backend_state.get("request_identity") != request_hash
            or backend_state.get("phase") != phase
            or any(backend_request.get(k) != result[k] for k in ("schema_before", "schema_after"))
            or (self.runtime / "desktop-upgrade-pending.json").exists()
            or (self.runtime / "desktop-upgrade-pending.json").is_symlink()
        ):
            raise ValueError("The offline data transaction no longer confirms activation/abort")
        observed = self.database_fingerprint()
        actual = observed["main"]
        expected_hash = (
            backend_state.get("staged_sha256") if activate else backend_request.get("source", {}).get("main")
        )
        if actual != expected_hash:
            raise ValueError("The database changed after the acknowledged offline transaction")
        for suffix in ("-wal", "-journal"):
            expected_sidecar = None if activate else backend_request.get("source", {}).get(suffix)
            if observed[suffix] != expected_sidecar:
                raise ValueError("Unexpected database sidecar writes require inspection before activation")
        old = self.request["previous_receipt"]
        expected = (
            old
            | {
                "phase": "starting",
                "package": self.target,
                "owner_instance_id": self.request["activation_owner"],
            }
            if activate
            else old
        )
        current = versions.load(self.root)
        if current != expected:
            if not activate or current != old:
                raise ValueError("The native version receipt changed before activation")
            versions.save(self.root, expected)
        state["final"] = results[-1]["result"]
        self.save(state)
        (self.runtime / FENCE).unlink()
        sync(self.runtime)
        return state["final"]

    def database_fingerprint(self):
        if self.storage:
            return self.storage.fingerprint()
        database = versions.canonical(self.data / "db/ai-station.sqlite")
        result = {"main": data_digest(database)}
        for suffix in ("-wal", "-journal", "-shm"):
            path = database.with_name(database.name + suffix)
            value = None
            if path.exists() or path.is_symlink():
                info = data_info(path)
                if suffix != "-shm" and info.st_size:
                    value = data_digest(path)
            if suffix != "-shm":
                result[suffix] = value
        return result
