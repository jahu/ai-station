"""Offline native Mac Python layer for consumer packaging; never platform readiness."""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from ai_station_runner.runtime_install import atomic_json
from ai_station_runner.speech_environment import directory, fingerprint, unpack_python, verified_object
from build_linux_package import file_manifest

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "packaging/macos"
CPU = {"arm64": 0x100000C, "x86_64": 0x1000007}


def recipe(architecture):
    if architecture not in CPU:
        raise ValueError("Select a reviewed native Mac package architecture")
    value = json.loads((RECIPES / (architecture + ".json")).read_text())
    if (
        value["schema"] != 1
        or value["profile"] != f"desktop-python312-darwin-{architecture}-v1"
        or value["architecture"] != architecture
        or value["minimum_os"] != ([14, 0] if architecture == "arm64" else [13, 3])
        or value["python_version"] != "3.12.14"
        or value["python_publisher_release"] != "20260901"
        or value["consumer_qualified"] is not False
        or len(value["inputs"]) != 27
        or value["inputs"][0]["kind"] != "python"
        or any(item["kind"] != "wheel" for item in value["inputs"][1:])
    ):
        raise ValueError("The built-in Mac Python packaging recipe changed")
    names, hashes = set(), set()
    for item in value["inputs"]:
        filename = item["filename"]
        allowed_url = (
            item["url"]
            == "https://github.com/astral-sh/python-build-standalone/releases/download/20260901/"
            + filename.replace("+", "%2B")
            if item["kind"] == "python"
            else item["url"].startswith("https://files.pythonhosted.org/packages/")
            and item["url"].endswith("/" + filename)
        )
        if (
            not re.fullmatch(r"[A-Za-z0-9_.+-]+", filename)
            or filename in names
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
            or item["sha256"] in hashes
            or type(item["size_bytes"]) is not int
            or not 0 < item["size_bytes"] < 100 * 1024**2
            or not allowed_url
            or (
                item["kind"] == "wheel"
                and (
                    not filename.endswith(".whl")
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", item["name"])
                    or not re.fullmatch(r"[0-9][A-Za-z0-9_.+-]*", item["version"])
                )
            )
        ):
            raise ValueError("Invalid fixed Mac packaging input coordinate")
        names.add(filename)
        hashes.add(item["sha256"])
    return value


def native_file(path, architecture, minimum_os):
    """Inspect the selected thin/universal Mach-O slice without executing it."""
    with path.open("rb") as source:
        header = source.read(32)
        if len(header) != 32:
            raise ValueError("Truncated native Mac executable")
        offset = 0
        if header[:4] == b"\xca\xfe\xba\xbe":
            count = struct.unpack_from(">I", header, 4)[0]
            if not 1 <= count <= 8:
                raise ValueError("Native universal slice count exceeds its bound")
            source.seek(8)
            slices = source.read(count * 20)
            if len(slices) != count * 20:
                raise ValueError("Truncated native universal slice table")
            matches = []
            size = os.fstat(source.fileno()).st_size
            for at in range(count):
                cpu, _, start, length, alignment = struct.unpack_from(">IIIII", slices, at * 20)
                if start < 8 + count * 20 or length < 32 or start + length > size or alignment > 30:
                    raise ValueError("Invalid native universal slice boundary")
                if cpu == CPU[architecture]:
                    matches.append((start, length))
            if len(matches) != 1:
                raise ValueError("The selected native architecture is absent or ambiguous")
            offset, slice_size = matches[0]
            source.seek(offset)
            header = source.read(32)
        else:
            slice_size = os.fstat(source.fileno()).st_size
        if header[:4] != b"\xcf\xfa\xed\xfe":
            raise ValueError("Expected a native 64-bit Mac executable")
        _, cpu, _, kind, count, length, _, _ = struct.unpack("<IiiIIIII", header)
        if (
            cpu != CPU[architecture]
            or kind not in {2, 6, 8}
            or not 0 < count <= 4096
            or not 0 < length <= 1024**2
            or length + 32 > slice_size
        ):
            raise ValueError("Native Mac architecture/type/commands differ")
        source.seek(offset + 32)
        commands = source.read(length)
    if len(commands) != length:
        raise ValueError("Truncated native Mac load commands")
    at, minimum = 0, None
    for _ in range(count):
        if at + 8 > length:
            raise ValueError("Truncated native Mac load command")
        command, size = struct.unpack_from("<II", commands, at)
        if size < 8 or at + size > length:
            raise ValueError("Invalid native Mac load command boundary")
        if command in {0x24, 0x32}:
            if minimum is not None or size < (24 if command == 0x32 else 16):
                raise ValueError("Ambiguous native Mac minimum OS")
            if command == 0x32 and struct.unpack_from("<I", commands, at + 8)[0] != 1:
                raise ValueError("The native binary targets a different Apple platform")
            version = struct.unpack_from("<I", commands, at + (12 if command == 0x32 else 8))[0]
            minimum = (version >> 16, version >> 8 & 255, version & 255)
        at += size
    if at != length or minimum is None or not (10, 0, 0) <= minimum <= (*minimum_os, 0):
        raise ValueError("The native binary minimum OS differs from its package")
    return list(minimum)


