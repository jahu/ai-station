"""Explain model feasibility without confusing a file, runtime and workload."""

import math

from app.model_setup import recommendation
from app.setup_models import CANDIDATES


def number(value):
    return value if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def assess_file(file, hardware, storage, *, candidates=None):
    """Only exact reviewed identities inherit a workload's memory estimate.

    Unknown checkpoint formats/architectures have unknown residency, KV geometry
    and companion requirements. Their byte size is only a disk lower bound.
    """
    size = file.get("size_bytes")
    size = size if type(size) is int and 0 < size <= 256 * 1024**3 else None
    free = number((storage or {}).get("free_bytes"))
    headroom = number((storage or {}).get("headroom_bytes"))
    disk = (
        "unknown"
        if size is None or free is None or headroom is None
        else "insufficient"
        if free < size + headroom
        else "file_fits"
    )
    matches = [
        entry
        for entry in (CANDIDATES if candidates is None else candidates)
        if file.get("identity_available")
        and entry.file.sha256 == file.get("sha256")
        and entry.file.size_bytes == size
    ]
    plans = []
    from app.native_models import host_profile, native

    mac = (hardware.get("host") or {}).get("system") == "Darwin"
    for entry in matches:
        is_native = native(entry.model_dump())
        if is_native and entry.runtime_profile != host_profile(hardware) or mac and not is_native:
            continue
        planned = recommendation(entry, hardware)
        selected = planned.get("gpus", [])
        current = {g.get("index"): g for g in hardware.get("gpus", []) if isinstance(g, dict)}
        # Capacity is distinct from present occupation. Do not sum arbitrary
        # devices here: the existing llama.cpp fitter chose the sharded group.
        observations = [current.get(index, {}) for index in selected]
        used = [number(g.get("memory_used_mib")) for g in observations]
        occupancy = (
            (
                "unknown"
                if any(value is None for value in used)
                else "in_use"
                if any(value > 256 for value in used)
                else "low_usage"
            )
            if selected
            else "not_applicable"
        )
        plans.append(
            {
                "catalog_id": entry.id,
                "name": entry.name,
                "capability": entry.capability,
                "runtime": entry.runtime,
                "fit": "estimated_fit" if planned["fits"] else "not_recommended",
                "occupancy": occupancy,
                "recommendation": planned,
                "locally_qualified": False,
                "provenance": "pinned_publisher_configuration"
                if getattr(entry, "origin", None) == "hub"
                else "reviewed_recipe_exact_object",
            }
        )
    return {
        "disk": {
            "status": disk,
            "file_bytes": size,
            "free_bytes": free,
            "headroom_bytes": headroom,
            "complete_install_budget_known": False,
            "note": "File size is a minimum; runtime, companions and staging may need more space.",
        },
        "runtime_status": "supported_architecture_plan"
        if plans and any(getattr(entry, "origin", None) == "hub" for entry in matches)
        else "reviewed_profile"
        if plans
        else "needs_compatible_recipe",
        "hardware_status": "estimated_fit"
        if any(p["fit"] == "estimated_fit" for p in plans)
        else "not_recommended"
        if plans
        else "unknown",
        "profiles": plans,
        "reason": "Supported architecture; memory is estimated from pinned publisher configuration and verified natively after download."
        if plans and any(getattr(entry, "origin", None) == "hub" for entry in matches)
        else "Review the matching recipe and hardware profile before installing."
        if plans
        else "No validated workload profile for this object yet. File size alone cannot establish VRAM fit.",
        "automatic_ram_offload": False,
        "automatic_cloud_fallback": False,
    }
