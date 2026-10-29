"""Repair only an existing owned API's failed Docker port publication.

Operator startup utility, never an agent tool or Host Runner shell endpoint.
No builds, pulls, database edits, Native Runner restarts or running-worker stops.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import ipaddress
import json
import os
import re
import runpy
import socket
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {"ai-station", "worker", "scheduler"}
MARKER = "# AI Station owned control-plane recovery"


class RecoveryError(ValueError):
    """Controlled operator-facing reason without command output or credentials."""


@dataclass
class Configuration:
    root: Path
    env_file: Path
    env: dict
    data: Path
    socket: Path
    project: str
    port: int
    addresses: list[str]
    files: list[Path]

    @property
    def compose(self):
        return ["docker", "compose", *[arg for path in self.files for arg in ("-f", str(path))]]


def configuration(root, env_file=None):
    root = Path(root).expanduser().resolve(strict=True)
    env_file = Path(env_file).expanduser().absolute() if env_file else root / ".env"
    env = {**{k: v for k, v in dotenv_values(env_file).items() if v is not None}, **os.environ}
    project = env.get("COMPOSE_PROJECT_NAME", "ai-station")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", project):
        raise RecoveryError("Choose a valid AI Station Compose project name")
    port = int(env.get("AI_STATION_PORT", "8765"))
    if not 1 <= port <= 65535:
        raise RecoveryError("Choose a valid UI port")
    addresses = ["127.0.0.1"]
    files = [root / "compose.yaml"]
    if env.get("AI_STATION_LAN_HOST"):
        address = ipaddress.IPv4Address(env["AI_STATION_LAN_HOST"])
        if not any(
            address in ipaddress.ip_network(n)
            for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
        ):
            raise RecoveryError("LAN recovery requires a specific private IPv4 address")
        addresses.append(str(address))
        files.append(root / "compose.lan.yaml")
    if not all(
        path.is_file() for path in [*files, root / "host-runner/ai_station_runner/source_identity.py"]
    ):
        raise RecoveryError("Choose the existing AI Station checkout")

    def location(value):
        path = Path(value).expanduser()
        return (root / path if not path.is_absolute() else path).resolve()

    data = location(env.get("AI_STATION_DATA_HOST_PATH", "data"))
    sock = location(env.get("AI_STATION_RUNNER_SOCKET", str(data / "runtime/runner/runner.sock")))
    if sock.name != "runner.sock" or not data.is_dir():
        raise RecoveryError("Recover an existing data directory and private runner.sock")
    env.update(
        COMPOSE_PROJECT_NAME=project,
        AI_STATION_DATA_HOST_PATH=str(data),
        AI_STATION_RUNNER_SOCKET_DIR=str(sock.parent),
        AI_STATION_UID=str(os.getuid()),
        AI_STATION_GID=str(os.getgid()),
    )
    return Configuration(root, env_file, env, data, sock, project, port, addresses, files)


class Recovery:
    def __init__(self, config, wait_seconds=120):
        self.config = config
        self.wait_seconds = wait_seconds

    def command(self, argv, timeout=20):
        return subprocess.check_output(
            argv,
            cwd=self.config.root,
            env=self.config.env,
            text=True,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

    def inspect(self, identifiers):
        return json.loads(self.command(["docker", "inspect", *identifiers]))

    def image_pin(self, image, *, create=False):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise RecoveryError("The existing API has no immutable image identity")
        folder = self.config.data / "runtime" / "recovery"
        if create:
            folder.mkdir(mode=0o700, exist_ok=True)
        info = folder.stat()
        if folder.resolve() != folder or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RecoveryError("Recovery image pins require a private owned directory")
        path = folder / ("recovery-image-" + image[7:] + ".json")
        expected = {"services": {"ai-station": {"image": image}}}
        if create and not path.exists():
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent) as temporary:
                json.dump(expected, temporary)
                temporary.flush()
                try:
                    os.link(temporary.name, path)
                except FileExistsError:
                    pass
        info = path.lstat()
        if (
            path.resolve() != path
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size > 4096
            or json.loads(path.read_text()) != expected
        ):
            raise RecoveryError("Inspect the unexpected recovery image pin")
        return path

    def owned(self, item):
        c = self.config
        labels = item["Config"].get("Labels") or {}
        security = item["HostConfig"]
        expected = {"/data": (c.data, True), "/runner": (c.socket.parent, False)}
        mounts = {
            m["Destination"]: (Path(m["Source"]).resolve(), m["RW"])
            for m in item.get("Mounts", [])
            if m["Type"] == "bind"
        }
        if (
            labels.get("com.docker.compose.project") != c.project
            or labels.get("com.docker.compose.service") not in SERVICES
            or labels.get("com.docker.compose.project.working_dir") != str(c.root)
            or item["Config"].get("User", "").split(":")[0] != str(os.getuid())
            or mounts != expected
            or security.get("Privileged")
            or not security.get("ReadonlyRootfs")
            or "ALL" not in (security.get("CapDrop") or [])
            or not any(
                s in {"no-new-privileges", "no-new-privileges:true"}
                for s in security.get("SecurityOpt") or []
            )
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", item.get("Image", ""))
        ):
            raise RecoveryError(
                "Existing containers do not match this owned checkout and hardened configuration"
            )
        files = ",".join(map(str, c.files))
        actual_files = labels.get("com.docker.compose.project.config_files")
        if actual_files != files:
            if labels.get("com.docker.compose.service") != "ai-station":
                raise RecoveryError("The existing service belongs to a different Compose configuration")
            pin = self.image_pin(item.get("Image", ""))
            if actual_files != files + "," + str(pin):
                raise RecoveryError("The existing API belongs to a different Compose configuration")
        return labels["com.docker.compose.service"]

    def health(self):
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(f"http://127.0.0.1:{self.config.port}/api/health")
                value = response.json()
                return response.status_code == 200 and isinstance(value, dict) and value.get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    def runner_ready(self):
        expected = runpy.run_path(str(self.config.root / "host-runner/ai_station_runner/source_identity.py"))[
            "SOURCE_FINGERPRINT"
        ]
        try:
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(self.config.socket)),
                base_url="http://runner",
                timeout=2,
                trust_env=False,
            ) as client:
                response = client.get("/health")
                value = response.json()
                return (
                    response.status_code == 200
                    and isinstance(value, dict)
                    and value.get("status") == "ok"
                    and value.get("data_dir") == str(self.config.data)
                    and value.get("source_fingerprint") == expected
                )
        except (httpx.HTTPError, ValueError, OSError):
            return False

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + self.wait_seconds
        while not predicate():
            if time.monotonic() >= deadline:
                raise RecoveryError(message)
            time.sleep(0.5)

    def addresses_ready(self):
        for address in self.config.addresses:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind((address, 0))
            except OSError as error:
                if error.errno == errno.EADDRNOTAVAIL:
                    return False
                raise
        return True

    def require_local_docker(self):
        # A selected context overrides DOCKER_HOST in the Docker CLI.
        env = self.config.env
        if env.get("DOCKER_CONTEXT") or not env.get("DOCKER_HOST"):
            endpoint = self.command(
                ["docker", "context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}']
            ).strip()
        else:
            endpoint = env["DOCKER_HOST"]
        if not endpoint.startswith("unix:///") or any(char in endpoint for char in "\n\r\0"):
            raise RecoveryError("Recovery requires a local Docker Unix endpoint")

    def repair(self):
        c = self.config
        self.require_local_docker()
        identifiers = self.command([*c.compose, "ps", "--all", "--quiet", *sorted(SERVICES)]).split()
        if not identifiers:
            return {"status": "absent", "changed": False}
        if any(not re.fullmatch(r"[a-f0-9]{12,64}", identifier) for identifier in identifiers):
            raise RecoveryError("Inspect the unexpected Compose container identities")
        items = self.inspect(identifiers)
        services = {}
        for item in items:
            service = self.owned(item)
            if service in services:
                raise RecoveryError("Inspect a scaled or ambiguous existing deployment before recovery")
            services[service] = item
        if set(services) != SERVICES:
            raise RecoveryError(
                "Inspect the incomplete owned project; recovery does not create a new deployment"
            )
        api = services["ai-station"]
        wanted = {(address, str(c.port)) for address in c.addresses}
        declared = api["HostConfig"].get("PortBindings") or {}
        if (
            set(declared) != {"8765/tcp"}
            or {(p["HostIp"], p["HostPort"]) for p in declared["8765/tcp"]} != wanted
        ):
            raise RecoveryError("Existing UI publish policy differs from this configuration")
        published = (api.get("NetworkSettings", {}).get("Ports") or {}).get("8765/tcp")
        if published:
            if {(p["HostIp"], p["HostPort"]) for p in published} != wanted:
                raise RecoveryError("Inspect the partial UI publish mapping")
            if api["State"].get("Running"):
                self.wait_for(self.health, "The existing API needs inspection; no service was restarted")
                return {"status": "healthy", "changed": False}
        error = (api["State"].get("Error") or "").lower()
        binding_failed = any(
            text in error
            for text in (
                "failed to bind host port",
                "external connectivity",
                "port is already allocated",
                "address already in use",
            )
        )
        if not api["State"].get("Running") and not binding_failed:
            return {"status": "stopped_or_requires_inspection", "changed": False}
        self.wait_for(self.addresses_ready, "The configured LAN address is not ready; no service was changed")
        self.wait_for(self.runner_ready, "The matching Host Runner is not ready; no service was changed")
        # An occupied host port belongs to its current listener. Never stop it.
        for address in c.addresses:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind((address, c.port))
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    raise RecoveryError("The UI port is occupied; no existing listener was stopped") from None
                raise
        # Pin the existing immutable image. Recovery cannot apply a newly tagged
        # image, change migrations, build, pull or restart a working GPU worker.
        pin = self.image_pin(api["Image"], create=True)
        latest = self.inspect([api["Id"]])[0]
        self.owned(latest)
        if latest["Image"] != api["Image"]:
            raise RecoveryError("The owned API changed before recovery")
        self.command(
            [
                *c.compose,
                "-f",
                str(pin),
                "up",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--detach",
                "--force-recreate",
                "ai-station",
            ],
            timeout=90,
        )
        self.wait_for(self.health, "The recreated owned API did not become healthy; inspect its logs")
        started = []
        for role in ("worker", "scheduler"):
            original = services[role]
            latest = self.inspect([original["Id"]])[0]
            self.owned(latest)
            if original["State"].get("Status") == "created" and latest["State"].get("Status") == "created":
                self.command(["docker", "start", original["Id"]])
                started.append(role)
        return {
            "status": "recovered",
            "changed": True,
            "image": api["Image"],
            "started_created_services": started,
        }

    def run(self):
        runtime = self.config.data / "runtime"
        runtime.mkdir(mode=0o700, exist_ok=True)
        if runtime.resolve() != runtime:
            raise RecoveryError("Recovery runtime must not follow a symlink")
        info = runtime.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o002:
            raise RecoveryError("Recovery runtime must be owned by you and not world-writable")
        descriptor = os.open(runtime / "launcher.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise RecoveryError("The launcher lock must be your recorded regular file")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "already_supervised", "changed": False}
            return self.repair()


def systemd_argument(value):
    if any(char in str(value) for char in "\n\r\0"):
        raise RecoveryError("Service paths must be single-line values")
    return (
        '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'
    )


def install_service(config):
    folder = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "ai-station-recovery.service"
    if target.is_symlink() or target.exists() and not target.read_text().startswith(MARKER + "\n"):
        raise RecoveryError("Refusing to replace an unrelated existing user service")
    arguments = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--checkout",
        str(config.root),
        "--env-file",
        str(config.env_file),
    ]
    content = (
        MARKER
        + "\n[Unit]\nDescription=Recover AI Station after network startup\n\n[Service]\nType=oneshot\nExecStart="
        + " ".join(map(systemd_argument, arguments))
        + "\nRestart=on-failure\nRestartSec=15\nTimeoutStartSec=600\n\n[Install]\nWantedBy=default.target\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        Path(temporary.name).replace(target)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", target.name], check=True)
    return {"status": "installed", "service": target.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--wait-seconds", type=int, metavar="1..120", default=120)
    parser.add_argument("--install-user-service", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 120:
        raise RecoveryError("Choose a wait budget between 1 and 120 seconds")
    config = configuration(args.checkout, args.env_file)
    result = (
        install_service(config) if args.install_user_service else Recovery(config, args.wait_seconds).run()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except RecoveryError as error:
        raise SystemExit("AI Station recovery needs inspection: " + str(error)) from None
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit("AI Station recovery needs inspection: " + type(error).__name__) from None
