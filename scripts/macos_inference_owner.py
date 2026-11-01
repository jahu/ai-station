"""Fixed developer-only subprocess entry for a private native model handoff."""

import os
import platform
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "host-runner"), str(ROOT / "scripts")]


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--run-native-inference":
        return 2
    if platform.system() != "Darwin" or os.geteuid() == 0:
        return 1  # Refuse before importing modules with native storage initialization.

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        from macos_inference_probe import owner

        owner(Path(sys.argv[2]))
    except BaseException:
        return 1  # Never print raw native errors, paths or replies.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
