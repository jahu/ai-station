"""Developer-only private bridge experiment, not Mac installer qualification."""

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from desktop_control import same_user
from macos_desktop_docker import connection

IMAGE = "docker.io/library/python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9"
IMAGE_IDS = {
    "amd64": "sha256:9e87977b867847e186d066f531ef783b006d582a985c341c269446088d90f2c4",
    "arm64": "sha256:8630ab77c5adf06e1f914483db4dd70e3fa59118160daab9b0ee75e685344221",
}
MANIFESTS = {
    "amd64": "sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b",
    "arm64": "sha256:950206c37262dd86c55659797f6ee418fee30535072f65a82ed470d985f5cda5",
}
ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
MEMORY = 128 * 1024**2
INFO = '{"os":{{json .OSType}},"arch":{{json .Architecture}},"system":{{json .OperatingSystem}}}'
INSPECT = (
    '{"id":{{json .Id}},"image":{{json .Image}},'
    '"label":{{json (index .Config.Labels "ai-station.probe")}},'
    '"user":{{json .Config.User}},"running":{{json .State.Running}},'
    '"network":{{json .HostConfig.NetworkMode}},"readonly":{{json .HostConfig.ReadonlyRootfs}},'
    '"memory":{{json .HostConfig.Memory}},"swap":{{json .HostConfig.MemorySwap}},'
    '"privileged":{{json .HostConfig.Privileged}}}'
)

# Fixed code in a fixed publisher image, with only disposable probe paths/data.
CLIENT = r"""
import json,os,re,socket,sqlite3,sys
from pathlib import Path
os.umask(0o077)
channel,root,config=map(Path,sys.argv[1:])
cfg=json.loads(config.read_text())
nonce=cfg['nonce'];stored=cfg['stored'];phase=cfg['phase']
def require(condition):
 if not condition:raise ValueError('Fixed probe client verification failed')
require(phase in {'write','read'} and all(re.fullmatch('[a-f0-9]{64}',v) for v in (nonce,stored)))
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(15);s.connect(str(channel));reader=s.makefile('rb')
 def send(stage):s.sendall(json.dumps({'nonce':nonce,'stage':stage}).encode()+b'\n')
 def receive(stage):
  line=reader.readline(257)
  require(len(line)<=256 and line.endswith(b'\n'))
  require(json.loads(line)=={'nonce':nonce,'stage':stage})
 send('connected');receive('files')
 if phase=='write':
  with (root/'artifact.bin').open('xb') as f:f.write(bytes.fromhex(stored))
  c=sqlite3.connect(root/'probe.sqlite')
  require(c.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal')
  c.execute('CREATE TABLE probe(value TEXT NOT NULL)');c.commit()
  c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO probe VALUES (?)',(stored,))
  send('transaction-held');receive('commit');c.commit();c.close()
 else:
  require((root/'artifact.bin').read_bytes()==bytes.fromhex(stored))
  c=sqlite3.connect((root/'probe.sqlite').as_uri()+'?mode=rw',uri=True)
  try:
   require(c.execute('SELECT value FROM probe').fetchall()==[(stored,)])
  finally:c.close()
 send('committed');receive('finished');reader.close()
"""


def command(argv, *, env=None, timeout=30, check=True):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        child = subprocess.Popen(
            argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, env=env, start_new_session=True
        )
        try:
            child.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=2)
            raise
        stdout.seek(0)
        data = stdout.read(1024**2 + 1)
        if len(data) > 1024**2:
            raise ValueError("Probe command output exceeded its bound")
        if check and child.returncode:
            # No ambient context, authentication/config content or command body in errors.
            raise RuntimeError("A fixed probe Docker operation failed; inspect the local prerequisite")
        return child.returncode, data.decode().strip()


def bind_mount(path, target, *, readonly=False):
    buffer = io.StringIO()
    fields = ["type=bind", f"source={path}", f"target={target}"]
    if readonly:
        fields.append("readonly")
    csv.writer(buffer).writerow(fields)
    return buffer.getvalue().removesuffix("\r\n")


