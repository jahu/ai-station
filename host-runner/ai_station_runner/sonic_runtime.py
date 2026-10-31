"""Configured native whole-avatar capability; disabled until explicitly enabled.

Keep legacy Echo discovery separate: readiness of Sonic must never make an
unconfigured Echo executor appear operational, or change an old request's model.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
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

_hash_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avatar-observation")
_hash_lock = threading.Lock()
_readiness = {}


class ObservationPending(ValueError):
    pass


def installation(identity=None):
    settings = get_settings()
    from ai_station_runner.avatar_selection import selection

    chosen = selection(settings, identity) or {}
    if identity is not None and not chosen.get("managed"):
        raise ValueError("The exact managed avatar environment is no longer selected")
    if not settings.sonic_whole_enabled and not chosen.get("managed"):
        raise ValueError("Whole-recording avatar integration is not enabled")
    if not all(chosen.get(k) for k in ("sonic_python", "sonic_dir", "sonic_models")):
        raise ValueError("Configure the offline Sonic Python, installation and model directory")
    python = chosen["sonic_python"].absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured Sonic Python is unavailable")
    if not scope_available():
        raise ValueError("Whole-recording avatars require owned user memory scopes")
    return (
        python,
        chosen["sonic_dir"].resolve(),
        chosen["sonic_models"].resolve(),
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


def ready_recipe(runtime, models):
    """Bounded, read-only discovery; hashing never blocks an HTTP handler.

    This imports no models and starts no execution. A single metadata reader
    uses a fixed-size hash buffer; changed installations remain unavailable
    until their complete observed bytes have been checked.
    """
    signature = _signature(runtime, models)
    key = (runtime, models, signature)
    with _hash_lock:
        future = _readiness.get(key)
        if future is None:
            for previous, job in list(_readiness.items()):
                if job.done() and len(_readiness) >= 4:
                    del _readiness[previous]
            if len(_readiness) >= 4:
                raise ObservationPending("Verifying changed avatar installations; retry shortly")
            future = _hash_workers.submit(_observed, runtime, models, signature)
            _readiness[key] = future
    if not future.done():
        raise ObservationPending(
            "Verifying installed avatar files; this initial check runs in the background"
        )
    value = {"id": PROFILE, "observation": future.result()}
    from ai_station_runner.avatar_environment import environment_id, read_json, resolve
    from ai_station_runner.avatar_selection import selection

    chosen = selection(get_settings()) or {}
    if chosen.get("managed"):
        ready = read_json(models.parent / "ready.json")
        observed = {k: ready[k] for k in ("profile", "manifest_sha256", "operation_id")}
        selected = resolve(get_settings().host_data_dir(), observed)
        if selected["sonic_models"] != models or selected["sonic_dir"] != runtime:
            raise ValueError("The observed avatar environment changed")
        value["environment_id"] = environment_id(observed)
    return value


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
    from ai_station_runner.avatar_selection import selection

    chosen = selection(get_settings()) or {}
    managed = chosen.get("managed") is True
    if not get_settings().sonic_whole_enabled and not managed:
        return {
            **base,
            "available": False,
            "readiness": "disabled",
            "reason": "Whole-recording avatar integration is not enabled",
        }
    try:
        _, runtime, models = installation()
        recipe = ready_recipe(runtime, models)
        if managed and not recipe.get("environment_id"):
            raise ValueError("Managed avatar readiness requires its frozen environment identity")
        gpus = collect(get_settings().host_data_dir()).get("gpus", [])
        if managed:
            from ai_station_runner.avatar_prepare import driver_supported

            gpus = [g for g in gpus if (g.get("memory_total_mib") or 0) >= 12288]
            if not driver_supported("580.126.20"):
                raise ValueError("The managed avatar driver is incompatible; inspect Diagnostics")
        if not gpus:
            raise ValueError("No CUDA GPU is detected for whole-recording avatars")
        return {
            **base,
            "available": True,
            "readiness": "ready",
            "recipe": recipe,
            "detected_gpu_count": len(gpus),
            "configuration_source": "managed" if managed else "configured",
            **({"eligible_gpu_indices": [int(g["index"]) for g in gpus]} if managed else {}),
        }
    except ObservationPending as exc:
        return {**base, "available": False, "readiness": "checking", "reason": str(exc)}
    except (OSError, ValueError) as exc:
        return {
            **base,
            "available": False,
            "readiness": "unavailable",
            "reason": "The installed avatar files changed or are unavailable; inspect model setup"
            if managed
            else str(exc),
        }


def start_whole_avatar(manager, body):
    from ai_station_runner.sonic_jobs import _start_owned

    try:
        identity = body.recipe.get("environment_id")
        if identity is None:
            from ai_station_runner.avatar_selection import selection

            if (selection(get_settings()) or {}).get("managed"):
                raise ValueError("Managed avatars require their frozen environment identity")
        python, runtime, models = installation(identity) if identity is not None else installation()
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    # Readiness's cached observation never substitutes for launch/native checks.
    return _start_owned(
        manager,
        body,
        python=python,
        runtime=runtime,
        models=models,
        hardware=collect(manager.data_dir),
        # The owned child verifies the full snapshot BEFORE importing models.
        # Do not hash gigabytes before journaling PID/deadline: an HTTP timeout
        # could otherwise hide a later accepted launch from worker recovery.
        verify_installation=False,
    )
