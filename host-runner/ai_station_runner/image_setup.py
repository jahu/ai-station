"""Read-only fixed image setup recipe/report; inference qualification gates setup."""

import os
import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from ai_station_runner import managed_image_job as image_job
from ai_station_runner import runtime_install, runtime_setup
from ai_station_runner.config import get_settings
from ai_station_runner.security import resolve_child
from ai_station_runner.speech_environment import fingerprint
from ai_station_runner.telemetry import collect

router = APIRouter(prefix="/v1/setup/images", tags=["managed image setup"])


def recipe():
    source = image_job.recipe()
    return {
        **source["runtime"],
        "profile": source["profile"],
        "name": source["name"],
        "license_url": source["licenses"][0]["url"],
        "component_licenses": source["licenses"],
        "model_manifest_sha256": fingerprint(source),
        "minimum_free_bytes": 12 * 1024**3,
        "model_download_bytes": sum(item["size_bytes"] for item in source["files"]),
        "inputs": [{**item, "kind": "model"} for item in source["files"]],
        "capability": "image",
    }


def catalog():
    settings = get_settings()
    root = settings.host_data_dir().resolve()
    frozen = recipe()
    hardware = collect(root)
    supported = runtime_setup.platform_supported()
    image = None
    docker_free = None
    try:
        daemon = runtime_install.daemon()
        with runtime_install.client(daemon["socket"]) as api:
            image = runtime_install.inspect_image(api, frozen)
        docker_free = shutil.disk_usage(daemon["data_root"]).free
    except (HTTPException, httpx.HTTPError, OSError, KeyError, TypeError, ValueError):
        pass
    cached = 0
    for item in frozen["inputs"]:
        relative = "models/store/" + item["sha256"]
        try:
            path = resolve_child(root, relative)
            if path == root / relative and path.is_file() and path.stat().st_size == item["size_bytes"]:
                cached += item["size_bytes"]
        except (OSError, ValueError):
            pass
    # Capacity hints are independent of live availability and never enable an
    # unqualified profile. Actual inference fit remains an activation gate.
    gpus = [g for g in (hardware.get("gpus") or []) if (g.get("memory_total_mib") or 0) >= 12288]
    capacity_hint = len(gpus) >= 2
    configured = any((settings.photo_python, settings.photo_script))
    configured_available = bool(
        settings.photo_python
        and settings.photo_script
        and os.access(Path(settings.photo_python).expanduser(), os.X_OK)
        and Path(settings.photo_script).expanduser().is_file()
        and hardware.get("gpus")
    )
    model_files_present = False
    try:
        image_job.files(image_job.recipe())
        model_files_present = True
    except (HTTPException, OSError, ValueError):
        pass
    free = shutil.disk_usage(root).free
    required = frozen["model_download_bytes"] - cached + 2 * 1024**3
    docker_storage_ok = bool(image) or docker_free is not None and docker_free >= frozen["minimum_free_bytes"]
    notice = (
        "Managed image generation and guided setup are still being qualified"
        if not image_job.QUALIFIED
        else "A compatible Linux NVIDIA workstation is required"
        if not supported or not capacity_hint
        else "Local Docker storage could not be confirmed"
        if docker_free is None and not image
        else "More free Docker storage is required"
        if not docker_storage_ok
        else "More free application storage is required"
        if free < required
        else None
    )
    return {
        "recipe": frozen,
        "manifest_sha256": fingerprint(frozen),
        "platform_supported": supported,
        "installation_available": notice is None,
        "installation_notice": notice,
        "hardware": {"gpus": (hardware.get("gpus") or []), "memory": hardware.get("memory")},
        "image": {"present": image is not None, "id": image["id"] if image else None},
        "storage": {
            "free_bytes": free,
            "download_bytes": frozen["model_download_bytes"] + frozen["download_bytes"],
            "cached_model_bytes_estimate": cached,
            "required_bytes": required,
            "docker_free_bytes": docker_free,
            "docker_required_bytes": 0 if image else frozen["minimum_free_bytes"],
        },
        "existing_images": {
            "source": "configured" if configured else "managed",
            "available": configured_available
            if configured
            else bool(image_job.QUALIFIED and supported and capacity_hint and image and model_files_present),
        },
        "licenses": frozen["component_licenses"],
        "image_inference_tested_now": False,
    }


@router.get("")
def catalog_endpoint():
    return catalog()