class Docker:
    def __init__(self, binary, endpoint, root, architecture):
        self.architecture = architecture
        client = root / "client"
        client.mkdir(mode=0o700)
        (client / "config.json").write_text("{}")
        (client / "config.json").chmod(0o600)
        self.argv = [binary, "--host", endpoint, "--config", str(client)]
        self.env = {"PATH": str(Path(binary).parent) + os.pathsep + os.defpath, "LANG": "C"}
        self.identity = uuid4().hex
        self.ids = []
        self.reserved_names = []
        self.uncertain = False
        self.image_id = None

    def accepted_images(self):
        # Classic stores identify a config; containerd may identify the index
        # or selected manifest. Every accepted value belongs to this fixed
        # publisher index and architecture, not an arbitrary cached image.
        return {IMAGE.split("@", 1)[1], MANIFESTS[self.architecture], IMAGE_IDS[self.architecture]}

    def call(self, *args, **kwargs):
        return command([*self.argv, *args], env=self.env, **kwargs)

    def image(self, *, prepare=False):
        code, raw = self.call("image", "inspect", IMAGE, check=False)
        if code:
            if not prepare:
                raise RuntimeError("Prepare the fixed fixture image with --prepare-image first")
            self.call("image", "pull", "--platform", "linux/" + self.architecture, IMAGE, timeout=600)
            _, raw = self.call("image", "inspect", IMAGE)
        values = json.loads(raw)
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise ValueError("Unexpected fixture image inventory")
        value = values[0]
        if (
            not isinstance(value.get("Id"), str)
            or value.get("Id") not in self.accepted_images()
            or value.get("Os") != "linux"
            or value.get("Architecture") != self.architecture
        ):
            raise ValueError("The cached fixture image is not the reviewed native architecture")
        self.image_id = value["Id"]
        return self.image_id

    def container(self, sockets, data, phase):
        if self.image_id is None:
            raise ValueError("Verify the fixed fixture image before creating a client")
        name = "ai-station-mac-probe-" + self.identity + "-" + phase
        self.reserved_names.append(name)  # Never repeat an uncertain create.
        try:
            _, identifier = self.call(
                "container",
                "create",
                "--name",
                name,
                "--label",
                "ai-station.probe=" + self.identity,
                "--platform",
                "linux/" + self.architecture,
                "--pull",
                "never",
                "--user",
                f"{os.geteuid()}:{os.getegid()}",
                "--network",
                "none",
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
                "16",
                "--cpus",
                "0.5",
                "--mount",
                bind_mount(sockets, "/probe-socket", readonly=True),
                "--mount",
                bind_mount(data, "/probe-data"),
                "--entrypoint",
                "python3",
                IMAGE,
                "-IBS",
                "-c",
                CLIENT,
                "/probe-socket/channel.sock",
                "/probe-data",
                "/probe-socket/token.json",
            )
            if re.fullmatch("[a-f0-9]{64}", identifier) is None:
                raise ValueError("The probe did not confirm its exact container identity")
        except BaseException:
            self.uncertain = True
            raise
        self.ids.append(identifier)
        self.owned(identifier)
        self.call("container", "start", identifier)
        return identifier

    def owned(self, identifier):
        _, raw = self.call("container", "inspect", "--format", INSPECT, identifier)
        value = json.loads(raw)
        if not isinstance(value, dict) or (
            value.get("id") != identifier
            or value.get("label") != self.identity
            or not isinstance(value.get("image"), str)
            or value.get("image") not in self.accepted_images()
            or value.get("user") != f"{os.geteuid()}:{os.getegid()}"
            or type(value.get("running")) is not bool
            or value.get("network") != "none"
            or value.get("readonly") is not True
            or value.get("privileged") is not False
            or value.get("memory") != MEMORY
            or value.get("swap") != MEMORY
        ):
            raise ValueError("Probe container ownership changed; nothing was signaled")
        return value

    def cleanup(self):
        complete = not self.uncertain
        for identifier in reversed(self.ids):
            try:
                if self.owned(identifier)["running"]:
                    self.call("container", "stop", "--time", "2", identifier)
                self.call("container", "rm", identifier)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                complete = False
        return complete


