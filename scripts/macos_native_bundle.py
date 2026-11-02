"""Pure packaging of the native presentation helper, shared with system UI QA."""

import plistlib
import shutil
from pathlib import Path

BUNDLE_ID = "io.ai-station.presentation"
BUNDLE = "bin/AI Station Helper.app"
EXECUTABLE = BUNDLE + "/Contents/MacOS/ai-station-native"
INFO = BUNDLE + "/Contents/Info.plist"


def create(root, binary, *, version="0.1.0", minimum_os="13.3"):
    root, binary = Path(root), Path(binary)
    bundle = root / BUNDLE
    bundle.mkdir(parents=True, mode=0o700)  # Never adopt an existing helper.
    contents = bundle / "Contents"
    (contents / "MacOS").mkdir(parents=True, mode=0o700)
    shutil.copy2(binary, root / EXECUTABLE)
    (root / INFO).write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "ai-station-native",
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleName": "AI Station",
                "CFBundleDisplayName": "AI Station",
                "CFBundlePackageType": "APPL",
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleVersion": version,
                "CFBundleShortVersionString": version,
                "LSMinimumSystemVersion": minimum_os,
                "LSUIElement": True,
                "NSPrincipalClass": "NSApplication",
                "NSHighResolutionCapable": True,
            }
        )
    )
    return root / EXECUTABLE
