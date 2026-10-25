#!/usr/bin/env python3
"""Explicit checksum-pinned project-local Tailscale installation, without OS changes."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host-runner"))
from ai_station_runner.tailnet_install import install  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args()
    print(install(args.prefix))