def packet(connection, reader, nonce, expected):
    raw = reader.readline(257)
    if len(raw) > 256 or not raw.endswith(b"\n"):
        raise ValueError("Incomplete or oversized probe packet")
    if json.loads(raw) != {"nonce": nonce, "stage": expected}:
        raise ValueError("Unexpected probe packet")


def send(connection, nonce, stage):
    connection.sendall(json.dumps({"nonce": nonce, "stage": stage}).encode() + b"\n")


def private_file(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
    ):
        raise ValueError("Probe files must remain private regular files owned by the native user")


def file_checks(data, stored, *, locked):
    private_file(data / "artifact.bin")
    private_file(data / "probe.sqlite")
    if (data / "artifact.bin").read_bytes() != bytes.fromhex(stored):
        raise ValueError("Artifact bytes changed across the host/container mount")
    with closing(sqlite3.connect((data / "probe.sqlite").as_uri() + "?mode=rw", uri=True, timeout=0.1)) as db:
        if db.execute("PRAGMA journal_mode").fetchone() != ("wal",):
            raise ValueError("The shared database is not in WAL mode")
        if db.execute("SELECT value FROM probe").fetchall() != ([] if locked else [(stored,)]):
            raise ValueError("Native/container transaction visibility differs")
        if locked:
            try:
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY:
                    raise
            else:
                db.rollback()
                raise ValueError("Native/container SQLite writes were not locked")
        else:
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("The shared database failed integrity inspection")


def experiment(docker, root, *, data_root=None):
    sockets = root / "sockets"
    sockets.mkdir(mode=0o700)
    data = (data_root or root) / ("long Application Support path " * 4) / "data"
    data.mkdir(mode=0o700, parents=True)
    stored = secrets.token_hex(32)
    channel = sockets / "channel.sock"
    if len(os.fsencode(channel)) >= 104:
        raise ValueError("Use a shorter private probe directory")
    for phase in ("write", "read"):
        nonce = stored if phase == "write" else secrets.token_hex(32)
        token = sockets / "token.json"
        token.write_text(json.dumps({"nonce": nonce, "stored": stored, "phase": phase}))
        token.chmod(0o600)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(channel))
            inode = channel.lstat().st_ino
            channel.chmod(0o600)
            listener.listen(1)
            listener.settimeout(30)
            identifier = docker.container(sockets, data, phase)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(15)
                if not same_user(connection):
                    raise ValueError("The bridge did not preserve the native peer user")
                with connection.makefile("rb") as reader:
                    packet(connection, reader, nonce, "connected")
                    send(connection, nonce, "files")
                    if phase == "write":
                        packet(connection, reader, nonce, "transaction-held")
                        file_checks(data, stored, locked=True)
                        send(connection, nonce, "commit")
                    packet(connection, reader, nonce, "committed")
                    file_checks(data, stored, locked=False)
                    send(connection, nonce, "finished")
            _, result = docker.call("container", "wait", identifier, timeout=30)
            if result != "0":
                raise ValueError("The fixed probe client failed")
        info = channel.lstat()
        if info.st_ino != inode or not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("Probe socket identity changed; replacement was preserved")
        channel.unlink()
    return {
        "native_peer_uid": os.geteuid(),
        "socket_rebind": True,
        "client_restart": True,
        "long_path_artifact_sha256": hashlib.sha256(bytes.fromhex(stored)).hexdigest(),
        "sqlite_wal": True,
        "concurrent_writer_lock": True,
        "chosen_data_filesystem": data_root is not None,
        "data_filesystem_device": data.stat().st_dev,
    }


