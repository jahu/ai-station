"""Optional offline effects runtime behind existing owned processes and scopes."""

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.effects_contract import (
    PROFILE,
    RAM_MIB,
    VRAM_MIB,
    installation_observation,
    installation_signature,
    video_path,
)
from ai_station_runner.memory_scope import available as scope_available
from ai_station_runner.memory_scope import scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child
from ai_station_runner.telemetry import collect

_reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="effects-observation")
_lock = threading.Lock()
_checks = {}


def devices(root, *, free=False):
    result = {}
    for gpu in collect(root).get("gpus", []):
        total, used = gpu.get("memory_total_mib"), gpu.get("memory_used_mib")
        values = (total, used) if free else (total,)
        if all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values):
            result[int(gpu["index"])] = max(0, total - used) if free else total
    return result


def installation(identity=None):
    settings = get_settings()
    from ai_station_runner.effects_selection import selection

    chosen = selection(settings, identity) or {}
    if identity is not None and not chosen.get("managed"):
        raise ValueError("The exact managed sound environment is no longer selected")
    if not settings.mmaudio_enabled and not chosen.get("managed"):
        raise ValueError("Sound effects is not enabled")
    if not all(chosen.get(k) for k in ("mmaudio_python", "mmaudio_dir", "mmaudio_models")):
        raise ValueError("Configure the offline MMAudio Python, source and model directory")
    python = chosen["mmaudio_python"].absolute()
    runtime = chosen["mmaudio_dir"].absolute()
    models = chosen["mmaudio_models"].absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured MMAudio Python is unavailable")
    if any(path.resolve() != path or not path.is_dir() for path in (runtime, models)):
        raise ValueError("Use direct configured MMAudio source and model directories")
    if not scope_available():
        raise ValueError("Sound effects requires an owned user memory scope")
    return python, runtime, models


def _observe(runtime, models, signature):
    observed = installation_observation(runtime, models)
    if installation_signature(runtime, models) != signature:
        raise ValueError("MMAudio files changed during verification")
    return observed


def capabilities():
    base = {
        "backend": "mmaudio",
        "name": "MMAudio · Sound effects",
        "model": "large_44k_v2",
        "model_revision": "eb13a1a98fdbec91753775c57b074ccdfc60587c",
        "source_revision": "974010a026c731054592d8f777218bd9d85a6c24",
        "profile": PROFILE,
        "ram_mib": RAM_MIB,
        "vram_mib": VRAM_MIB,
        "max_seconds": 300,
        "offline": True,
        "license_url": "https://huggingface.co/hkchengrex/MMAudio",
        "commercial_license_required": True,
    }
    from ai_station_runner.effects_selection import selection

    chosen = selection(get_settings()) or {}
    managed = chosen.get("managed") is True
    try:
        _, runtime, models = installation()
        if not any(v >= VRAM_MIB for v in devices(get_settings().host_data_dir()).values()):
            raise ValueError("Sound effects requires a CUDA GPU with at least 8 GiB VRAM")
        signature = installation_signature(runtime, models)
        key = (runtime, models, signature)
        with _lock:
            future = _checks.get(key)
            if future is None:
                for previous, value in list(_checks.items()):
                    if value.done():
                        del _checks[previous]
                if len(_checks) >= 4:
                    return {**base, "available": False, "readiness": "checking"}
                future = _reader.submit(_observe, runtime, models, signature)
                _checks[key] = future
        if not future.done():
            return {
                **base,
                "available": False,
                "readiness": "checking",
                "reason": "Verifying installed sound model",
            }
        extra = {}
        if managed:
            from ai_station_runner.effects_environment import environment_id, read_json, resolve
            from ai_station_runner.effects_prepare import compatible_devices, driver_supported

            ready = read_json(models.parent / "ready.json")
            observed = {k: ready[k] for k in ("profile", "manifest_sha256", "operation_id")}
            selected = resolve(get_settings().host_data_dir(), observed)
            if selected["mmaudio_models"] != models or selected["mmaudio_dir"] != runtime:
                raise ValueError("The observed sound environment changed")
            eligible = compatible_devices(collect(get_settings().host_data_dir()).get("gpus", []))
            if not eligible or not driver_supported("580.126.20"):
                raise ValueError("The installed sound profile needs compatible BF16 GPUs and driver")
            extra = {
                "environment_id": environment_id(observed),
                "eligible_gpu_indices": [int(g["index"]) for g in eligible],
            }
        return {
            **base,
            **extra,
            "available": True,
            "readiness": "ready",
            "configuration_source": "managed" if managed else "configured",
            "observation": future.result(),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            **base,
            "available": False,
            "readiness": "unavailable",
            "reason": "The installed sound files changed or are unavailable; inspect model setup"
            if managed
            else str(exc),
        }


