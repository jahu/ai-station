"""Fixed installer-only empty-volume ownership action and read-only attestation."""

import argparse
import json
import os
import re
import stat
from pathlib import Path

ROOT = Path("/database")
MARKER = ".ai-station-database-owner.json"


def binding(storage_id, namespace_sha256, uid, gid):
    if (
        not isinstance(storage_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", storage_id)
        or not isinstance(namespace_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", namespace_sha256)
        or any(type(v) is not int or not 0 < v < 2**31 for v in (uid, gid))
    ):
        raise ValueError("Invalid fixed database ownership coordinates")
    return {
        "schema": 1,
        "storage_id": storage_id,
        "namespace_sha256": namespace_sha256,
        "uid": uid,
        "gid": gid,
    }


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def directory():
    return os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def owned_directory(fd, value):
    info = os.fstat(fd)
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (value["uid"], value["gid"], 0o700):
        raise ValueError("Database directory ownership changed")


def inspect(value):
    if (os.geteuid(), os.getegid()) != (value["uid"], value["gid"]):
        raise ValueError("Database inspection must use the configured ordinary user")
    fd = directory()
    try:
        owned_directory(fd, value)
        marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        with os.fdopen(marker, "rb") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or (info.st_uid, info.st_gid, info.st_nlink, stat.S_IMODE(info.st_mode)) != (0, 0, 1, 0o444)
                or source.read(1025) != encoded(value)
            ):
                raise ValueError("Database ownership marker changed")
        return value
    finally:
        os.close(fd)


def initialize(value):
    if os.geteuid() != 0:
        raise ValueError("Only the isolated empty-volume initializer may set ownership")
    fd = directory()
    try:
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid) != (0, 0) or os.listdir(fd):
            raise ValueError(
                "Initialization requires a new empty root-owned volume; existing bytes preserved"
            )
        marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=fd)
        with os.fdopen(marker, "wb") as target:
            target.write(encoded(value))
            target.flush()
            os.fchmod(target.fileno(), 0o444)
            os.fsync(target.fileno())
        os.fsync(fd)
        os.fchmod(fd, 0o700)
        # Publish writable ownership only after the complete marker is durable.
        # The initializer has CHOWN alone, no DAC override and no host mounts.
        os.fchown(fd, value["uid"], value["gid"])
        os.fsync(fd)
        owned_directory(fd, value)
        return value
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "inspect"))
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--gid", required=True, type=int)
    args = parser.parse_args()
    value = binding(args.storage_id, args.namespace, args.uid, args.gid)
    result = {"initialize": initialize, "inspect": inspect}[args.action](value)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
