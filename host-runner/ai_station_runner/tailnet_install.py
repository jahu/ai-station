"""Explicit, pinned native dependency installation; never a system package operation."""

import fcntl
import hashlib
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Callable

import httpx

VERSION = "1.104.2"
ARCHIVES = {
    "amd64": "512f613ed7d04fc7282f7dc5bd76aa105aae28168fbb9357eb749ebcbc29f0ae",
    "arm64": "5776aaa901b5ef1916e66be5bb54b9f481cd399c9c28db123a8cab620efa237b",
}
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXTRACTED = 160 * 1024 * 1024


def private_directory(path: Path, *, create: bool = True) -> Path:
    path = path.expanduser().absolute()
    if ".." in path.parts or path.resolve() != path:
        raise ValueError("Private dependency directory must be canonical, without symlinks")
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Private dependency directory must be owned by this user with mode 0700")
    return path


def read_private(path: Path, *, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_mode & 0o077
            or not 0 <= before.st_size <= limit
        ):
            raise ValueError("Private file ownership, type or size changed")
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
        if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Private file changed while reading")
    return data


def verified_install(path: Path, architecture: str) -> dict:
    if architecture not in ARCHIVES:
        raise ValueError("Unsupported native architecture")
    private_directory(path, create=False)
    receipt = json.loads(read_private(path / "install.json", limit=4096))
    if receipt.get("version") != VERSION or receipt.get("archive_sha256") != ARCHIVES[architecture]:
        raise ValueError("Installed tailnet dependency has a different pinned release")
    for name in ("tailscale", "tailscaled"):
        content = read_private(path / name, limit=MAX_EXTRACTED)
        if hashlib.sha256(content).hexdigest() != receipt.get("binaries", {}).get(name):
            raise ValueError("Installed tailnet binary changed")
        if stat.S_IMODE((path / name).lstat().st_mode) != 0o700:
            raise ValueError("Installed tailnet binary permissions changed")
    return receipt


def install(
    prefix: Path,
    *,
    canceled: Callable[[], bool] = lambda: False,
    client: httpx.Client | None = None,
) -> Path:
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or architecture not in ARCHIVES:
        raise ValueError("Private tailnet dependency supports Linux x64 and ARM64")
    prefix = private_directory(prefix)
    lock_fd = os.open(prefix / "install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        info = os.fstat(lock.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("Dependency installation lock is not private")
        while True:
            if canceled():
                raise InterruptedError("Private dependency installation canceled")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        if canceled():
            raise InterruptedError("Private dependency installation canceled")
        destination = prefix / f"tailscale-{VERSION}-{architecture}"
        if destination.exists() or destination.is_symlink():
            verified_install(destination, architecture)
            return destination
        stage = Path(tempfile.mkdtemp(prefix=".install-", dir=prefix))
        own_client = client is None
        client = client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        try:
            archive = stage / "archive.tgz"
            url = f"https://pkgs.tailscale.com/stable/tailscale_{VERSION}_{architecture}.tgz"
            digest, size = hashlib.sha256(), 0
            with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                with archive.open("xb") as target:
                    for block in response.iter_bytes(1024 * 1024):
                        if canceled():
                            raise InterruptedError("Private dependency installation canceled")
                        size += len(block)
                        if size > MAX_ARCHIVE:
                            raise ValueError("Tailnet dependency archive exceeds its size limit")
                        digest.update(block)
                        target.write(block)
            if digest.hexdigest() != ARCHIVES[architecture]:
                raise ValueError("Tailnet dependency archive does not match pinned SHA-256")
            extracted = stage / "runtime"
            extracted.mkdir(mode=0o700)
            binaries = {}
            folder = f"tailscale_{VERSION}_{architecture}"
            with tarfile.open(archive, "r:gz") as bundle:
                members, extracted_size = [], 0
                for member in bundle:
                    extracted_size += member.size
                    if len(members) >= 64 or member.size < 0 or extracted_size > MAX_EXTRACTED:
                        raise ValueError("Tailnet dependency archive exceeds extraction limits")
                    members.append(member)
                for name in ("tailscale", "tailscaled"):
                    choices = [m for m in members if m.name == f"{folder}/{name}"]
                    if (
                        len(choices) != 1
                        or not choices[0].isfile()
                        or choices[0].size <= 0
                        or choices[0].mode & 0o7000
                    ):
                        raise ValueError("Tailnet dependency binary is missing, duplicated or unsafe")
                    member = choices[0]
                    source = bundle.extractfile(member)
                    if source is None:
                        raise ValueError("Tailnet dependency binary is unreadable")
                    hasher = hashlib.sha256()
                    with source, (extracted / name).open("xb") as target:
                        remaining = member.size
                        while remaining:
                            if canceled():
                                raise InterruptedError("Private dependency installation canceled")
                            block = source.read(min(remaining, 1024 * 1024))
                            if not block:
                                raise ValueError("Tailnet dependency binary is truncated")
                            remaining -= len(block)
                            hasher.update(block)
                            target.write(block)
                    (extracted / name).chmod(0o700)
                    binaries[name] = hasher.hexdigest()
            (extracted / "install.json").write_text(
                json.dumps(
                    {
                        "version": VERSION,
                        "architecture": architecture,
                        "archive_sha256": digest.hexdigest(),
                        "binaries": binaries,
                    }
                )
            )
            (extracted / "install.json").chmod(0o600)
            if canceled():
                raise InterruptedError("Private dependency installation canceled")
            extracted.rename(destination)
            verified_install(destination, architecture)
            return destination
        finally:
            if own_client:
                client.close()
            shutil.rmtree(stage)


def main():
    import argparse
    import signal
    from threading import Event

    parser = argparse.ArgumentParser(description="Install the pinned private-access runtime")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--architecture", choices=tuple(ARCHIVES), required=True)
    args = parser.parse_args()
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        if {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine()) != args.architecture:
            raise ValueError("Private runtime architecture changed")
        install(args.prefix, canceled=stopped.is_set)
    except (ValueError, OSError, httpx.HTTPError):
        raise SystemExit("Private runtime installation did not complete; inspect or retry") from None


if __name__ == "__main__":
    main()
