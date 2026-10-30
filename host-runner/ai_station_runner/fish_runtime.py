"""Optional offline speech runtime behind existing owned processes and scopes."""

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.fish_contract import (
    CODEC_VRAM_MIB,
    DIRECTIONS,
    PRIMARY_VRAM_MIB,
    PROFILE,
    RAM_MIB,
    installation_observation,
    installation_signature,
    reference_bytes,
)
from ai_station_runner.memory_scope import available as scope_available
from ai_station_runner.memory_scope import scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child
from ai_station_runner.telemetry import collect

_reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fish-observation")
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
    if not settings.fish_speech_enabled:
        raise ValueError("Expressive speech is not enabled")
    if not all((settings.fish_speech_python, settings.fish_speech_dir, settings.fish_speech_models)):
        raise ValueError("Configure the offline Fish Python, source and model directory")
    python = Path(settings.fish_speech_python).expanduser().absolute()
    runtime = Path(settings.fish_speech_dir).expanduser().absolute()
    models = Path(settings.fish_speech_models).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Configured Fish Python is unavailable")
    if any(path.resolve() != path or not path.is_dir() for path in (runtime, models)):
        raise ValueError("Use direct configured Fish source and model directories")
    if not scope_available():
        raise ValueError("Expressive speech requires an owned user memory scope")
    return python, runtime, models


def _observe(runtime, models, signature):
    observed = installation_observation(runtime, models)
    if installation_signature(runtime, models) != signature:
        raise ValueError("Fish files changed during verification")
    return observed


def capabilities():
    base = {
        "backend": "fish_s2_pro",
        "name": "Fish S2 Pro",
        "profile": PROFILE,
        "gpu_count": 2,
        "ram_mib": RAM_MIB,
        "primary_vram_mib": PRIMARY_VRAM_MIB,
        "codec_vram_mib": CODEC_VRAM_MIB,
        "max_text_characters": 1000,
        "directions": list(DIRECTIONS),
        "paces": ["natural", "slow", "fast"],
        "offline": True,
        "license_url": "https://huggingface.co/fishaudio/s2-pro/blob/1de9996b6be38b745688de084d87a5633f714e4e/LICENSE.md",
        "attribution": "Built with Fish Audio",
        "commercial_license_required": True,
    }
    try:
        _, runtime, models = installation()
        capacity = devices(get_settings().host_data_dir())
        if not any(
            primary != auxiliary and a >= PRIMARY_VRAM_MIB and b >= CODEC_VRAM_MIB
            for primary, a in capacity.items()
            for auxiliary, b in capacity.items()
        ):
            raise ValueError("This profile needs two CUDA GPUs: at least 10 GiB primary and 5 GiB codec VRAM")
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
                "reason": "Verifying installed speech files",
            }
        observation = future.result()
        return {**base, "available": True, "readiness": "ready", "observation": observation}
    except (OSError, ValueError) as exc:
        return {**base, "available": False, "readiness": "unavailable", "reason": str(exc)}


def start(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise PermissionError("Speech requires artifact read/write permissions")
    python, runtime, models = installation()
    root = manager.data_dir.resolve()
    run_id = str(body.run_id)
    launch = resolve_child(root, f"runs/{run_id}/fish-launch")
    if launch != root / f"runs/{run_id}/fish-launch":
        raise ValueError("Speech launch must not contain symlinks")
    record = {
        "request": body.model_dump(mode="json"),
        "runtime": str(runtime),
        "models": str(models),
        "python": str(python),
    }
    receipt = launch / "request.json"
    if launch.exists():
        if receipt.resolve() != receipt or not receipt.is_file() or json.loads(receipt.read_text()) != record:
            raise ValueError("Speech launch identity changed; inspect existing work")
        try:
            owned = manager.inspect(run_id)
        except ProcessNotOwned as exc:
            raise ValueError("Inspect existing speech launch before retrying") from exc
        if owned.get("executor") != "fish_speech":
            raise ValueError("Run belongs to another executor")
        return owned
    try:
        manager.inspect(run_id)
    except ProcessNotOwned:
        pass
    else:
        raise ValueError("Run already owns a process")
    if body.deadline_at <= time.time():
        raise ValueError("Speech execution deadline elapsed")
    free = devices(root, free=True)
    if free.get(body.gpus[0], 0) < PRIMARY_VRAM_MIB or free.get(body.gpus[1], 0) < CODEC_VRAM_MIB:
        raise ValueError("Allocated speech GPUs lack the required free VRAM")
    reference_bytes(root, body.reference.model_dump())
    output = resolve_child(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav")
    if output.exists() or output.is_symlink():
        raise ValueError("Inspect existing speech output instead of overwriting")
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
        "CUDA_VISIBLE_DEVICES": ",".join(map(str, body.gpus)),
        "PYTHONPATH": str(Path(__file__).parent.parent) + os.pathsep + str(runtime),
        "PYTHONUNBUFFERED": "1",
    }
    # Hashing and all model work occur in the owned child after PID journaling.
    return manager.start(
        run_id=run_id,
        executor="fish_speech",
        cwd=root,
        argv=scope_prefix(run_id, RAM_MIB) + [str(python), "-m", "ai_station_runner.fish_job", str(receipt)],
        env=environment,
        deadline_at=body.deadline_at,
    )
