"""Finite native desktop update messages; no commands, paths or caller URLs."""

import json
import os
import socket
import stat
import struct
from pathlib import Path
from uuid import UUID

from ai_station_runner.station_release_metadata import update_request
from ai_station_runner.unix_sockets import unix_address

LIMIT = 8192


def command(value):
    if value == {"action": "updates.capabilities"}:
        return value.copy()
    if not isinstance(value, dict):
        raise ValueError("Invalid desktop update operation")
    action = value.get("action")
    fields = {"action", "run_id", "request"} if action == "updates.prepare" else {"action", "run_id"}
    if (
        not isinstance(action, str)
        or action not in {"updates.prepare", "updates.inspect", "updates.apply", "updates.cancel"}
        or set(value) != fields
    ):
        raise ValueError("Invalid desktop update operation")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("Use a canonical desktop update Run identity")
    return {**value, **({"request": update_request(value["request"])} if "request" in value else {})}


def request(path, value):
    value = command(value)
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Desktop update communication requires its owned canonical socket")
    info, parent = path.lstat(), path.parent.lstat()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or parent.st_mode & 0o077
    ):
        raise ValueError("Desktop update communication must remain private and user-owned")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        with unix_address(path) as address:
            connection.connect(address)
        # This channel is Linux/WSL only; it does not enable the gated Mac client.
        if (
            struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            != os.geteuid()
        ):
            raise ValueError("Desktop update communication belongs to another user")
        connection.sendall(json.dumps(value, separators=(",", ":")).encode() + b"\n")
        with connection.makefile("rb") as source:
            raw = source.readline(LIMIT + 1)
        if len(raw) > LIMIT or not raw.endswith(b"\n"):
            raise ValueError("Desktop update status exceeded its bound")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("The desktop update status is invalid")
        if "error" in result:
            raise ValueError(str(result["error"])[:300])
        if "run_id" in value and result.get("run_id") != value["run_id"]:
            raise ValueError("The desktop update status belongs to another Run")
        return result
