"""Build a private Linux desktop bundle/deb; no models or workstation config."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from desktop import digest

ROOT = Path(__file__).resolve().parent.parent
PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA256 = "72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c"
SOURCE = (
    "host-runner/ai_station_runner",
    "scripts/launch.py",
    "scripts/desktop.py",
    "scripts/desktop_control.py",
    "compose.yaml",
    "config/search/settings.yml",
    "LICENSE",
    "NOTICE",
    "COMMERCIAL.md",
)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def copy_sources(destination):
    for name in SOURCE:
        source, target = ROOT / name, destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)


def python_archive(path):
    if not path.exists():
        with urllib.request.urlopen(PYTHON_URL, timeout=30) as source, path.open("xb") as output:
            total = 0
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024**2:
                    raise ValueError("The pinned Python distribution exceeded its expected bound")
                output.write(chunk)
    if digest(path) != PYTHON_SHA256:
        raise ValueError("The Python archive does not match its pinned publisher hash")


def file_manifest(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("The package contains a link outside its directory")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def build(output, *, allow_dirty=False, python_tar=None):
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("Build this package on Linux x86-64")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty and not allow_dirty:
        raise RuntimeError(
            "Commit the reviewed source first; --allow-dirty is for private qualification only"
        )
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new package destination; existing output is never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".desktop-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        bundle = stage / "bundle"
        bundle.mkdir()
        copy_sources(bundle)
        shutil.copy2(ROOT / "packaging/linux/requirements.lock", bundle / "native-requirements.lock")
        files = file_manifest(bundle)
        patch = subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)
        identity = hashlib.sha256(
            json.dumps(
                {"files": files, "head": head, "patch": hashlib.sha256(patch).hexdigest()}, sort_keys=True
            ).encode()
        ).hexdigest()
        image_tag = "ai-station:desktop-" + identity[:16]
        archive = python_tar or stage / "python.tar.gz"
        python_archive(archive)
        with tarfile.open(archive) as source:
            source.extractall(bundle, filter="data")
        python = bundle / "python/bin/python3"
        original_bin = {path.name for path in python.parent.iterdir()}
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--prefix",
            str(bundle / "python"),
            "--require-hashes",
            "--no-deps",
            "--no-installer-metadata",
            "-r",
            str(ROOT / "packaging/linux/requirements.lock"),
        )
        # Install a regular wheel, never an editable reference to the build tree.
        runner_source = stage / "runner-source"
        runner_source.mkdir()
        shutil.copy2(ROOT / "host-runner/pyproject.toml", runner_source / "pyproject.toml")
        shutil.copytree(bundle / "host-runner/ai_station_runner", runner_source / "ai_station_runner")
        run("uv", "build", "--wheel", "--out-dir", str(stage / "wheels"), str(runner_source))
        wheel = next((stage / "wheels").glob("*.whl"))
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--prefix",
            str(bundle / "python"),
            "--no-deps",
            "--no-installer-metadata",
            str(wheel),
        )
        for path in python.parent.iterdir():
            if path.name not in original_bin and path.is_file():
                path.unlink()  # Use python -m, never build-path console shebangs.
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        run(
            str(python),
            "-I",
            "-c",
            "import ssl,venv,av,numpy,httpx,dotenv; from ai_station_runner.app import app; assert app",
            env=env,
        )
        run("docker", "build", "-t", image_tag, str(ROOT))
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"], text=True
        ).strip()
        run("docker", "save", "--output", str(bundle / "control-plane.tar"), image_tag)
        (bundle / "station").write_text(
            '#!/bin/sh\nstation_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec "$station_root/python/bin/python3" -I "$station_root/scripts/desktop.py" "$@"\n'
        )
        (bundle / "station").chmod(0o755)
        for cache in bundle.rglob("__pycache__"):
            if cache.is_dir() and not cache.is_symlink():
                shutil.rmtree(cache)
        metadata = {
            "schema": 1,
            "bundle_id": identity,
            "source_head": head,
            "source_epoch": int(
                subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True)
            ),
            "source_dirty": bool(dirty),
            "image_tag": image_tag,
            "image_id": image_id,
            "python_source": {"url": PYTHON_URL, "sha256": PYTHON_SHA256},
            "files": file_manifest(bundle),
        }
        (bundle / "desktop-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        os.rename(bundle, output)
    return metadata


def deb(bundle, metadata):
    result = bundle.with_suffix(".deb")
    if result.exists():
        raise ValueError("The Debian package already exists")
    with tempfile.TemporaryDirectory(prefix=".desktop-deb-", dir=bundle.parent) as temporary:
        root = Path(temporary)
        shutil.copytree(bundle, root / "usr/lib/ai-station", symlinks=True)
        applications = root / "usr/share/applications"
        applications.mkdir(parents=True)
        (applications / "ai-station.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=AI Station\nComment=Your local AI workstation\n"
            "Exec=/usr/lib/ai-station/station\nIcon=ai-station\nTerminal=false\nCategories=Utility;Graphics;AudioVideo;\n"
        )
        icons = root / "usr/share/icons/hicolor/scalable/apps"
        icons.mkdir(parents=True)
        shutil.copy2(ROOT / "frontend/public/station.svg", icons / "ai-station.svg")
        control = root / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            "Package: ai-station\nVersion: 0.1.0~dev."
            + metadata["bundle_id"][:16]
            + "\nArchitecture: amd64\n"
            "Maintainer: AI Station contributors\nSection: utils\nPriority: optional\n"
            "Depends: zenity, libc6 (>= 2.35), docker.io | docker-ce-cli | docker-desktop, docker-compose-v2 | docker-compose-plugin | docker-desktop\n"
            "Description: Local AI workstation with a bundled native Python runner\n"
            " Development package. Docker must be available to the current user.\n"
        )
        run("dpkg-deb", "--root-owner-group", "--build", str(root), str(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python-archive", type=Path, help="Reuse the same pinned, hash-verified archive")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--deb", action="store_true")
    args = parser.parse_args()
    metadata = build(args.output.resolve(), allow_dirty=args.allow_dirty, python_tar=args.python_archive)
    if args.deb:
        print(deb(args.output.resolve(), metadata))


if __name__ == "__main__":
    main()
