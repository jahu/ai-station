"""Build a private checksummed WSL rootfs from an audited Debian package. No host OS changes."""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from desktop import digest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging/windows"
BASE = "ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852"


def package_identity(package, expected):
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or package.is_symlink() or not package.is_file():
        raise ValueError("Use an audited regular Debian package and its complete SHA-256")
    if not 0 < package.stat().st_size < 1024**3 or digest(package) != expected:
        raise ValueError("The Debian package differs from its audited identity")
    result = subprocess.run(
        [
            "dpkg-deb",
            "--field",
            str(package),
            "Package",
            "Version",
            "Architecture",
            "X-AI-Station-Desktop-Protocol",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    fields = dict(line.split(": ", 1) for line in result.stdout.splitlines())
    if fields.get("Package") != "ai-station" or fields.get("Architecture") != "amd64":
        raise ValueError("The Windows x64 guest requires the AI Station amd64 package")
    if fields.get("X-AI-Station-Desktop-Protocol") != "2":
        raise ValueError("The Windows guest requires desktop protocol 2 (browser identity and host port)")
    return fields


def build(package, expected, output):
    package = package.absolute()
    fields = package_identity(package, expected)
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a fresh output directory; existing packages and user data are preserved")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Commit the reviewed source before building a Windows guest")
    source_hashes = {
        name: digest(SOURCE / name) for name in ["guest.Dockerfile", "wsl.conf", "guest_control.py"]
    }
    receipt = dict(
        schema=1,
        desktop_protocol=2,
        source_head=head,
        base=BASE,
        package_sha256=expected,
        package=fields,
        sources=source_hashes,
        qualification="private-build-only; Windows WSL acceptance pending",
    )
    identity = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    image = "ai-station:wsl-build-" + identity[:16]
    container = "ai-station-wsl-export-" + uuid.uuid4().hex
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    with tempfile.TemporaryDirectory(prefix=".wsl-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        context = stage / "context"
        context.mkdir()
        for name in source_hashes:
            shutil.copy2(SOURCE / name, context / name)
        shutil.copy2(package, context / "station.deb")
        if digest(context / "station.deb") != expected or any(
            digest(context / name) != expected_hash for name, expected_hash in source_hashes.items()
        ):
            raise ValueError("Package inputs changed while creating the private build context")
        (context / "guest-build.json").write_text(json.dumps(receipt, indent=2) + "\n")
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--tag",
                image,
                "--file",
                str(context / "guest.Dockerfile"),
                str(context),
            ],
            check=True,
        )
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
        ).strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise ValueError("Docker returned an invalid built-image identity")
        archive = stage / "ai-station-wsl-rootfs.tar.gz"
        try:
            subprocess.run(
                ["docker", "create", "--name", container, image_id], check=True, stdout=subprocess.DEVNULL
            )
            created = True
            with (
                archive.open("xb") as raw,
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
            ):
                with subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE) as exporter:
                    try:
                        shutil.copyfileobj(exporter.stdout, compressed, length=1024**2)
                    except BaseException:
                        exporter.terminate()
                        raise
                    if exporter.wait() != 0:
                        raise RuntimeError("The guest filesystem export did not complete")
        finally:
            if created:
                # Only our never-started, unique export container; never --force or global prune.
                subprocess.run(["docker", "rm", container], check=True, stdout=subprocess.DEVNULL)
        published = stage / "published"
        published.mkdir()
        shutil.move(archive, published / archive.name)
        receipt.update(
            image_id=image_id,
            image_tag=image,
            rootfs_sha256=digest(published / archive.name),
            rootfs_bytes=(published / archive.name).stat().st_size,
        )
        (published / "windows-guest-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
        os.rename(published, output)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build(args.package, args.package_sha256, args.output.absolute())
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