def fetch(cache, frozen, check):
    """Trusted build step; exact built-in public inputs, no model/network runtime."""
    store = directory(cache, "models/store")
    for item in frozen["inputs"]:
        check()
        target = store / item["sha256"]
        if target.exists() or target.is_symlink():
            verified_object(cache, item, check)
            continue
        fd, temporary = tempfile.mkstemp(prefix=".download-", dir=store)
        try:
            count, digest = 0, hashlib.sha256()
            with (
                os.fdopen(fd, "wb") as output,
                httpx.Client(timeout=30, trust_env=False, follow_redirects=True) as client,
            ):
                with client.stream("GET", item["url"]) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        check()
                        count += len(chunk)
                        if count > item["size_bytes"]:
                            raise ValueError("The fixed Mac packaging input exceeds its length")
                        digest.update(chunk)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("The fixed Mac packaging input checksum differs")
            os.chmod(temporary, 0o444)
            os.link(temporary, target)  # Never replace a concurrently published object.
        finally:
            Path(temporary).unlink(missing_ok=True)
        verified_object(cache, item, check)


def install(python, folder, wheels, architecture, minimum_os):
    executable = shutil.which("uv")
    if not executable:
        raise RuntimeError("The package builder requires uv; consumers do not")
    site = python.parent.parent / "lib/python3.12/site-packages"
    if (site / "bin").exists():
        raise ValueError("The pinned Python already contains an unexpected target script directory")
    lock = folder / "requirements.lock"
    lock.write_text(
        "\n".join(f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}" for item in wheels)
        + "\n"
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(folder),
        "UV_CACHE_DIR": str(folder / "uv-cache"),
        "MACOSX_DEPLOYMENT_TARGET": ".".join(map(str, minimum_os)),
    }
    subprocess.run(
        [
            executable,
            "--no-config",
            "--offline",
            "--no-python-downloads",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(site),
            "--python-version",
            "3.12",
            "--python-platform",
            "aarch64-apple-darwin" if architecture == "arm64" else "x86_64-apple-darwin",
            "--only-binary",
            ":all:",
            "--no-index",
            "--no-deps",
            "--no-installer-metadata",
            "--link-mode",
            "copy",
            "--require-hashes",
            "--find-links",
            str(folder / "wheels"),
            "-r",
            str(lock),
        ],
        env=env,
        check=True,
        timeout=180,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    scripts = site / "bin"
    if scripts.exists():
        if scripts.is_symlink() or not scripts.is_dir():
            raise ValueError("Native package script storage changed")
        shutil.rmtree(scripts)  # Build-path console shebangs are never shipped.


def prepare(output, cache, architecture, *, download=False):
    output, cache = Path(output).absolute(), Path(cache).resolve(strict=True)
    if output.exists() or output.is_symlink() or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Choose a new canonical native Python output directory")
    info = cache.stat()
    if not cache.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("Use an owned packaging input cache")
    frozen = recipe(architecture)
    deadline = time.monotonic() + 600

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Native Python packaging deadline exceeded")

    if download:
        fetch(cache, frozen, check)
    inputs = {item["filename"]: verified_object(cache, item, check) for item in frozen["inputs"]}
    with tempfile.TemporaryDirectory(prefix=".mac-python-", dir=output.parent) as temporary:
        stage = Path(temporary)
        python = unpack_python(inputs[frozen["inputs"][0]["filename"]], stage, check)
        native_file(python.resolve(strict=True), architecture, frozen["minimum_os"])
        wheels = directory(stage, "wheels")
        for item in frozen["inputs"][1:]:
            if Path(item["filename"]).name != item["filename"]:
                raise ValueError("Mac packaging requires fixed wheel filenames")
            (wheels / item["filename"]).symlink_to(inputs[item["filename"]])
        install(python, stage, frozen["inputs"][1:], architecture, frozen["minimum_os"])
        observed = {}
        for path in (stage / "python").rglob("*"):
            check()
            if (
                path.is_file()
                and not path.is_symlink()
                and (path.suffix in {".so", ".dylib"} or path.name == "python3.12")
            ):
                observed[path.relative_to(stage / "python").as_posix()] = native_file(
                    path, architecture, frozen["minimum_os"]
                )
        metadata = {
            "schema": 1,
            "profile": frozen["profile"],
            "manifest_sha256": fingerprint(frozen),
            "architecture": architecture,
            "minimum_os": frozen["minimum_os"],
            "python_version": frozen["python_version"],
            "native_mac_code_executed": False,
            "python_import_qualified": False,
            "macos_installer_qualified": False,
            "native_files": observed,
            "files": file_manifest(stage / "python"),
        }
        output.mkdir(mode=0o700)  # Exclusive publication; never overwrite an existing build.
        try:
            for path in (stage / "python").iterdir():
                os.rename(path, output / path.name)
            if file_manifest(output) != metadata["files"]:
                raise ValueError("Native Python changed during publication")
            atomic_json(output, "native-python.json", metadata)
        except BaseException:
            # The caller-owned new output is retained for explicit inspection.
            raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=list(CPU), required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-inputs", action="store_true")
    args = parser.parse_args()
    value = prepare(args.output, args.cache, args.architecture, download=args.download_inputs)
    print(
        json.dumps(
            {
                key: value[key]
                for key in ("profile", "architecture", "python_import_qualified", "macos_installer_qualified")
            }
        )
    )


if __name__ == "__main__":
    main()
