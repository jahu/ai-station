"""Prepare application Python from a verified Mac layer; never consumer readiness."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from ai_station_runner.runtime_install import atomic_json
from build_linux_package import digest, file_manifest
from macos_desktop_python import CPU, fingerprint, install, native_file, recipe

ROOT = Path(__file__).resolve().parent.parent
SITE = "lib/python3.12/site-packages/"
PACKAGE = "ai_station_runner/"
DIST = "ai_station_runner-0.1.0.dist-info/"


def base_layer(path, architecture):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("Use a canonical verified native Python layer")
    record = path / "native-python.json"
    if record.is_symlink() or not record.is_file() or record.stat().st_size > 8 * 1024**2:
        raise ValueError("Native Python requires a bounded regular receipt")
    receipt = json.loads(record.read_text())
    frozen = recipe(architecture)
    if (
        receipt.get("schema") != 1
        or receipt.get("architecture") != architecture
        or receipt.get("manifest_sha256") != fingerprint(frozen)
        or receipt.get("python_version") != frozen["python_version"]
        or receipt.get("minimum_os") != frozen["minimum_os"]
    ):
        raise ValueError("Native Python receipt does not match the reviewed architecture/recipe")
    files = file_manifest(path)
    files.pop("native-python.json")
    if files != receipt.get("files"):
        raise ValueError("The verified native Python layer changed")
    native_file(path / "bin/python3.12", architecture, frozen["minimum_os"])
    return receipt, file_manifest(path)


def tracked_source(destination, *, allow_dirty=False):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    status = ["status", "--porcelain"]
    if destination.parent.is_relative_to(ROOT):
        # Our newly created stage is not an unreviewed source modification.
        status += ["--", ".", ":(exclude)" + destination.parent.relative_to(ROOT).as_posix()]
    head, dirty = git("rev-parse", "HEAD"), bool(git(*status))
    if not re.fullmatch(r"[a-f0-9]{40}", head) or (dirty and not allow_dirty):
        raise ValueError("Commit reviewed source first; dirty builds are private qualification only")
    names = git("ls-files", "--", "host-runner/pyproject.toml", "host-runner/ai_station_runner").splitlines()
    if "host-runner/pyproject.toml" not in names or not any(name.endswith("/__init__.py") for name in names):
        raise ValueError("The tracked Host Runner package is incomplete")
    for name in names:
        source = ROOT / name
        if source.resolve(strict=True) != source or not source.is_file():
            raise ValueError("Tracked package inputs must be canonical regular files")
        target = destination / Path(name).relative_to("host-runner")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return head, dirty, file_manifest(destination / "ai_station_runner")


def build_wheel(source, wheels, work):
    executable = shutil.which("uv")
    if not executable:
        raise RuntimeError("The package builder requires uv; consumers do not")
    subprocess.run(
        [
            executable,
            "--no-config",
            "--no-python-downloads",
            "build",
            "--wheel",
            "--out-dir",
            str(wheels),
            str(source),
        ],
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(work),
            "UV_CACHE_DIR": str(work / "uv-cache"),
        },
        check=True,
        timeout=180,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ignored = wheels / ".gitignore"
    if ignored.exists() or ignored.is_symlink():
        # uv creates this exact non-code marker in its output wheel directory.
        if ignored.is_symlink() or not ignored.is_file() or ignored.read_bytes() != b"*":
            raise ValueError("Unexpected wheel output marker")
    found = [path for path in wheels.iterdir() if path.name != ".gitignore"]
    if len(found) != 1 or found[0].name != "ai_station_runner-0.1.0-py3-none-any.whl":
        raise ValueError("The Host Runner must build as one regular pure-Python wheel")
    return found[0]


def verify_wheel(wheel, source_files):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            not name.startswith((PACKAGE, DIST))
            or ".." in Path(name).parts
            or "\\" in name
            or name.endswith(".pth")
            or ((archive.getinfo(name).external_attr >> 16) & 0o170000) == 0o120000
            for name in names
        ):
            raise ValueError("The application wheel contains unexpected paths or links")
        observed = {
            name.removeprefix(PACKAGE): hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith(PACKAGE) and not name.endswith("/")
        }
        if observed != source_files or b"Tag: py3-none-any" not in archive.read(DIST + "WHEEL"):
            raise ValueError("Wheel package bytes differ from the tracked Host Runner")


def prepare(output, layer, architecture, *, allow_dirty=False):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Choose a new canonical application Python output")
    layer = Path(layer).absolute()
    original, before = base_layer(layer, architecture)
    if output.parent.is_relative_to(layer):
        raise ValueError("Application output must remain outside its verified base layer")
    with tempfile.TemporaryDirectory(prefix=".mac-app-python-", dir=output.parent) as temporary:
        work = Path(temporary)
        source, wheels = work / "runner-source", work / "wheels"
        source.mkdir()
        wheels.mkdir()
        head, dirty, sources = tracked_source(source, allow_dirty=allow_dirty)
        wheel = build_wheel(source, wheels, work)
        verify_wheel(wheel, sources)
        target = work / "python"
        shutil.copytree(layer, target, symlinks=True)
        install(
            target / "bin/python3.12",
            work,
            [{"name": "ai-station-runner", "version": "0.1.0", "sha256": digest(wheel)}],
            architecture,
            original["minimum_os"],
        )
        after = file_manifest(target)
        if file_manifest(layer) != before or any(after.get(name) != value for name, value in before.items()):
            raise ValueError("Application installation modified verified Python dependencies")
        added = set(after) - set(before)
        if not added or any(not name.startswith((SITE + PACKAGE, SITE + DIST)) for name in added):
            raise ValueError("Application installation added unexpected interpreter files")
        installed = {
            name.removeprefix(SITE + PACKAGE): value
            for name, value in after.items()
            if name.startswith(SITE + PACKAGE)
        }
        if installed != sources:
            raise ValueError("Installed Host Runner bytes differ from reviewed source")
        receipt = {
            "schema": 1,
            "profile": f"application-python312-darwin-{architecture}-v1",
            "architecture": architecture,
            "source_head": head,
            "source_dirty": dirty,
            "base_manifest_sha256": original["manifest_sha256"],
            "base_receipt_sha256": before["native-python.json"],
            "wheel_sha256": digest(wheel),
            "runner_source_files": sources,
            "base_inventory_unchanged": True,
            "files": after,
            "native_application_executed": False,
            "macos_installer_qualified": False,
        }
        output.mkdir(mode=0o700)
        # Failed/incomplete publication is retained, never overwritten on retry.
        for item in target.iterdir():
            os.rename(item, output / item.name)
        if file_manifest(output) != after:
            raise ValueError("Application Python changed during publication")
        atomic_json(output, "application-python.json", receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=list(CPU), required=True)
    parser.add_argument("--python-layer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help="Private qualification only")
    args = parser.parse_args()
    value = prepare(args.output, args.python_layer, args.architecture, allow_dirty=args.allow_dirty)
    print(
        json.dumps(
            {
                key: value[key]
                for key in ("profile", "source_head", "source_dirty", "macos_installer_qualified")
            }
        )
    )


if __name__ == "__main__":
    main()
