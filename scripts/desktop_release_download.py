"""Official desktop packages only; native-owned quarantine, never an arbitrary downloader."""

import hashlib
import os
import shutil
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from ai_station_runner.station_release_metadata import API, admit_release, positive_id, update_package
from desktop_versions import canonical, directory

METADATA_LIMIT = 1024 * 1024


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "api.github.com",
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("The official update package redirected to an unexpected source")
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None:
            result.headers.pop("Authorization", None)
        return result


def open_official(url, *, binary=False):
    # Callers construct the exact official API coordinate. Ignore proxy settings
    # and netrc; neither workstation credentials nor application secrets travel.
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "User-Agent": "AI-Station-Desktop-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        ReleaseRedirect(),
    )
    try:
        return opener.open(request, timeout=15)
    except urllib.error.URLError:
        # Signed CDN URLs are not error/log material.
        raise RuntimeError(
            "Could not reach the official update service. Your station was not changed."
        ) from None


def official_release(identity, check=lambda: None):
    import json

    positive_id(identity)
    check()
    with open_official(f"{API}/releases/{identity}") as response:
        if response.status != 200 or response.geturl() != f"{API}/releases/{identity}":
            raise ValueError("The official release identity changed")
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise ValueError("The release metadata encoding is unsupported")
        body = bytearray()
        started = time.monotonic()
        while chunk := response.read1(65536):
            check()
            if len(body) + len(chunk) > METADATA_LIMIT or time.monotonic() - started > 60:
                raise ValueError("The official release metadata exceeded its size or time bound")
            body.extend(chunk)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate release metadata fields")
            result[key] = value
        return result

    snapshot = admit_release(json.loads(body, object_pairs_hook=unique))
    if snapshot["release_id"] != identity:
        raise ValueError("The official release identity changed")
    check()
    return snapshot


def digest(path, check):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o022
    ):
        raise ValueError("The update package must remain an owned regular file")
    value, count = hashlib.sha256(), 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("The update package changed during verification")
        while chunk := source.read(1024 * 1024):
            check()
            count += len(chunk)
            value.update(chunk)
        after = os.fstat(source.fileno())
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            raise ValueError("The update package changed during verification")
    return count, value.hexdigest()


def download(
    root, release_id, fingerprint, current, platform, *, check=lambda: None, progress=lambda done, total: None
):
    """Re-observe the frozen release before any package transfer or native Stop."""
    canonical(root)
    directory(root)
    snapshot = official_release(release_id, check)
    if snapshot["fingerprint"] != fingerprint:
        raise ValueError("The update changed since it was offered. Check for updates again.")
    package = update_package(snapshot, current, platform)
    folder = root / "update-downloads"
    folder.mkdir(mode=0o700, exist_ok=True)
    info = directory(folder)
    if info.st_mode & 0o077:
        raise ValueError("Update downloads require a private owned directory")
    destination = folder / package["name"]
    expected = (package["size_bytes"], package["sha256"])
    if destination.exists() or destination.is_symlink():
        if digest(destination, check) != expected:
            raise ValueError("The saved update package changed. Inspect it before retrying.")
        progress(expected[0], expected[0])
        return destination, snapshot
    if shutil.disk_usage(folder).free < package["size_bytes"] * 3 + 512 * 1024**2:
        raise ValueError("Not enough free space to download and prepare this update")
    temporary = folder / ("." + uuid4().hex + ".part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    started, count, value = time.monotonic(), 0, hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as target:
            # A unique query avoids an intermediary's cached JSON metadata reply
            # to the same asset API path's different Accept representation.
            url = f"{API}/releases/assets/{package['id']}?ai_station_download={uuid4().hex}"
            with open_official(url, binary=True) as response:
                if (
                    response.status != 200
                    or response.headers.get("Content-Encoding", "identity") != "identity"
                ):
                    raise ValueError("The official update transfer was not a complete package")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) != expected[0]):
                    raise ValueError("The official update package size changed")
                while chunk := response.read1(128 * 1024):
                    check()
                    if time.monotonic() - started > 1800:
                        raise TimeoutError("The update download exceeded its time limit")
                    count += len(chunk)
                    if count > expected[0]:
                        raise ValueError("The official update package exceeded its expected size")
                    value.update(chunk)
                    target.write(chunk)
                    progress(count, expected[0])
            target.flush()
            os.fsync(target.fileno())
        check()
        if (count, value.hexdigest()) != expected:
            raise ValueError("The official update package failed its size or SHA256 check")
        temporary.chmod(0o400)
        os.link(temporary, destination)  # An existing verified file is never overwritten.
        from desktop_upgrade_image import sync

        sync(folder)
        return destination, snapshot
    finally:
        temporary.unlink(missing_ok=True)
