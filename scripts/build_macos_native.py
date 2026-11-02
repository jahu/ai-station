"""Compile the fixed native Mac presentation/bootstrap; not installer readiness."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from macos_desktop_python import native_file

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {"arm64": [14, 0], "x86_64": [13, 3]}


def build(output, architecture):
    if platform.system() != "Darwin" or platform.machine() != architecture or architecture not in TARGETS:
        raise RuntimeError("Compile this native interface on its actual supported Mac architecture")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Choose a new canonical native interface directory")
    output.mkdir(mode=0o700)
    source = ROOT / "packaging/macos/native.m"
    binary = output / "ai-station-native"
    minimum = TARGETS[architecture]
    # No Xcode/driver installation or global SDK/settings changes. Build hosts
    # need their ordinary developer tools; the application ships this binary.
    result = subprocess.run(
        [
            "/usr/bin/xcrun",
            "clang",
            "-fobjc-arc",
            "-fmodules",
            "-framework",
            "Cocoa",
            "-arch",
            architecture,
            "-mmacosx-version-min=" + ".".join(map(str, minimum)),
            "-Werror=implicit-function-declaration",
            "-Werror=return-type",
            str(source),
            "-o",
            str(binary),
        ],
        env={"PATH": os.defpath, "HOME": str(output)},
        check=False,
        timeout=120,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (output / "compiler.stderr").write_bytes(result.stderr)
    if result.returncode:
        # Fixed public build input only; no application credentials or prompts.
        raise RuntimeError(
            "Native interface compilation failed: " + result.stderr.decode(errors="replace")[-6000:]
        )
    actual_minimum = native_file(binary, architecture, minimum)
    value = {
        "schema": 1,
        "architecture": architecture,
        "minimum_os": minimum,
        "binary_minimum_os": actual_minimum,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "native_ui_exercised": False,
        "macos_installer_qualified": False,
    }
    (output / "native-interface.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--architecture", choices=list(TARGETS), required=True)
    args = parser.parse_args()
    value = build(args.output, args.architecture)
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
