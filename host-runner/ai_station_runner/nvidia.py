"""Locate NVIDIA's read-only CLI without enabling Windows executable interop."""

import os
import shutil
from pathlib import Path

WSL_NVIDIA_SMI = Path("/usr/lib/wsl/lib/nvidia-smi")


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False
    return "microsoft" in release


def executable() -> str:
    # Retain ordinary PATH lookup on Linux, including an existing installation
    # in WSL. Never search Windows drives or invoke a Windows executable.
    if not shutil.which("nvidia-smi") and is_wsl():
        if WSL_NVIDIA_SMI.is_file() and os.access(WSL_NVIDIA_SMI, os.X_OK):
            return str(WSL_NVIDIA_SMI)
    return "nvidia-smi"
