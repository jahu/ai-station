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


def installation():
    settings = get_settings()
    if not settings.mmaudio_enabled:
        raise ValueError("Sound effects is not enabled")
    if not all((settings.mmaudio_python, settings.mmaudio_dir, settings.mmaudio_models)):
        raise ValueError("Configure the offline MMAudio Python, source and model directory")
    python = Path(settings.mmaudio_python).expanduser().absolute()
    runtime = Path(settings.mmaudio_dir).expanduser().absolute()
    models = Path(settings.mmaudio_models).expanduser().absolute()
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
        return {**base, "available": True, "readiness": "ready", "observation": future.result()}
    except (OSError, ValueError) as exc:
        return {**base, "available": False, "readiness": "unavailable", "reason": str(exc)}


def start(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise PermissionError("Effects requires artifact read/write permissions")
    python, runtime, models = installation()
    root = manager.data_dir.resolve()
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
