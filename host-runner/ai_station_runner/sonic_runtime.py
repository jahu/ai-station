"""Configured native whole-avatar capability; disabled until explicitly enabled.

Keep legacy Echo discovery separate: readiness of Sonic must never make an
unconfigured Echo executor appear operational, or change an old request's model.
"""

import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import available as scope_available
from ai_station_runner.sonic_contract import (
    IMPLEMENTATION_FILES,
    MODEL_FILES,
    PROFILE,
    direct_file,
    installation_observation,
)
from ai_station_runner.telemetry import collect


def installation():
    settings = get_settings()
    if not settings.sonic_whole_enabled:
        raise ValueError("Whole-recording avatar integration is not enabled")
    if not all((settings.sonic_python, settings.sonic_dir, settings.sonic_models)):
        raise ValueError("Configure the offline Sonic Python, installation and model directory")
    python = Path(settings.sonic_python).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured Sonic Python is unavailable")
    if not scope_available():
        raise ValueError("Whole-recording avatars require owned user memory scopes")
    return (
        python,
        Path(settings.sonic_dir).expanduser().resolve(),
        Path(settings.sonic_models).expanduser().resolve(),
    )


def _signature(runtime, models):
    if any(path.is_symlink() for path in (runtime / "src").rglob("*")):
        raise ValueError("Sonic source must not import through symlinks")
    source = {"sonic.py", "config/inference/sonic.yaml"} | {
        path.relative_to(runtime).as_posix() for path in (runtime / "src").rglob("*.py")
    }
    files = [
        *(direct_file(runtime, name) for name in sorted(source)),
        *(direct_file(models, name) for name in MODEL_FILES),
        *(direct_file(Path(__file__).parent, name) for name in IMPLEMENTATION_FILES),
    ]
    result = []
    for path in files:
        stat = path.stat()
        result.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


@lru_cache(maxsize=4)
def _observed(runtime, models, signature):
    observation = installation_observation(runtime, models)
    if _signature(runtime, models) != signature:
        raise ValueError("Sonic installation changed during observation")
    return observation


def current_recipe(runtime, models):
    # Readiness polling does not repeatedly hash gigabytes of unchanged weights.
    # Native dispatch and entry independently rehash the actual complete files.
    signature = _signature(runtime, models)
    return {"id": PROFILE, "observation": _observed(runtime, models, signature)}


def capabilities():
    base = {
        "backend": "sonic",
        "generation": "whole_recording",
        "fps": 25,
        "max_audio_seconds": 60,
        "max_side": 768,
        "max_pixels": 512 * 768,
        "ram_mib": 18432,
        "gpu_counts": [1, 2],
        "offline": True,
    }
    try:
        _, runtime, models = installation()
        recipe = current_recipe(runtime, models)
        if not collect(get_settings().host_data_dir()).get("gpus"):
            raise ValueError("No CUDA GPU is detected for whole-recording avatars")
        return {**base, "available": True, "recipe": recipe}
    except (OSError, ValueError) as exc:
        return {**base, "available": False, "reason": str(exc)}


def start_whole_avatar(manager, body):
    from ai_station_runner.sonic_jobs import _start_owned

    try:
        python, runtime, models = installation()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    # Readiness's cached observation never substitutes for launch/native checks.
    return _start_owned(
        manager, body, python=python, runtime=runtime, models=models, hardware=collect(manager.data_dir)
    )
