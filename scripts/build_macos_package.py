"""Assemble a native Mac application from reviewed inputs; no runtime installation."""

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_control_plane_image import recipe as image_recipe
from build_linux_package import copy_sources, digest, file_manifest, package_permissions
from desktop import DESKTOP_PROTOCOL
from macos_application_probe import receipt, verify_layer
from macos_desktop_python import fingerprint, native_file, recipe

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURES = {"arm64": "arm64", "x86_64": "amd64"}
MAC_SOURCES = (
    "scripts/macos_desktop_docker.py",
    "scripts/macos_transport_probe.py",
    "scripts/desktop_bridge.py",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def docker(*args):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={key: value for key, value in os.environ.items() if key not in {"DOCKER_CONTEXT", "DOCKER_HOST"}},
    )


def application_python(path, architecture):
    path = Path(path).absolute()
    value, files = verify_layer(path, architecture, ROOT)
    frozen = recipe(architecture)
    native_file(path / "bin/python3.12", architecture, frozen["minimum_os"])
    return path, value, files


def native_interface(path, architecture):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("Use a canonical native interface directory")
    value = receipt(path / "native-interface.json")
    minimum = recipe(architecture)["minimum_os"]
    binary = path / "ai-station-native"
    if (
        value.get("schema") != 1
        or value.get("architecture") != architecture
        or value.get("minimum_os") != minimum
        or value.get("source_sha256") != digest(ROOT / "packaging/macos/native.m")
        or binary.is_symlink()
        or not binary.is_file()
        or not os.access(binary, os.X_OK)
        or value.get("binary_sha256") != digest(binary)
        or value.get("macos_installer_qualified") is not False
    ):
        raise ValueError("Native interface differs from reviewed source/architecture")
    native_file(binary, architecture, minimum)
    return binary, value


def image_identity(name, architecture, build_receipt):
    if not re.fullmatch(r"ai-station:[a-z0-9][a-z0-9_.-]{0,100}", name):
        raise ValueError("Choose a project-owned local application image")
    import hashlib

    built = receipt(Path(build_receipt))
    dockerfile = (ROOT / "Dockerfile").read_bytes()
    if (
        built.get("status") != "built_image_only"
        or built.get("source_head") != git("rev-parse", "HEAD")
        or built.get("platform") != "linux/" + ARCHITECTURES[architecture]
        or built.get("image_tag") != name
        or built.get("canonical_dockerfile_sha256") != hashlib.sha256(dockerfile).hexdigest()
        or built.get("generated_dockerfile_sha256") != hashlib.sha256(image_recipe(dockerfile)).hexdigest()
    ):
        raise ValueError("Application image build receipt differs from reviewed source/target")
    # This is a trusted developer producer, never a Runner/API operation. It
    # creates only its new desktop tag and never changes global Docker settings.
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = os.environ.get("DOCKER_HOST") if not context else None
    if not endpoint:
        result = docker(
            "context",
            "inspect",
            *([context] if context else []),
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        )
        if result.returncode:
            raise RuntimeError("Inspect the local developer Docker prerequisite")
        endpoint = result.stdout.strip()
    if not endpoint.startswith("unix:///"):
        raise ValueError("Mac packaging uses only a local Unix Docker endpoint")
    result = docker("--host", endpoint, "image", "inspect", name)
    if result.returncode:
        raise RuntimeError("Build the selected application image before packaging")
    rows = json.loads(result.stdout)
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("Os") != "linux"
        or rows[0].get("Architecture") != ARCHITECTURES[architecture]
        or rows[0].get("Config", {}).get("User") != "1000:1000"
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(rows[0].get("Id", "")))
        or rows[0].get("Id") != built.get("image_id")
    ):
        raise ValueError("Application image architecture, non-root user or identity differs")
    return rows[0]["Id"], endpoint


def export_image(identity, tag, destination, *, endpoint):
    previous = docker("--host", endpoint, "image", "inspect", tag)
    if previous.returncode == 0 or "no such image" not in previous.stderr.lower():
        raise ValueError("The desktop tag already exists or its absence is uncertain")
    result = docker("--host", endpoint, "image", "tag", identity, tag)
    if result.returncode:
        raise RuntimeError("The desktop image tag was not prepared; inspect before retrying")
    # Retain this new project-owned tag if export fails; never replay an
    # uncertain operation or delete an existing developer image.
    result = docker("--host", endpoint, "image", "save", "--output", str(destination), tag)
    if result.returncode:
        raise RuntimeError("The desktop image export failed; inspect its retained tag")


