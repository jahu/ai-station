"""Explain model feasibility without confusing a file, runtime and workload."""

import math

from app.hub_model_parts import looks_split
from app.model_setup import recommendation
from app.setup_models import CANDIDATES


def number(value):
    return value if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def assess_file(file, hardware, storage, *, candidates=None, bundle=None):
    """Only exact recipes or pinned supported configurations supply an estimate.

    Unknown checkpoint formats/architectures have unknown residency, KV geometry
    and companion requirements. Their byte size is only a disk lower bound.
    """
    size = file.get("size_bytes")
    size = size if type(size) is int and 0 < size <= 256 * 1024**3 else None
    free = number((storage or {}).get("free_bytes"))
    headroom = number((storage or {}).get("headroom_bytes"))
    split_candidates = [
        entry
        for entry in (candidates or ())
        if getattr(entry, "origin", None) == "hub_split"
        and file.get("identity_available") is True
        and any(
            part.filename == file.get("filename")
            and part.file.sha256 == file.get("sha256")
            and part.file.size_bytes == size
            for part in entry.parts
        )
    ]
    if len(split_candidates) == 1:
        from app.hub_split_candidates import assessment

        return assessment(split_candidates[0], hardware, storage, selected_size=size)
    disk = (
        "unknown"
        if size is None or free is None or headroom is None
        else "insufficient"
        if free < size + headroom
        else "file_fits"
    )
    if bundle is not None or looks_split(file.get("filename", "")):
        total = (
            bundle.get("total_size_bytes") if bundle and bundle.get("status") == "complete_metadata" else None
        )
        return {
            "disk": {
                "status": "unknown"
                if total is None or free is None or headroom is None
                else "file_fits"
                if free >= total + headroom
                else "insufficient",
                "file_bytes": size,
                "model_bundle_bytes": total,
                "free_bytes": free,
                "headroom_bytes": headroom,
                "complete_install_budget_known": False,
                "note": "All declared model parts are required. Runtime, context and staging requirements remain separate.",
            },
            "runtime_status": "needs_complete_bundle_runtime",
            "hardware_status": "unknown",
            "profiles": [],
            "reason": "This split model needs a complete compatible bundle plan. A fragment cannot be installed or used as the whole model.",
            "automatic_ram_offload": False,
            "automatic_cloud_fallback": False,
        }
    matches = [
        entry
        for entry in (CANDIDATES if candidates is None else candidates)
        if file.get("identity_available")
        and entry.file.sha256 == file.get("sha256")
        and entry.file.size_bytes == size
    ]
    embedding = [entry for entry in matches if getattr(entry, "origin", None) == "hub_embedding"]
    if embedding:
        from app.hub_embedding_candidates import assessment

        return assessment(embedding[0], hardware, storage)
    images = [
        v
        for v in matches
        if getattr(v, "origin", None) in {"hub_image", "hub_video", "hub_speech", "hub_music", "hub_avatar"}
    ]
    if images:
        entry = images[0]
        prerequisites = entry.prerequisite_budget_bytes
        if prerequisites is None:
            prerequisites = (
                sum(v["size_bytes"] for v in entry.setup_recipe["inputs"])
                + max(entry.setup_recipe.get("minimum_free_bytes", 0), entry.setup_recipe["download_bytes"])
                if entry.prepare_engine
                else 0
            )
        budget = size + prerequisites
        disk = (
            "unknown"
            if free is None or headroom is None
            else "file_fits"
            if free >= budget + headroom
            else "insufficient"
        )
    plans = []
    from app.native_models import host_profile, native

    mac = (hardware.get("host") or {}).get("system") == "Darwin"
    for entry in matches:
        is_native = native(entry.model_dump())
        if is_native and entry.runtime_profile != host_profile(hardware) or mac and not is_native:
            continue
        planned = recommendation(entry, hardware)
        ram = number((hardware.get("memory") or {}).get("total_mib"))
        capacity_known = ram is not None and ram > 0
        if not entry.runtime_profile:
            capacity_known = (
                capacity_known
                and isinstance(hardware.get("gpus"), list)
                and all(
                    isinstance(gpu, dict)
                    and number(gpu.get("memory_total_mib")) is not None
                    and gpu["memory_total_mib"] > 0
                    for gpu in hardware.get("gpus", [])
                )
            )
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
                "quantization": entry.quantization,
                "capability": entry.capability,
                "runtime": entry.runtime,
                "fit": "estimated_fit"
                if planned["fits"]
                else "not_recommended"
                if capacity_known
                else "unknown",
                "occupancy": occupancy,
                "recommendation": planned,
                "locally_qualified": False,
                "provenance": "pinned_avatar_recipe_and_tensor_metadata"
                if getattr(entry, "origin", None) == "hub_avatar"
                else "pinned_music_recipe_and_checkpoint_header"
                if getattr(entry, "origin", None) == "hub_music"
                else "pinned_speech_recipe_and_checkpoint_header"
                if getattr(entry, "origin", None) == "hub_speech"
                else "pinned_video_recipe_and_checkpoint_header"
                if getattr(entry, "origin", None) == "hub_video"
                else "pinned_image_recipe_and_configuration"
                if getattr(entry, "origin", None) == "hub_image"
                else "pinned_publisher_configuration"
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
            "complete_install_budget_known": bool(images),
            **({"install_bytes_upper_bound": budget} if images else {}),
            "note": "File size is a minimum; runtime, companions and staging may need more space.",
        },
        "runtime_status": "runtime_unavailable"
        if images and not images[0].preparation_available
        else "supported_architecture_plan"
        if plans
        and any(
            getattr(entry, "origin", None)
            in {"hub", "hub_image", "hub_video", "hub_speech", "hub_music", "hub_avatar"}
            for entry in matches
        )
        else "reviewed_profile"
        if plans
        else "needs_compatible_recipe",
        "hardware_status": "estimated_fit"
        if any(p["fit"] == "estimated_fit" for p in plans)
        else "unknown"
        if any(p["fit"] == "unknown" for p in plans)
        else "not_recommended"
        if plans
        else "unknown",
        "profiles": plans,
        "reason": images[0].preparation_notice or "Prepare the supported media runtime prerequisites first."
        if images and not images[0].preparation_available
        else "Supported media graph; the fixed engine and all companions are included in this estimate. Review the workload; the downloaded graph is verified natively."
        if images
        else "Supported architecture; memory is estimated from pinned publisher configuration and verified natively after download."
        if plans and any(getattr(entry, "origin", None) == "hub" for entry in matches)
        else "Review the matching recipe and hardware profile before installing."
        if plans
        else "No validated workload profile for this object yet. File size alone cannot establish VRAM fit.",
        "automatic_ram_offload": False,
        **(
            {"requires_cpu_offload_consent": True}
            if images and images[0].capability in {"video", "music", "avatar"}
            else {}
        ),
        "automatic_cloud_fallback": False,
    }
