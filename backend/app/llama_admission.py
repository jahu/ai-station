"""Observed external GPU occupancy supplements owned resource locks."""

from datetime import timedelta

from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.resources import RESOURCE_WAIT_KEY
from app.task_control import lock_task


def memory_available(session, run, hardware):
    selected = set(run.parameters["gpus"])
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
        # A heavy new model receives exclusive GPU capacity, with room for normal
        # display/background allocations. This does not estimate a smaller context.
        if free < total * 0.9:
            blocked.append({"index": gpu["index"], "free_mib": free, "total_mib": total})
    if not blocked:
        return True
    now = utcnow()
    wait = {"reason": "gpu", "checked_at": now.isoformat(), "gpu_memory": blocked}
    run.metadata_json = {**run.metadata_json, "resource_wait": wait}
    lock_task(session, run.task)
    until = now + timedelta(seconds=max(2, get_settings().heartbeat_seconds * 2))
    run.task.metadata_json = {**run.task.metadata_json, RESOURCE_WAIT_KEY: until.isoformat()}
    append_event(session, run.id, "resource.waiting", wait)
    return False