def bundle(output, python_layer, native_layer, architecture, image, image_build, *, version="0.1.0"):
    if architecture not in ARCHITECTURES:
        raise ValueError("Choose a supported native Mac architecture")
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]?)\.(?:0|[1-9][0-9]?)", version):
        raise ValueError("Choose a three-part numeric Mac application version")
    output = Path(output).absolute()
    if (
        output.suffix != ".app"
        or output.exists()
        or output.is_symlink()
        or output.parent.resolve(strict=True) != output.parent
    ):
        raise ValueError("Choose a new canonical .app destination")
    head = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[a-f0-9]{40}", head) or git("status", "--porcelain"):
        raise ValueError("Commit the reviewed source before assembling the application")
    python_layer, python_receipt, python_files = application_python(python_layer, architecture)
    binary, interface_receipt = native_interface(native_layer, architecture)
    for source in (python_layer, binary.parent):
        if output.parent.is_relative_to(source):
            raise ValueError("Application output must remain outside its verified inputs")
    image_id, endpoint = image_identity(image, architecture, image_build)
    identity = fingerprint(
        {
            "head": head,
            "version": version,
            "architecture": architecture,
            "python_receipt": digest(python_layer / "application-python.json"),
            "native": interface_receipt["binary_sha256"],
            "image": image_id,
        }
    )
    tag = "ai-station:desktop-" + identity[:16]
    with tempfile.TemporaryDirectory(prefix=".mac-app-", dir=output.parent) as temporary:
        stage = Path(temporary) / "AI Station.app"
        contents = stage / "Contents"
        resources = contents / "Resources"
        executable = contents / "MacOS/AI Station"
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        copy_sources(resources)
        for name in MAC_SOURCES:
            shutil.copy2(ROOT / name, resources / name)
        shutil.copytree(python_layer, resources / "python", symlinks=True)
        if file_manifest(resources / "python") != python_files:
            raise ValueError("Application Python changed while copying")
        (resources / "bin").mkdir()
        shutil.copy2(binary, resources / "bin/ai-station-native")
        shutil.copy2(binary, executable)
        minimum = ".".join(map(str, recipe(architecture)["minimum_os"]))
        info = {
            "CFBundleExecutable": "AI Station",
            "CFBundleIdentifier": "io.ai-station.desktop",
            "CFBundleName": "AI Station",
            "CFBundleDisplayName": "AI Station",
            "CFBundlePackageType": "APPL",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleVersion": version,
            "CFBundleShortVersionString": version,
            "LSMinimumSystemVersion": minimum,
            "LSArchitecturePriority": [architecture],
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        export_image(image_id, tag, resources / "control-plane.tar", endpoint=endpoint)
        package_permissions(stage)
        metadata = {
            "schema": 1,
            "desktop_protocol": DESKTOP_PROTOCOL,
            "bundle_id": identity,
            "source_head": head,
            "source_epoch": int(git("show", "-s", "--format=%ct", "HEAD")),
            "source_dirty": False,
            "platform": "Darwin",
            "architecture": architecture,
            "version": version,
            "minimum_os": minimum,
            "image_tag": tag,
            "image_id": image_id,
            "python_receipt_sha256": digest(python_layer / "application-python.json"),
            "native_interface_sha256": interface_receipt["binary_sha256"],
            "installed_runner_head": python_receipt["source_head"],
            "signed": False,
            "notarized": False,
            "macos_installer_qualified": False,
            "files": file_manifest(resources),
        }
        (resources / "desktop-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        if digest(executable) != metadata["native_interface_sha256"]:
            raise ValueError("Native application entry changed while copying")
        # Input changes or unreviewed source during a long export cannot publish
        # an apparently clean application. Existing output is never adopted.
        if (
            git("rev-parse", "HEAD") != head
            or git("status", "--porcelain")
            or file_manifest(python_layer) != python_files
            or digest(binary) != metadata["native_interface_sha256"]
        ):
            raise ValueError("Reviewed package inputs changed during assembly")
        os.rename(stage, output)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python-layer", required=True, type=Path)
    parser.add_argument("--native-interface", required=True, type=Path)
    parser.add_argument("--architecture", required=True, choices=list(ARCHITECTURES))
    parser.add_argument("--image", required=True, help="Already-built matching Linux control-plane image")
    parser.add_argument(
        "--image-build", required=True, type=Path, help="build_control_plane_image.py build.json receipt"
    )
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    value = bundle(
        args.output,
        args.python_layer,
        args.native_interface,
        args.architecture,
        args.image,
        args.image_build,
        version=args.version,
    )
    print(
        json.dumps(
            {
                key: value[key]
                for key in ("bundle_id", "architecture", "signed", "notarized", "macos_installer_qualified")
            }
        )
    )


if __name__ == "__main__":
    main()
