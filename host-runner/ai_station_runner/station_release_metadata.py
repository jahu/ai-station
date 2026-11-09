"""Pure official-release admission, shared by the app and native update owner."""

import hashlib
import json
import re
from datetime import datetime

REPOSITORY = "jahu/ai-station"
API = f"https://api.github.com/repos/{REPOSITORY}"
WEB = f"https://github.com/{REPOSITORY}"
MAX_PACKAGE_BYTES = 4 * 1024**3
PACKAGES = {"linux-amd64": "linux-amd64.deb", "windows-x64": "windows-x64-Setup.exe"}


def update_request(value):
    if not isinstance(value, dict) or set(value) != {
        "release_id",
        "fingerprint",
        "current_version",
        "platform",
    }:
        raise ValueError("The desktop update request has invalid coordinates")
    positive_id(value["release_id"])
    version_number(value["current_version"])
    if (
        not isinstance(value["platform"], str)
        or value["platform"] not in PACKAGES
        or not isinstance(value["fingerprint"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["fingerprint"])
    ):
        raise ValueError("The desktop update request has invalid coordinates")
    return value.copy()


def version_number(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})", value
    ):
        raise ValueError("Updates require a stable numeric application version")
    parts = tuple(map(int, value.split(".")))
    if any(part > 65535 for part in parts):
        raise ValueError("The update version exceeds the supported numeric bound")
    return parts


def positive_id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("The official release identity is invalid")
    return value


def asset_identity(raw, version, platform):
    if not isinstance(raw, dict):
        raise ValueError("Invalid official update package")
    identity = positive_id(raw.get("id"))
    name = f"AI-Station-{version}-{PACKAGES[platform]}"
    size = raw.get("size")
    digest = raw.get("digest")
    if (
        raw.get("name") != name
        or raw.get("state") != "uploaded"
        or type(size) is not int
        or not 0 < size <= MAX_PACKAGE_BYTES
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
        or raw.get("url") != f"{API}/releases/assets/{identity}"
        or raw.get("browser_download_url") != f"{WEB}/releases/download/v{version}/{name}"
    ):
        raise ValueError("The official package needs an exact identity, size and SHA256 digest")
    return {"id": identity, "name": name, "size_bytes": size, "sha256": digest[7:]}


def admit_release(raw):
    """Publisher descriptions never supply commands, destinations or update URLs."""
    if not isinstance(raw, dict):
        raise ValueError("The official release response is invalid")
    identity = positive_id(raw.get("id"))
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("The official release needs a stable version tag")
    version = tag[1:]
    version_number(version)
    if raw.get("draft") is not False or raw.get("prerelease") is not False:
        raise ValueError("Only published stable releases can be installed")
    if raw.get("html_url") != f"{WEB}/releases/tag/{tag}":
        raise ValueError("The release does not belong to the official repository")
    published = raw.get("published_at")
    if not isinstance(published, str):
        raise ValueError("The release has no publication time")
    try:
        stamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Missing release timezone")
    except ValueError as exc:
        raise ValueError("The release publication time is invalid") from exc
    assets = raw.get("assets")
    if not isinstance(assets, list) or len(assets) > 32:
        raise ValueError("The release package list exceeds its bound")
    selected = {}
    for platform, suffix in PACKAGES.items():
        name = f"AI-Station-{version}-{suffix}"
        matches = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
        if len(matches) > 1:
            raise ValueError("The official release has ambiguous update packages")
        if matches:
            selected[platform] = asset_identity(matches[0], version, platform)
    if not selected:
        raise ValueError("The release contains no supported desktop update package")
    binding = {"release_id": identity, "version": version, "packages": selected}
    fingerprint = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    notes = raw.get("body")
    return {
        **binding,
        "fingerprint": fingerprint,
        "release_url": f"{WEB}/releases/tag/{tag}",
        "published_at": stamp.isoformat(),
        "notes": notes[:20000] if isinstance(notes, str) else "",
    }


def update_package(snapshot, current, platform):
    """A frozen offer never admits a same-version install or a downgrade."""
    if platform not in PACKAGES:
        raise ValueError("This installation has no supported desktop update target")
    if version_number(snapshot["version"]) <= version_number(current):
        raise ValueError("This update is not newer than the running application")
    package = snapshot["packages"].get(platform)
    if package is None:
        raise ValueError("The release has no update package for this platform")
    return package.copy()
