"""Build a fixed offline NVIDIA toolkit input bundle; never install or configure it."""

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.request
from pathlib import Path

REPOSITORY = "https://nvidia.github.io/libnvidia-container/stable/deb/amd64/"
RECIPE = "nvidia-container-toolkit-1.20.1-amd64-v1"
VERSION = "1.20.1-1"
SIGNING_KEY = "C95B321B61E88C1809C4F759DDCAE044F796ECB0"
INDEX_SHA512 = "6ed6287c6bc0cd60a425bd37ffd413f36a0dc11865382f586960cdaecc2a12524bd193450812f72ae50bd4d2a24ed3a8c661c734e7736c4230acb9bd96f1b73f"
PACKAGES = (
    ("libnvidia-container1", 1236052, "9d803cd9c898cb2fa927529d5ac4fc09f3d65c8cfbde8985de1b9398e53a4656"),
    ("libnvidia-container-tools", 20804, "8bd131b8977a3db667982024850ae7b50cfa02d6b2be06a718064ec814778f05"),
    (
        "nvidia-container-toolkit-base",
        5993348,
        "e01964a064fbdb62425ab22ec5832349f92c5b0b50c8f23fdf14dad004db4fb2",
    ),
    ("nvidia-container-toolkit", 1501496, "a95c9d206a7ecd6a90adff9290635271fa167a86b5767b17eaa0478a552eb02c"),
)


def metadata():
    return {
        "schema": 1,
        "recipe": RECIPE,
        "repository": REPOSITORY,
        "signing_key": SIGNING_KEY,
        "signed_index_sha512": INDEX_SHA512,
        "packages": [
            {
                "name": name,
                "version": VERSION,
                "architecture": "amd64",
                "filename": f"{name}_{VERSION}_amd64.deb",
                "size_bytes": size,
                "sha256": digest,
            }
            for name, size, digest in PACKAGES
        ],
    }


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o022:
        raise ValueError("Toolkit inputs must be regular, single-link files without shared write access")
    return info


def verify(root):
    root = Path(root).absolute()
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
        raise ValueError("Use a direct, non-shared-writable toolkit input directory")
    if root.resolve() != root:
        raise ValueError("Toolkit input paths must not traverse symlinks")
    expected = metadata()
    names = {"bundle.json", *(p["filename"] for p in expected["packages"])}
    if {p.name for p in root.iterdir()} != names:
        raise ValueError("The fixed toolkit input bundle is incomplete or contains unexpected files")
    receipt = root / "bundle.json"
    if regular(receipt).st_size > 16384 or json.loads(receipt.read_bytes()) != expected:
        raise ValueError("The toolkit input receipt differs from its fixed reviewed recipe")
    for package in expected["packages"]:
        path = root / package["filename"]
        if regular(path).st_size != package["size_bytes"]:
            raise ValueError("The toolkit input package has an unexpected length")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024**2):
                digest.update(block)
        if digest.hexdigest() != package["sha256"]:
            raise ValueError("The toolkit input package differs from its reviewed publisher hash")
    return expected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("The fixed toolkit publisher source redirected; review its source explicitly")


def prepare(output, *, cache=None):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a fresh toolkit bundle destination; existing inputs are preserved")
    if cache is not None:
        cache = Path(cache).absolute()
        verify(cache)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.resolve() != output.parent:
        raise ValueError("Toolkit output paths must not traverse symlinks")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with tempfile.TemporaryDirectory(prefix=".windows-gpu-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir(mode=0o700)
        for package in metadata()["packages"]:
            path = stage / package["filename"]
            if cache is not None:
                shutil.copyfile(cache / path.name, path)
            else:
                with opener.open(REPOSITORY + path.name, timeout=30) as source, path.open("xb") as target:
                    remaining = package["size_bytes"]
                    while block := source.read(min(1024**2, remaining + 1)):
                        if len(block) > remaining:
                            raise ValueError("The toolkit package exceeded its reviewed length")
                        target.write(block)
                        remaining -= len(block)
                    if remaining:
                        raise ValueError("The toolkit package transfer was incomplete")
            path.chmod(0o644)
        receipt = stage / "bundle.json"
        receipt.write_text(json.dumps(metadata(), sort_keys=True, indent=2) + "\n")
        receipt.chmod(0o644)
        verify(stage)
        # Refuse a destination created during transfer, including a symlink.
        # The parent is a trusted developer build directory, not agent storage.
        if output.exists() or output.is_symlink():
            raise ValueError("The toolkit output appeared during preparation; existing data is preserved")
        os.rename(stage, output)
    return metadata()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--output", type=Path)
    commands.add_argument("--verify", type=Path)
    parser.add_argument("--cache", type=Path, help="Reuse an existing verified bundle without network access")
    args = parser.parse_args()
    if args.verify:
        if args.cache:
            parser.error("--cache belongs only to preparation")
        result = verify(args.verify)
    else:
        result = prepare(args.output, cache=args.cache)
    print(json.dumps({"recipe": result["recipe"], "packages": len(result["packages"]), "installed": False}))


if __name__ == "__main__":
    main()
