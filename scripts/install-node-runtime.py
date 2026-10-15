#!/usr/bin/env python3
"""Explicit project-local Node 22 installation from official checksum-pinned files."""

import argparse
import hashlib
import json
import platform
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

ORIGIN = "https://nodejs.org/dist/latest-v22.x/"
MAX_ARCHIVE = 64 * 1024 * 1024


def install(prefix: Path):
    machine = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or machine is None:
        raise RuntimeError(
            "This installer supports Linux x64/arm64; configure an existing Node runtime otherwise"
        )
    prefix = prefix.expanduser().resolve()
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
        response = client.get(ORIGIN + "SHASUMS256.txt")
        response.raise_for_status()
        if len(response.content) > 100000:
            raise RuntimeError("Node checksum manifest exceeds its limit")
        choices = re.findall(
            rf"^([a-f0-9]{{64}})\s+(node-v22\.\d+\.\d+-linux-{machine}\.tar\.xz)$", response.text, re.M
        )
        if len(choices) != 1:
            raise RuntimeError("Official Node manifest has no unambiguous supported archive")
        digest, filename = choices[0]
        folder = filename.removesuffix(".tar.xz")
        destination = prefix / folder
        if destination.exists() or destination.is_symlink():
            receipt = destination / "ai-station-install.json"
            if not destination.is_symlink() and receipt.is_file():
                metadata = json.loads(receipt.read_text())
                if metadata.get("archive_sha256") == digest and hashlib.sha256(
                    (destination / "bin/node").read_bytes()
                ).hexdigest() == metadata.get("node_sha256"):
                    return destination
            raise RuntimeError("Node destination already exists; inspect it rather than overwrite")
        stage = Path(tempfile.mkdtemp(prefix=".install-", dir=prefix))
        try:
            archive = stage / filename
            hasher = hashlib.sha256()
            total = 0
            with client.stream("GET", ORIGIN + filename) as download:
                download.raise_for_status()
                with archive.open("xb") as handle:
                    for block in download.iter_bytes(1024 * 1024):
                        total += len(block)
                        if total > MAX_ARCHIVE:
                            raise RuntimeError("Node archive exceeds its download limit")
                        hasher.update(block)
                        handle.write(block)
            if hasher.hexdigest() != digest:
                raise RuntimeError("Downloaded Node archive does not match the official SHA-256")
            with tarfile.open(archive, "r:xz") as bundle:
                members = bundle.getmembers()
                if len(members) > 20000 or sum(m.size for m in members) > 300 * 1024 * 1024:
                    raise RuntimeError("Node archive exceeds extraction limits")
                if any(Path(m.name).parts[0] != folder for m in members if Path(m.name).parts):
                    raise RuntimeError("Node archive contains an unexpected top-level path")
                bundle.extractall(stage, filter="data")
            extracted = stage / folder
            node, npm = extracted / "bin/node", extracted / "lib/node_modules/npm/bin/npm-cli.js"
            if not node.is_file() or not npm.is_file():
                raise RuntimeError("Node archive does not contain the required runtime")
            receipt = extracted / "ai-station-install.json"
            receipt.write_text(
                json.dumps(
                    {
                        "source": ORIGIN + filename,
                        "archive_sha256": digest,
                        "node_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
                    },
                    indent=2,
                )
            )
            receipt.chmod(0o600)
            extracted.rename(destination)
        finally:
            shutil.rmtree(stage)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix", type=Path, default=Path(__file__).resolve().parents[1] / ".tools/node-runtimes"
    )
    arguments = parser.parse_args()
    print("AI_STATION_NODE_PREFIX=" + str(install(arguments.prefix)))
