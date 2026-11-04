"""Resolve configured speech first, then the explicitly activated owned runtime."""

import os
import stat
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from ai_station_runner import runtime_install, speech_environment, speech_prepare
from ai_station_runner.security import resolve_child


def selection(settings):
    values = [settings.chatterbox_python, settings.chatterbox_script, settings.chatterbox_cache]
    if any(values):
        return {
            "python": Path(values[0]).expanduser() if values[0] else None,
            "script": Path(values[1]).expanduser() if values[1] else None,
            "cache": Path(values[2]).expanduser() if values[2] else None,
            "managed": False,
            "environment": None,
        }
    if not speech_prepare.QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        active_path = root / "runtime/speech/active.json"
        if resolve_child(root, "runtime/speech/active.json") != active_path:
            return None
        active = runtime_install.load_json(active_path)
        if not active or active.get("profile") != speech_environment.PROFILE:
            return None
        frozen = speech_environment.recipe()
        fingerprint = speech_environment.fingerprint(frozen)
        identity = str(UUID(active["operation_id"]))
        if identity != active["operation_id"] or active.get("manifest_sha256") != fingerprint:
            return None
        relative = f"runtime/speech/{fingerprint}/{identity}"
        folder = root / relative
        if resolve_child(root, relative + "/ready.json") != folder / "ready.json":
            return None
        ready = runtime_install.load_json(folder / "ready.json")
        if not ready or not all(
            ready.get(key) == value
            for key, value in {
                "profile": speech_environment.PROFILE,
                "operation_id": identity,
                "manifest_sha256": fingerprint,
                "environment_prepared": True,
                "relative_path": relative,
            }.items()
        ):
            return None
        python = folder / "venv/bin/python"
        binary = folder / "python/bin/python3.12"
        if (
            not binary.is_file()
            or binary.is_symlink()
            or python.resolve() != binary
            or not os.access(binary, os.X_OK)
        ):
            return None
        for item in (v for v in frozen["inputs"] if v["kind"] == "model"):
            target = root / "models/store" / item["sha256"]
            if (folder / "models" / item["filename"]).resolve() != target:
                return None
            info = target.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o222
                or info.st_nlink != 1
                or info.st_size != item["size_bytes"]
            ):
                return None
        return {
            "python": python,
            "script": Path(__file__).with_name("managed_speech_job.py"),
            "cache": folder / "cache",
            "managed": True,
            "environment": folder,
        }
    except (OSError, ValueError, KeyError, TypeError, HTTPException):
        return None
