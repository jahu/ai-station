#!/usr/bin/env python3
"""Explicitly prepare an owned pinned Krea runtime, separate from external ComfyUI.

Default is a read-only plan. --install fetches three exact source revisions and
installs hash-locked wheels into a new private venv. No models or drivers are
downloaded, inference is not launched, and AI Station configuration is unchanged.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/images/krea2-companions.json"
LOCK = ROOT / "config/images/krea2-runtime.lock"
OWNER = "ai-station-runtime.json"
SOURCES = {
    "comfy": "https://github.com/Comfy-Org/ComfyUI.git",
    "gguf": "https://github.com/city96/ComfyUI-GGUF.git",
    "edit": "https://github.com/lbouaraba/comfyui-krea2edit.git",
}


def destination_path(value):
    path = Path(os.path.abspath(Path(value).expanduser()))
    if path == Path(path.anchor) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Choose a dedicated native runtime directory without symlinks")
    return path


def plan(destination):
    import hashlib

    revisions = json.loads(MANIFEST.read_text())["runtime_revisions"]
    return {
        "owner": "ai-station",
        "destination": str(destination_path(destination)),
        "profile": "gpu-only",
        "sources": {name: {"url": url, "revision": revisions[name]} for name, url in SOURCES.items()},
        "dependency_lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        "inference_qualified": False,
    }


def run(args):
    subprocess.run(args, check=True)


def install(destination):
    details = plan(destination)
    path = Path(details["destination"])
    tools = {name: shutil.which(name) for name in ("git", "uv")}
    if not all(tools.values()):
        raise ValueError("Krea runtime installation requires Git and uv")
    path.parent.mkdir(parents=True, exist_ok=True)
    destination_path(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        owner = path / OWNER
        if owner.is_symlink() or not owner.is_file() or json.loads(owner.read_text()) != details:
            raise ValueError("Existing directory is not this pinned owned runtime") from None
    else:
        with (path / OWNER).open("x") as handle:
            json.dump(details, handle, indent=2)
    # Serialize source checkout and venv installation, including interrupted setup.
    import fcntl

    with (path / OWNER).open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name, source in details["sources"].items():
            checkout = destination_path(path / name)
            if not checkout.exists():
                run([tools["git"], "init", "-q", str(checkout)])
                run(
                    [
                        tools["git"],
                        "-C",
                        str(checkout),
                        "fetch",
                        "--depth=1",
                        source["url"],
                        source["revision"],
                    ]
                )
                run([tools["git"], "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"])
            actual = subprocess.check_output(
                [tools["git"], "-C", str(checkout), "rev-parse", "HEAD"], text=True
            ).strip()
            dirty = subprocess.check_output(
                [tools["git"], "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
                text=True,
            ).strip()
            if actual != source["revision"] or dirty:
                raise ValueError("Refusing to replace changed runtime source")
        python = destination_path(path / "venv") / "bin/python"
        if not python.exists():
            run([tools["uv"], "venv", "--python", sys.executable, str(path / "venv")])
        run(
            [
                tools["uv"],
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "--only-binary",
                ":all:",
                "-r",
                str(LOCK),
            ]
        )
    return {**details, "dependencies_installed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.destination) if args.install else plan(args.destination), indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Krea runtime setup failed: {exc}\n")


if __name__ == "__main__":
    main()