def receipt(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as target:
        json.dump(value, target, indent=2)
        target.flush()
        os.fsync(target.fileno())


def data_parent(path):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise ValueError("Choose a canonical application data folder without symlink traversal")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("Choose an owned application data folder without shared write access")
    return path


def removable(path, original):
    if original is None:
        return False
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return (
        (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)
        and current.st_uid == os.geteuid()
        and stat.S_ISDIR(current.st_mode)
        and not current.st_mode & 0o077
    )


def probe(output, *, prepare_image=False, data_directory=None):
    if platform.system() != "Darwin" or os.geteuid() == 0:
        raise ValueError("This qualification requires a native, ordinary-user Mac")
    architecture = ARCHITECTURES.get(platform.machine().lower())
    if architecture not in IMAGE_IDS:
        raise ValueError("This Mac architecture has no reviewed fixture")
    selected = data_parent(data_directory) if data_directory is not None else None
    binary, endpoint = connection(command)
    output = Path(output).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("The proof directory must not traverse symlinks")
    parent = output.parent.stat()
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise ValueError("Choose an owned proof parent without shared write access")
    output.mkdir(mode=0o700)  # Fresh, never overwrite or replay a prior proof.
    root = Path(tempfile.mkdtemp(prefix="ast-probe-", dir=str(Path("/tmp").resolve())))
    original = root.lstat()
    data_root = None
    data_original = None
    docker = None
    result = {
        "platform": platform.system(),
        "architecture": architecture,
        "macos_installer_qualified": False,
        "other_os_user_tested": False,
        "image": IMAGE,
        "chosen_data_directory": str(selected) if selected else None,
    }
    try:
        if selected is not None:
            data_root = Path(tempfile.mkdtemp(prefix=".ast-filesystem-", dir=selected))
            data_original = data_root.lstat()
        docker = Docker(binary, endpoint, root, architecture)
        result["probe_id"] = docker.identity
        receipt(
            output / "pending.json",
            {
                **result,
                "root": str(root),
                "data_root": str(data_root) if data_root else None,
                "native_uid": os.geteuid(),
                "reserved_names": [
                    "ai-station-mac-probe-" + docker.identity + "-" + phase for phase in ("write", "read")
                ],
            },
        )
        _, info = docker.call("info", "--format", INFO)
        info = json.loads(info)
        if not isinstance(info, dict) or (
            info.get("system") != "Docker Desktop"
            or info.get("os") != "linux"
            or not isinstance(info.get("arch"), str)
            or ARCHITECTURES.get(info.get("arch")) != architecture
        ):
            raise ValueError("The selected engine is not native-architecture Docker Desktop")
        result["image_id"] = docker.image(prepare=prepare_image)
        result["checks"] = (
            experiment(docker, root, data_root=data_root) if data_root else experiment(docker, root)
        )
        result["transport_passed"] = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        result.update(transport_passed=False, error_type=type(exc).__name__, error=str(exc)[:500])
    finally:
        result["cleanup_complete"] = docker.cleanup() if docker else True
        result["reserved_names"] = docker.reserved_names if docker else []
        result["container_ids"] = docker.ids if docker else []
        directories = [(root, original)]
        if data_root is not None:
            directories.append((data_root, data_original))
        if result["cleanup_complete"] and all(removable(path, info) for path, info in directories):
            try:
                for path, _ in reversed(directories):
                    shutil.rmtree(path)
            except OSError:
                result["cleanup_complete"] = False
        else:
            result["cleanup_complete"] = False
        if not result["cleanup_complete"]:
            result["retained_root"] = str(root)
            result["retained_data_root"] = str(data_root) if data_root else None
        result["transport_passed"] = result.get("transport_passed", False) and result["cleanup_complete"]
        receipt(output / "result.json", result)
        if result["cleanup_complete"]:
            (output / "pending.json").unlink(missing_ok=True)
    return result


if __name__ == "__main__":

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="A fresh private proof directory")
    parser.add_argument(
        "--data-directory",
        type=Path,
        help="Existing chosen app data folder; only a new disposable child is tested",
    )
    parser.add_argument(
        "--prepare-image",
        action="store_true",
        help="Download only the fixed reviewed fixture image if absent",
    )
    args = parser.parse_args()
    outcome = probe(args.output, prepare_image=args.prepare_image, data_directory=args.data_directory)
    print(json.dumps(outcome, indent=2))
    raise SystemExit(0 if outcome["transport_passed"] else 1)
