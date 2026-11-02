"""Explicit native .app entry/verification experiment with a neutral image fixture."""

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def main(architecture):
    if (
        platform.system() != "Darwin"
        or platform.machine() != architecture
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
    ):
        raise RuntimeError("Use the isolated/no-bytecode application Python on its native Mac")
    root = Path(__file__).resolve().parent.parent
    layer = root / ".native-mac/application-python"
    if Path(sys.prefix).resolve() != layer.resolve(strict=True):
        raise RuntimeError("The bundle experiment requires the actual installed application interpreter")
    sys.path.insert(0, str(root / "scripts"))  # Reviewed producer only; never Runner source.
    import build_macos_package as build

    before = build.file_manifest(layer)
    with tempfile.TemporaryDirectory(prefix="ais-bundle-", dir="/private/tmp") as temporary:
        work = Path(temporary).resolve()
        output, home = work / "AI Station.app", work / "home"
        home.mkdir(mode=0o700)
        identity = "sha256:" + "b" * 64

        def fixture_image(name, target, _receipt):
            if name != "ai-station:entry-probe" or target != architecture:
                raise ValueError("Unexpected native entry fixture")
            return identity, "unix:///private/neutral-entry-fixture.sock"

        def fixture_export(image_id, tag, destination, *, endpoint):
            if (
                image_id != identity
                or not tag.startswith("ai-station:desktop-")
                or endpoint != "unix:///private/neutral-entry-fixture.sock"
            ):
                raise ValueError("Unexpected native entry export")
            destination.write_bytes(b"Neutral entry/verification fixture, never loaded into Docker.\n")

        # Only the image provider is a double. Native executable, installed
        # Python, source/inventory validation, actual .app layout and entry path
        # use the production producer. This cannot qualify Docker or first run.
        with (
            patch.object(build, "image_identity", fixture_image),
            patch.object(build, "export_image", fixture_export),
            patch.object(build, "docker", side_effect=AssertionError("No Docker in the entry experiment")),
        ):
            metadata = build.bundle(
                output,
                layer,
                root / ".native-mac/native-interface",
                architecture,
                "ai-station:entry-probe",
                work / "unused-fixture-receipt.json",
            )
        executable = output / "Contents/MacOS/AI Station"
        env = {"PATH": os.defpath, "HOME": str(home), "LANG": "C"}

        def run(*args):
            return subprocess.run(
                [str(executable), *args],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        result = run("--package-check")
        if result.returncode or json.loads(result.stdout) != {
            "package_verified": True,
            "bundle_id": metadata["bundle_id"],
            "workloads_started": False,
        }:
            raise ValueError("The actual .app entry did not verify its own resources")
        resources = output / "Contents/Resources"
        result = subprocess.run(
            [str(resources / "python/bin/python3"), "-IB", str(resources / "scripts/launch.py"), "--help"],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or "--desktop" not in result.stdout or result.stderr:
            raise ValueError("The actual isolated package supervisor could not import its helpers")
        result = subprocess.run(
            [
                str(resources / "python/bin/python3"),
                "-IB",
                str(resources / "scripts/macos_transport_probe.py"),
                "--help",
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or "--data-directory" not in result.stdout or result.stderr:
            raise ValueError("The actual isolated bridge child could not import its helpers")
        result = subprocess.run(
            [
                str(resources / "python/bin/python3"),
                "-IB",
                "-c",
                "import sys;sys.path.insert(0,sys.argv[1]);import desktop_bridge",
                str(resources / "scripts"),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or result.stdout or result.stderr:
            raise ValueError("The actual isolated desktop bridge coordinator could not import")
        (output / "Contents/Resources/control-plane.tar").write_bytes(b"changed fixture")
        result = run("--package-check")
        if result.returncode != 1 or "missing or changed" not in result.stderr:
            raise ValueError("The actual .app entry did not reject changed resources without UI")
        result = run("--package-check", "--stop")
        if result.returncode != 2:
            raise ValueError("The .app entry accepted conflicting read-only flags")
        if list(home.iterdir()) or build.file_manifest(layer) != before:
            raise ValueError("Native entry verification changed application Python or user data")
    value = {
        "architecture": architecture,
        "platform": "Darwin",
        "os_version": platform.mac_ver()[0],
        "native_bundle_entry_passed": True,
        "actual_installed_python": True,
        "package_check_passed": True,
        "isolated_packaged_supervisor_import_passed": True,
        "isolated_packaged_bridge_import_passed": True,
        "tampering_refused": True,
        "conflicting_flags_refused": True,
        "python_inventory_unchanged": True,
        "station_data_created": False,
        "fixture_image_only": True,
        "docker_desktop_tested": False,
        "model_inference_tested": False,
        "macos_installer_qualified": False,
    }
    print(json.dumps(value, sort_keys=True))
    return value


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Choose the native architecture")
    main(sys.argv[1])
