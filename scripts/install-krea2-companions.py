#!/usr/bin/env python3
"""Explicit, checksum-pinned Krea companions setup; never downloads LUSTIFY.

Default: offline plan. --download creates a dedicated owned directory; interrupted
setup can be rerun without downloading verified files again. Inference never runs
this installer. No credentials, existing models or runtime settings are modified.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

MANIFEST = Path(__file__).resolve().parents[1] / "config/images/krea2-companions.json"
OWNER = ".ai-station-krea2-install.json"
RECEIPT = "ai-station-model.json"
CHUNK = 1024 * 1024


def load_manifest():
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("schema_version") != 1 or not 1 <= len(manifest.get("files", [])) <= 8:
        raise ValueError("Invalid Krea companion manifest")
    seen = set()
    for item in manifest["files"]:
        path = PurePosixPath(item["path"])
        source = PurePosixPath(item["source_path"])
        if (
            len(path.parts) != 2
            or path.parts[0] not in {"text_encoders", "vae", "loras"}
            or str(path) != item["path"]
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in str(path)
            or item["path"] in seen
            or source.is_absolute()
            or ".." in source.parts
            or str(source) != item["source_path"]
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*", str(source))
            or item["repository"] not in {"Comfy-Org/Krea-2", "conradlocke/krea2-identity-edit"}
            or not re.fullmatch(r"[a-f0-9]{40}", item["revision"])
            or type(item["size"]) is not int
            or not 0 < item["size"] < 6_000_000_000
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
        ):
            raise ValueError("Invalid pinned Krea companion")
        seen.add(item["path"])
    if sum(item["size"] for item in manifest["files"]) != manifest["total_bytes"]:
        raise ValueError("Invalid Krea companion total")
    return manifest


def checked(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    if path == Path(path.anchor) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Choose a dedicated directory without symlinks")
    return path


def plan(destination, manifest):
    return {
        "operation": "plan",
        "destination": str(checked(destination)),
        "network": False,
        "total_bytes": manifest["total_bytes"],
        "files": manifest["files"],
        "includes_lustify": False,
        "generation_verified": False,
    }


def matches(target, item):
    target = checked(target)
    if not target.is_file() or target.stat().st_size != item["size"]:
        return False
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest() == item["sha256"]


def public_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not (host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co"))
    ):
        raise ValueError("Krea download left the public model service")
    return url


def download(client, target, item):
    url = f"https://huggingface.co/{item['repository']}/resolve/{item['revision']}/{item['source_path']}"
    for _ in range(6):
        with client.stream("GET", public_url(url)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            size, digest = 0, hashlib.sha256()
            with target.open("xb") as handle:
                for block in response.iter_bytes(CHUNK):
                    size += len(block)
                    if size > item["size"]:
                        raise ValueError("Krea download exceeds pinned size")
                    digest.update(block)
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
            if size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("Krea download failed size/SHA-256 verification")
            return
    raise ValueError("Krea download redirect limit exceeded")


def verify(destination, manifest):
    destination = checked(destination)
    receipt = checked(destination / RECEIPT)
    if not receipt.is_file() or json.loads(receipt.read_text()) != manifest:
        raise ValueError("No completed Krea installation receipt")
    for item in manifest["files"]:
        if not matches(destination / item["path"], item):
            raise ValueError(f"Krea companion missing or changed: {item['path']}")
    return {"operation": "verify", "network": False, "verified_files": len(manifest["files"])}


def install(destination, manifest):
    destination = checked(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    checked(destination)
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        owner = checked(destination / OWNER)
        if not owner.is_file() or json.loads(owner.read_text()) != manifest:
            raise ValueError("Existing directory is not this owned Krea installation") from None
    else:
        with (destination / OWNER).open("x") as handle:
            json.dump(manifest, handle)
    # A single installer owns publication and interrupted partial-file cleanup.
    with checked(destination / OWNER).open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = checked(destination / RECEIPT)
        if receipt.exists():
            return verify(destination, manifest)
        missing = []
        for item in manifest["files"]:
            target = checked(destination / item["path"])
            if target.exists() and not matches(target, item):
                raise ValueError(f"Refusing to replace changed file: {item['path']}")
            if not target.exists():
                missing.append(item)
        if shutil.disk_usage(destination).free < sum(i["size"] for i in missing) + 512 * CHUNK:
            raise ValueError("Insufficient disk space for Krea companions")
        with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
            for item in missing:
                target = checked(destination / item["path"])
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                partial = checked(target.with_name(target.name + ".partial"))
                # Only uncommitted partials inside this exact manifest-owned tree.
                partial.unlink(missing_ok=True)
                print(f"Downloading {item['path']} ({item['size']} bytes)", flush=True)
                download(client, partial, item)
                os.link(partial, target)  # Exclusive publication; never replace operator bytes.
                partial.unlink()
        with receipt.open("x") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
        return verify(destination, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        action = install if args.download else verify if args.verify else plan
        print(json.dumps(action(args.destination, load_manifest()), indent=2))
    except (OSError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"Krea setup failed: {exc}\n")


if __name__ == "__main__":
    main()