def start(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise PermissionError("Effects requires artifact read/write permissions")
    from ai_station_runner.effects_selection import selection

    if body.environment_id is None and (selection(get_settings()) or {}).get("managed"):
        raise ValueError("Managed sound requires its frozen environment identity")
    python, runtime, models = installation(body.environment_id) if body.environment_id else installation()
    root = manager.data_dir.resolve()
    managed = None
    if body.environment_id:
        from ai_station_runner.effects_environment import resolve_id

        managed = resolve_id(root, body.environment_id)
        if (python, runtime, models) != tuple(
            managed[k] for k in ("mmaudio_python", "mmaudio_dir", "mmaudio_models")
        ):
            raise ValueError("Sound launch must use its exact frozen environment")
    run_id = str(body.run_id)
    launch = resolve_child(root, f"runs/{run_id}/effects-launch")
    if launch != root / f"runs/{run_id}/effects-launch":
        raise ValueError("Effects launch must not contain symlinks")
    record = {
        "request": body.model_dump(mode="json"),
        "runtime": str(runtime),
        "models": str(models),
        "python": str(python),
    }
    receipt = launch / "request.json"
    if launch.exists():
        if receipt.resolve() != receipt or not receipt.is_file() or json.loads(receipt.read_text()) != record:
            raise ValueError("Effects launch identity changed; inspect existing work")
        try:
            owned = manager.inspect(run_id)
        except ProcessNotOwned as exc:
            raise ValueError("Inspect existing effects launch before retrying") from exc
        if owned.get("executor") != "mmaudio_effects":
            raise ValueError("Run belongs to another executor")
        return owned
    try:
        manager.inspect(run_id)
    except ProcessNotOwned:
        pass
    else:
        raise ValueError("Run already owns a process")
    if body.deadline_at <= time.time():
        raise ValueError("Effects execution deadline elapsed")
    free = devices(root, free=True)
    if free.get(body.gpu, 0) < VRAM_MIB:
        raise ValueError("Allocated effects GPUs lack the required free VRAM")
    if managed:
        from ai_station_runner.effects_prepare import compatible_devices, driver_supported

        if not driver_supported("580.126.20") or body.gpu not in {
            int(g["index"]) for g in compatible_devices(collect(root).get("gpus", []))
        }:
            raise ValueError("The allocated sound GPU or driver does not fit its prepared profile")
    video_path(root, body.video, verify=False)
    output = resolve_child(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav")
    if output.exists() or output.is_symlink():
        raise ValueError("Inspect existing effects output instead of overwriting")
    launch.mkdir(mode=0o700, parents=True)
    with receipt.open("x") as handle:
        os.chmod(receipt, 0o600)
        json.dump(record, handle, ensure_ascii=False)
    environment = {
        **os.environ,
        **scope_environment(),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "CUDA_VISIBLE_DEVICES": str(body.gpu),
        "PYTHONPATH": str(Path(__file__).parent.parent) + os.pathsep + str(runtime),
        "PYTHONUNBUFFERED": "1",
    }
    if managed:
        home = launch / "home"
        home.mkdir(mode=0o700)
        environment = {
            **scope_environment(),
            **{
                k: environment[k]
                for k in (
                    "HF_HUB_OFFLINE",
                    "TRANSFORMERS_OFFLINE",
                    "HF_HUB_DISABLE_TELEMETRY",
                    "CUDA_VISIBLE_DEVICES",
                    "PYTHONPATH",
                    "PYTHONUNBUFFERED",
                )
            },
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    # Hashing and all model work occur in the owned child after PID journaling.
    return manager.start(
        run_id=run_id,
        executor="mmaudio_effects",
        cwd=root,
        argv=scope_prefix(run_id, RAM_MIB)
        + [str(python), "-m", "ai_station_runner.effects_job", str(receipt)],
        env=environment,
        deadline_at=body.deadline_at,
    )
