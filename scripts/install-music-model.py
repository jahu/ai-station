#!/usr/bin/env python3
"""Plan, explicitly download, or verify pinned local music checkpoints.

The default operation is offline and read-only. This does not install Python
packages, run model code, configure AI Station, or launch inference.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

MANIFEST = Path(__file__).resolve().parents[1] / "config/music/ace-step-1.5-turbo.json"
RECEIPT = "ai-station-model.json"
CHUNK = 1024 * 1024


def load_manifest():
    manifest = json.loads(MANIFEST.read_text())
    if (
        manifest.get("schema_version") != 1
        or manifest.get("repository") != "ACE-Step/Ace-Step1.5"
        or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("revision", ""))
        or not 1 <= len(manifest.get("files", [])) <= 32
    ):
        raise ValueError("Invalid pinned music manifest")
    seen = set()
    for item in manifest["files"]:
        path = PurePosixPath(item["path"])
        if (
            path.is_absolute()
            or ".." in path.parts
            or str(path) != item["path"]
            or "\\" in item["path"]
            or path.parts[0] not in {"acestep-v15-turbo", "Qwen3-Embedding-0.6B", "vae"}
            or len(path.parts) != 2
            or item["path"] in seen
            or type(item["size"]) is not int
            or not 0 < item["size"] < 5_000_000_000
            or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))
        ):
            raise ValueError("Invalid pinned music file")
        seen.add(item["path"])
    if sum(item["size"] for item in manifest["files"]) != manifest["total_bytes"]:
        raise ValueError("Manifest total does not match its files")
    return manifest


def checked_destination(destination):
    path = Path(os.path.abspath(destination.expanduser()))
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("Music destination must not contain symlinks")
    if path == Path(path.anchor):
        raise ValueError("Choose a new dedicated model directory")
    return path


def plan(destination, manifest):
    destination = checked_destination(destination)
    return {
        "operation": "plan",
        "network": False,
        "destination": str(destination),
        "destination_exists": destination.exists(),
        "total_bytes": manifest["total_bytes"],
        "gib": round(manifest["total_bytes"] / 1024**3, 3),
        "model_revision": manifest["revision"],
        "code_revision": manifest["code_revision"],
        "files": [
            {
                **item,
                "url": f"https://huggingface.co/{manifest['repository']}/resolve/"
                f"{manifest['revision']}/{item['path']}",
            }
            for item in manifest["files"]
        ],
        "runtime_installed": False,
        "music_generation_verified": False,
    }


def public_download_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not (host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co"))
    ):
        raise ValueError("Music download redirected outside the public model service")
    return url


def download_file(client, url, target, item):
    for _ in range(6):
        with client.stream("GET", public_download_url(url)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            size, digest = 0, hashlib.sha256()
            with target.open("xb") as handle:
                for block in response.iter_bytes(CHUNK):
                    size += len(block)
                    if size > item["size"]:
                        raise ValueError("Music download exceeds its pinned size")
                    digest.update(block)
                    handle.write(block)
            if size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("Music download failed its pinned size/SHA-256 check")
            return
    raise ValueError("Music download exceeded its redirect limit")


def verify(destination, manifest):
    destination = checked_destination(destination)
    receipt = destination / RECEIPT
    if receipt.is_symlink() or not receipt.is_file() or json.loads(receipt.read_text()) != manifest:
        raise ValueError("Music model has no matching completed installation receipt")
    for item in manifest["files"]:
        target = checked_destination(destination / item["path"])
        if not target.is_file() or target.stat().st_size != item["size"]:
            raise ValueError(f"Music file is missing or has changed: {item['path']}")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                digest.update(block)
        if digest.hexdigest() != item["sha256"]:
            raise ValueError(f"Music file failed SHA-256: {item['path']}")
    return {"operation": "verify", "verified_files": len(manifest["files"]), "network": False}


def install(destination, manifest):
    details = plan(destination, manifest)
    destination = Path(details["destination"])
    if destination.exists():
        raise ValueError("Music destination already exists; verify it or choose a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    checked_destination(destination)
    if shutil.disk_usage(destination.parent).free < manifest["total_bytes"] + 512 * 1024**2:
        raise ValueError("Not enough free disk space for the music checkpoint")
    # mkdir is the exclusive reservation: no existing directory is ever replaced
    # or removed. A failed attempt remains incomplete and cannot verify as ready.
    destination.mkdir(mode=0o700)
    with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
        for item in details["files"]:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            partial = target.with_name(target.name + ".partial")
            print(f"Downloading {item['path']} ({item['size']} bytes)", flush=True)
            download_file(client, item["url"], partial, item)
            # Exclusive publication avoids overwriting even an unexpected file
            # created while the download was running.
            os.link(partial, target)
            partial.unlink()
    with (destination / RECEIPT).open("x") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    return verify(destination, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download", action="store_true", help="Explicitly download the planned 6.34 GB")
    mode.add_argument("--verify", action="store_true", help="Offline full-file checksum verification")
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        action = install if args.download else verify if args.verify else plan
        print(json.dumps(action(args.destination, manifest), indent=2))
    except (OSError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"Music setup failed: {exc}\n")


if __name__ == "__main__":
    main()
