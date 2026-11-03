#!/usr/lib/ai-station/python/bin/python3 -IBS
"""OS-authenticated fixed prerequisite action. Never import user/application code."""

import os
import stat
import sys
from pathlib import Path

APP = Path("/usr/lib/ai-station")


def main():
    if len(sys.argv) != 1 or os.getuid() != 0 or os.geteuid() != 0:
        raise SystemExit("Use the operating-system authentication dialog")
    for path in (APP, *APP.parents, APP / "scripts"):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit("Install the root-owned AI Station package")
    for name in ("linux_gpu_install.py", "windows_gpu_install.py", "windows_gpu_bundle.py"):
        info = (APP / "scripts" / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit("The fixed graphics preparation code changed")
    sys.path.insert(0, str(APP / "scripts"))
    from linux_gpu_install import main as prepare

    prepare()


if __name__ == "__main__":
    main()
