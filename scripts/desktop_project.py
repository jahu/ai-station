"""Private Linux/WSL desktop Compose ownership; never an HTTP or workload API."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from io import StringIO
from pathlib import Path

from desktop_versions import canonical, directory, read_private

RECEIPT = "desktop-compose-owner.json"
SERVICES = frozenset({"ai-station", "worker", "scheduler", "search"})
HEX = r"[a-f0-9]{64}"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def container_ids(text):
    ids = text.split()
    if (
        len(ids) > len(SERVICES)
        or len(set(ids)) != len(ids)
        or any(not re.fullmatch(HEX, item) for item in ids)
    ):
        raise ValueError("Inspect the unexpected desktop Compose inventory")
    return ids


class DesktopProject:
    def __init__(self, config, env, engine, inventory, source):
        from dotenv import dotenv_values

        self.config = canonical(config)
        self.root = self.config.parent
        if directory(self.root).st_mode & 0o077:
            raise ValueError("Desktop Compose ownership needs private native storage")
        values = dotenv_values(stream=StringIO(read_private(self.config, 65536).decode()), interpolate=False)
        self.data = canonical(env["AI_STATION_DATA_HOST_PATH"])
        self.project = env.get("COMPOSE_PROJECT_NAME", "")
        if (
            self.data != self.root / "data"
            or values.get("AI_STATION_DATA_HOST_PATH") != str(self.data)
            or values.get("COMPOSE_PROJECT_NAME") != self.project
            or values.get("AI_STATION_ACCESS_PROFILE") != "accounts"
            or not isinstance(self.project, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.project)
        ):
            raise ValueError("Desktop Compose configuration and private namespace differ")
        self.engine = engine
        self.inventory = inventory
        self.source = canonical(source)
        self.path = self.root / RECEIPT
        self.namespace = self.current_namespace()
        self.record = self.load()

    def current_namespace(self):
        return {
            "project": self.project,
            "uid": os.geteuid(),
            "root": str(self.root),
            "data": str(self.data),
            # Device numbers can change when WSL remounts its disk. On ext4,
            # f_fsid derives from the filesystem UUID, not device enumeration.
            "directories": [
                [os.statvfs(path).f_fsid, directory(path).st_ino] for path in (self.root, self.data)
            ],
        }

    def docker(self, *arguments):
        result = subprocess.run(
            self.engine.command(*arguments),
            env=self.engine.environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        if len(result.stdout.encode()) > 2 * 1024**2:
            raise ValueError("Desktop Docker observation exceeds its expected bound")
        return result.stdout

    def daemon(self):
        value = self.docker("info", "--format", "{{.ID}}").strip()
        if not re.fullmatch(r"[A-Za-z0-9:_-]{8,128}", value):
            raise ValueError("Docker returned an invalid desktop daemon identity")
        return value

    def load(self):
        try:
            value = json.loads(read_private(self.path, 16384))
        except FileNotFoundError:
            return None
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "namespace", "daemon", "containers"}
            or type(value["schema"]) is not int
            or value["schema"] != 1
            or value["namespace"] != self.namespace
            or not isinstance(value["daemon"], str)
            or not re.fullmatch(r"[A-Za-z0-9:_-]{8,128}", value["daemon"])
            or not isinstance(value["containers"], dict)
            or len(value["containers"]) != len(SERVICES)
        ):
            raise ValueError("Desktop Compose ownership receipt is invalid or belongs to different storage")
        seen = set()
        for identity, item in value["containers"].items():
            if (
                not re.fullmatch(HEX, identity)
                or not isinstance(item, dict)
                or set(item) != {"service", "fingerprint"}
                or not isinstance(item["service"], str)
                or item["service"] not in SERVICES
                or item["service"] in seen
                or not isinstance(item["fingerprint"], str)
                or not re.fullmatch(HEX, item["fingerprint"])
            ):
                raise ValueError("Desktop Compose ownership receipt has an invalid container")
            seen.add(item["service"])
        return value

    def observe(self, ids, *, created=False):
        items = json.loads(self.docker("inspect", *ids))
        if not isinstance(items, list) or len(items) != len(ids):
            raise ValueError("Desktop container inspection is incomplete")
        result = {}
        services = set()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("Config"), dict):
                raise ValueError("Desktop container configuration is invalid")
            labels = item.get("Config", {}).get("Labels") or {}
            if not isinstance(labels, dict):
                raise ValueError("Desktop container labels are invalid")
            service = labels.get("com.docker.compose.service")
            if (
                item.get("Id") not in ids
                or item["Id"] in result
                or labels.get("com.docker.compose.project") != self.project
                or not isinstance(service, str)
                or service not in SERVICES
                or service in services
                or labels.get("com.docker.compose.oneoff") != "False"
                or labels.get("com.docker.compose.container-number") != "1"
                or not isinstance(item.get("Mounts"), list)
                or not isinstance(item.get("HostConfig"), dict)
                or not isinstance(item.get("Image"), str)
                or not re.fullmatch("sha256:" + HEX, item["Image"])
            ):
                raise ValueError("An unexpected container belongs to this desktop project")
            if created and (
                labels.get("com.docker.compose.project.working_dir") != str(self.source)
                or service != "search"
                and not any(
                    isinstance(mount, dict)
                    and mount.get("Type") == "bind"
                    and mount.get("Destination") == "/data"
                    and mount.get("Source") == str(self.data)
                    for mount in item["Mounts"]
                )
            ):
                raise ValueError("New desktop containers do not match the launched package/data")
            immutable = {key: item[key] for key in ("Config", "HostConfig", "Image")}
            # Docker's mount inventory is unordered; comparison must not depend
            # on the daemon's map enumeration before/after a restart.
            immutable["Mounts"] = sorted(item["Mounts"], key=lambda value: json.dumps(value, sort_keys=True))
            result[item["Id"]] = {
                "service": service,
                # Configuration can contain credentials. Persist only its hash,
                # never raw environment, logs, setup links, PIDs or process state.
                "fingerprint": digest(immutable),
            }
            services.add(service)
        return result

    def recover(self, ids):
        """Caller holds launcher.lock. Validate the entire inventory before any stop."""
        if self.current_namespace() != self.namespace:
            raise ValueError("Desktop storage changed before recovery")
        if self.record is None:
            if ids:
                raise RuntimeError("Existing Compose containers have no private desktop ownership receipt")
            return
        if self.daemon() != self.record["daemon"]:
            raise ValueError("Desktop Docker daemon changed; no containers were stopped")
        if not set(ids) <= self.record["containers"].keys():
            raise ValueError("Unregistered desktop containers need inspection; nothing was stopped")
        if not ids:
            return
        observed = self.observe(ids)
        if observed != {identity: self.record["containers"][identity] for identity in ids}:
            raise ValueError("A recorded desktop container changed; nothing was stopped")
        # Exact IDs only. Never Compose down against an unverified inventory,
        # --volumes, global cleanup, native processes or model runtime containers.
        self.docker("stop", "--time", "10", *ids)
        self.docker("rm", *ids)
        if container_ids(self.inventory()):
            raise RuntimeError("Inspect remaining desktop containers before starting")

    def capture(self):
        if self.current_namespace() != self.namespace:
            raise ValueError("Desktop storage changed before recording ownership")
        ids = container_ids(self.inventory())
        if not ids:
            raise ValueError("No newly launched desktop containers to record")
        containers = self.observe(ids, created=True)
        if {item["service"] for item in containers.values()} != SERVICES:
            raise ValueError("The newly launched desktop project is incomplete")
        value = {
            "schema": 1,
            "namespace": self.namespace,
            "daemon": self.daemon(),
            "containers": containers,
        }
        if self.load() != self.record:
            raise ValueError("Desktop ownership changed before publication")
        descriptor, name = tempfile.mkstemp(prefix=".compose-owner-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(value, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path)
            parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            Path(name).unlink(missing_ok=True)
        self.record = value

    def clear(self):
        if self.load() != self.record:
            raise ValueError("Desktop ownership changed during shutdown")
        if self.record is not None:
            self.path.unlink()
            self.record = None
