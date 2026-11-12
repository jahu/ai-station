"""Observed external GPU occupancy supplements owned resource locks."""

import math
from datetime import timedelta

from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.models import RuntimeInstance
from app.resources import RESOURCE_WAIT_KEY, memory_observation
from app.task_control import lock_task


def estimated_gpu_mib(session, run):
    """Use verified Q8 geometry; retain conservative admission for unknown layouts."""
    p = run.parameters
    if p.get("cache_type") != "q8_0" or p.get("model_bundle") or not p.get("gpus"):
        return None
    instance = session.get(RuntimeInstance, p.get("instance_id"))
    profile = (instance.metadata_json if instance else {}).get("context_profile") or {}
    values = [p.get("size_bytes"), p.get("context_size"), profile.get("q8_kv_bytes_per_token")]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
        return None
    state = profile.get("state_reserve_mib", 0)
    projector = (p.get("projector") or {}).get("size_bytes", 0)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (state, projector)):
        return None
    from app.llama import _CUDA_OVERHEAD_MIB_PER_GPU

    weights, context, kv = values
    return ((weights + projector + context * kv) / 1024**2 + state) / len(
        p["gpus"]
    ) + _CUDA_OVERHEAD_MIB_PER_GPU


def memory_available(session, run, hardware):
    selected = set(run.parameters["gpus"])
    required = estimated_gpu_mib(session, run)
    blocked = []
    for gpu in (hardware or {}).get("gpus", []):
        if gpu.get("index") not in selected:
            continue
        total, free = gpu.get("memory_total_mib"), gpu.get("memory_free_mib")
        used = gpu.get("memory_used_mib")
        if free is None and type(total) in {int, float} and type(used) in {int, float}:
            free = total - used
        if not (
            type(total) in {int, float} and type(free) in {int, float} and total > 0 and 0 <= free <= total
        ):
            continue  # Older runners expose indices only; native readiness remains authoritative.
        # Compare the fitted model's weights, KV, state and CUDA workspace to
        # actual free VRAM. Normal desktop occupancy must not block a model that
        # fits. Unknown layouts retain the legacy conservative threshold.
        if free < (required if required is not None else total * 0.9):
            blocked.append(
                {
                    "index": gpu["index"],
                    "free_mib": free,
                    "total_mib": total,
                    **({"required_mib": required} if required is not None else {}),
                }
            )
    if not blocked:
        return True
    now = utcnow()
    wait = {
        "reason": "gpu",
        "checked_at": now.isoformat(),
        "gpu_memory": blocked,
        **memory_observation(session, run, ((hardware or {}).get("memory") or {}).get("available_mib"), 0),
    }
    run.metadata_json = {**run.metadata_json, "resource_wait": wait}
    lock_task(session, run.task)
    until = now + timedelta(seconds=max(2, get_settings().heartbeat_seconds * 2))
    run.task.metadata_json = {**run.task.metadata_json, RESOURCE_WAIT_KEY: until.isoformat()}
    append_event(session, run.id, "resource.waiting", wait)
    return False
