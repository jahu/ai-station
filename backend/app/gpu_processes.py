"""Allowlisted process observations for live views and durable inspection reports."""

import math
from pathlib import PurePosixPath


def normalize(raw):
    if not isinstance(raw, dict) or raw.get("status") not in {"available", "partial"}:
        return {"status": "unavailable", "sampled_at": None, "processes": [], "truncated": False}
    rows, seen, partial = [], set(), raw["status"] == "partial"
    values = raw.get("processes", [])
    if not isinstance(values, list):
        return normalize(None)
    for item in values[:128]:
        if not isinstance(item, dict):
            partial = True
            continue
        uuid, pid = item.get("gpu_uuid"), item.get("pid")
        if (
            not isinstance(uuid, str)
            or not uuid.startswith(("GPU-", "MIG-"))
            or len(uuid) > 100
            or type(pid) is not int
            or not 0 < pid < 2**31
        ):
            partial = True
            continue
        if (uuid, pid) in seen:
            continue
        seen.add((uuid, pid))
        used = item.get("memory_used_mib")
        if type(used) not in {int, float} or not math.isfinite(used) or used < 0:
            used = None
        name = item.get("name")
        name = " ".join(PurePosixPath(name).name.split())[:160] if isinstance(name, str) else "Unknown"
        rows.append({"gpu_uuid": uuid, "pid": pid, "name": name or "Unknown", "memory_used_mib": used})
    at = raw.get("sampled_at")
    return {
        "status": "partial" if partial else "available",
        "sampled_at": at[:80] if isinstance(at, str) else None,
        "processes": rows,
        "truncated": raw.get("truncated") is True or len(values) > 128,
    }
