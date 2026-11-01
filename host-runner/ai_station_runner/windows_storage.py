"""Bounded native Windows volume observations for the dedicated WSL guest.

This file is also a fixed ordinary-user installer entry point. It accepts only
two decimal byte counts, never a path, command, URL or executable.
"""

import json
import math
import os
import shutil
import stat
import sys
import tempfile
import time
from collections import namedtuple
from pathlib import Path

GUEST = Path("/usr/lib/ai-station-wsl-build.json")
HOME = Path("/home/station")
ROOT = HOME / ".local/share/ai-station-desktop"
BOOT = Path("/proc/sys/kernel/random/boot_id")
MAX_AGE = 45
HEADROOM = 256 * 1024**2
Usage = namedtuple("Usage", "total used free")


def private(path, *, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or (not directory and info.st_nlink != 1)
        or path.resolve() != path
    ):
        raise ValueError("Windows capacity observations must remain private ordinary-user files")
    return info


def marker():
    info = GUEST.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("The dedicated WSL guest identity must remain immutable")


def counts(total, free):
    if type(total) is not int or type(free) is not int or not 0 <= free <= total <= 2**60 or not total:
        raise ValueError("Invalid physical Windows volume capacity")


def write(total, free):
    counts(total, free)
    marker()
    if os.getuid() < 1000 or os.getuid() != os.geteuid() or Path.home() != HOME:
        raise ValueError("Report capacity only as the dedicated ordinary guest account")
    private(HOME, directory=True)
    if ROOT.resolve() != ROOT:
        raise ValueError("Windows capacity storage cannot cross links")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(ROOT, directory=True)
    target = ROOT / "windows-volume.json"
    if target.exists() or target.is_symlink():
        private(target)
    value = {
        "schema": 1,
        "total_bytes": total,
        "free_bytes": free,
        "guest_free_bytes": shutil.disk_usage(ROOT).free,
        "observed_at": time.monotonic(),
        "boot_id": BOOT.read_text().strip(),
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".windows-volume-", dir=ROOT)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def physical(path):
    try:
        GUEST.lstat()
    except FileNotFoundError:
        return None  # Ordinary Linux installation: retain its filesystem policy.
    try:
        marker()
        private(ROOT, directory=True)
        target = ROOT / "windows-volume.json"
        info = private(target)
        if info.st_size > 4096 or os.stat(path).st_dev != ROOT.stat().st_dev:
            raise ValueError("The Windows volume observation does not cover this filesystem")
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or opened.st_mode & 0o077
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise ValueError("The Windows capacity file changed during inspection")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError("Windows capacity observation exceeds its bound")
            value = json.loads(raw)
        finally:
            os.close(descriptor)
        if (
            set(value)
            != {"schema", "total_bytes", "free_bytes", "guest_free_bytes", "observed_at", "boot_id"}
            or type(value["schema"]) is not int
            or value["schema"] != 1
        ):
            raise ValueError("Invalid Windows capacity observation")
        counts(value["total_bytes"], value["free_bytes"])
        if type(value["guest_free_bytes"]) is not int or value["guest_free_bytes"] < 0:
            raise ValueError("Invalid guest filesystem observation")
        if type(value["observed_at"]) not in {int, float} or not math.isfinite(value["observed_at"]):
            raise ValueError("Invalid Windows capacity time")
        age = time.monotonic() - value["observed_at"]
        if not 0 <= age <= MAX_AGE or value["boot_id"] != BOOT.read_text().strip():
            raise ValueError("Windows capacity observation is stale")
        growth = max(0, value["guest_free_bytes"] - shutil.disk_usage(path).free)
        return {
            "status": "ready",
            "total_bytes": value["total_bytes"],
            "free_bytes": max(0, value["free_bytes"] - growth - HEADROOM),
            "source": "windows_volume",
        }
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {"status": "unavailable", "source": "windows_volume"}


def disk_usage(path):
    usage = shutil.disk_usage(path)
    report = physical(path)
    if report is None:
        return usage
    if report["status"] != "ready":
        return Usage(usage.total, usage.total, 0)
    total = min(usage.total, report["total_bytes"])
    free = min(usage.free, report["free_bytes"], total)
    return Usage(total, total - free, free)


def main():
    if len(sys.argv) != 3 or any(
        not value.isascii() or not value.isdigit() or len(value) > 19 for value in sys.argv[1:]
    ):
        raise ValueError("Supply only physical total and available byte counts")
    write(*(int(value) for value in sys.argv[1:]))
    print('{"status":"observed"}', flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
