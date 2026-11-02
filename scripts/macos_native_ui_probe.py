"""Fresh public Intel UI fixture: host launches; sandboxed XCTest only interacts."""

import json
import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path


def main():
    required = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "jahu/ai-station",
        "GITHUB_ACTOR": "jahu",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "X64",
    }
    if (
        any(os.environ.get(key) != value for key, value in required.items())
        or platform.system() != "Darwin"
        or platform.machine() != "x86_64"
        or os.geteuid() == 0
    ):
        raise ValueError("Use the explicit fresh public Intel UI check")
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    parent = repo / ".native-mac"
    parent.mkdir(mode=0o700)  # Never adopt an uncertain prior fixture.
    root = parent / "ui-acceptance"
    root.mkdir(mode=0o700)
    binary = root / "ai-station-native"
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "clang",
            "-fobjc-arc",
            "-fmodules",
            "-framework",
            "Cocoa",
            "-framework",
            "UniformTypeIdentifiers",
            "-arch",
            "x86_64",
            "-mmacosx-version-min=13.3",
            "-Werror=implicit-function-declaration",
            "-Werror=return-type",
            str(repo / "packaging/macos/native.m"),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=120,
    )
    contents = root / "Helper.app/Contents"
    helper = contents / "Resources/bin/ai-station-native"
    helper.parent.mkdir(parents=True, mode=0o700)
    (contents / "MacOS").mkdir(mode=0o700)
    shutil.copy2(binary, helper)
    shutil.copy2(binary, contents / "MacOS/Helper")
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "Helper",
                "CFBundleIdentifier": "org.ai-station.qa.NestedHelper",
                "CFBundleName": "AI Station QA",
                "CFBundlePackageType": "APPL",
                "NSPrincipalClass": "NSApplication",
            }
        )
    )
    env = {
        "PATH": os.defpath,
        **{
            key: os.environ[key]
            for key in ("HOME", "TMPDIR", "LANG", "__CF_USER_TEXT_ENCODING")
            if key in os.environ
        },
    }
    with (
        (root / "helper.reply.private.json").open("xb") as reply,
        (root / "helper.stderr.private.log").open("xb") as errors,
    ):
        child = subprocess.Popen(
            [str(helper), "--native-admin-recovery"], env=env, stdout=reply, stderr=errors
        )
        try:
            (root / "helper-process.json").write_text(json.dumps({"pid": child.pid}))
            subprocess.run(
                [
                    "/usr/bin/xcodebuild",
                    "test",
                    "-project",
                    str(repo / "packaging/macos/acceptance/NativeAcceptance.xcodeproj"),
                    "-scheme",
                    "NativeAcceptance",
                    "-configuration",
                    "Debug",
                    "-destination",
                    "platform=macOS",
                    "-parallel-testing-enabled",
                    "NO",
                    "-derivedDataPath",
                    str(root / "build"),
                    "-resultBundlePath",
                    str(root / "result.xcresult"),
                    "CODE_SIGN_IDENTITY=-",
                ],
                check=True,
                timeout=300,
            )
            if child.wait(timeout=10) != 0:
                raise RuntimeError("The owned native helper did not exit cleanly")
        finally:
            if child.poll() is None:
                child.terminate()  # Immediate, unreaped child only.
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
    if json.loads((root / "helper.reply.private.json").read_text()) != {"action": "cancel"}:
        raise ValueError("The system UI did not cancel the exact owned helper")


if __name__ == "__main__":
    main()
