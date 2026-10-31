"""Private desktop lifecycle control; never an application/agent host API."""

import json
import os
import re
import socket
import stat
import struct
import threading
from uuid import uuid4

CONTROL_FILE = "desktop-control.sock"


def unix_address(path):
    # Package builders only need stdlib metadata helpers. The native wheel is
    # required when a packaged desktop actually binds/connects its control socket.
    from ai_station_runner.unix_sockets import unix_address as address

    return address(path)


def private_socket(path):
    info = path.lstat()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
    ):
        raise ValueError("Desktop control must remain a private owned socket")
    return info


def same_user(connection):
    return (
        struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
        == os.geteuid()
    )


class DesktopControl:
    def __init__(self, root):
        self.path = root / CONTROL_FILE
        self.instance_id = uuid4().hex
        self.ready = threading.Event()
        self.background = threading.Event()
        self.stop_requested = threading.Event()
        self.closing = threading.Event()
        self.socket = None
        self.thread = None
        self.inode = None

    def status(self):
        return {
            "instance_id": self.instance_id,
            "ready": self.ready.is_set(),
            "background": self.background.is_set(),
            "stopping": self.stop_requested.is_set(),
        }

    def __enter__(self):
        # The caller owns desktop.lock. Only an owned stale socket may be removed.
        try:
            private_socket(self.path)
        except FileNotFoundError:
            pass
        else:
            self.path.unlink()
        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            with unix_address(self.path) as address:
                self.socket.bind(address)
            self.inode = self.path.lstat().st_ino
            self.path.chmod(0o600)
            self.socket.listen(4)
            self.socket.settimeout(0.2)
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def serve(self):
        while not self.closing.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(1)
                try:
                    if not same_user(connection):
                        continue
                    with connection.makefile("rb") as source:
                        line = source.readline(129)
                    if len(line) > 128 or not line.endswith(b"\n"):
                        continue
                    value = json.loads(line)
                    if value == {"action": "status"}:
                        response = self.status()
                    elif value == {"action": "stop", "instance_id": self.instance_id}:
                        self.stop_requested.set()
                        response = {"accepted": True, "instance_id": self.instance_id}
                    else:
                        response = {"error": "Invalid or stale desktop control request"}
                    connection.sendall(json.dumps(response).encode() + b"\n")
                except (OSError, ValueError, TypeError):
                    continue  # No request bodies, setup links or secrets enter logs.

    def close(self):
        self.closing.set()
        if self.socket is not None:
            self.socket.close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            info = self.path.lstat()
            if info.st_ino == self.inode and stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid():
                self.path.unlink()
        except FileNotFoundError:
            pass

    def __exit__(self, *args):
        self.close()


def request(root, action="status", *, instance_id=None):
    if (
        action not in {"status", "stop"}
        or action == "stop"
        and not re.fullmatch(r"[a-f0-9]{32}", instance_id or "")
    ):
        raise ValueError("Invalid desktop control action")
    path = root / CONTROL_FILE
    private_socket(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        with unix_address(path) as address:
            connection.connect(address)
        if not same_user(connection):
            raise ValueError("Desktop control belongs to another OS user")
        value = {"action": action}
        if action == "stop":
            value["instance_id"] = instance_id
        connection.sendall(json.dumps(value).encode() + b"\n")
        with connection.makefile("rb") as source:
            line = source.readline(1025)
        if len(line) > 1024 or not line.endswith(b"\n"):
            raise ValueError("Desktop control returned an incomplete response")
        response = json.loads(line)
        if not isinstance(response, dict) or "error" in response:
            raise ValueError("The desktop instance changed; reopen its controls")
        if action == "stop":
            valid = (
                set(response) == {"accepted", "instance_id"}
                and response["accepted"] is True
                and response["instance_id"] == instance_id
            )
        else:
            valid = (
                set(response) == {"instance_id", "ready", "background", "stopping"}
                and isinstance(response["instance_id"], str)
                and re.fullmatch(r"[a-f0-9]{32}", response["instance_id"])
                and all(type(response[key]) is bool for key in ("ready", "background", "stopping"))
            )
        if not valid:
            raise ValueError("Desktop control returned an invalid response")
        return response
