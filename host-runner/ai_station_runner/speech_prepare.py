"""Typed, journaled lifecycle for the qualified fixed speech preparation profile."""

import os
import platform
import stat
import sys
import time as time
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import runtime_install, speech_environment
from ai_station_runner.config import get_settings
from ai_station_runner.environment_prepare import OwnedEnvironmentPreparation
from ai_station_runner.memory_scope import available
from ai_station_runner.memory_scope import scope_environment as scope_environment
from ai_station_runner.memory_scope import scope_prefix as scope_prefix
from ai_station_runner.windows_storage import disk_usage

QUALIFIED = True
PERMISSIONS = {"manage_models", "network_read", "workspace_write"}
router = APIRouter(prefix="/v1/setup/speech", tags=["managed speech preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["chatterbox-v3-linux-x86-64-python312-v1"]
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)


class Preparation(Selection):
    run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: datetime

    @model_validator(mode="after")
    def aware(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Use an absolute timezone-aware preparation deadline")
        return self


def permitted(body):
    if set(body.permissions) != PERMISSIONS:
        raise HTTPException(403, "Speech preparation requires model, network and workspace permissions")


def catalog():
    from ai_station_runner.speech_selection import selection
    from ai_station_runner.telemetry import collect

    frozen = speech_environment.recipe()
    root = get_settings().host_data_dir().resolve()
    hardware = collect(root)
    gpus = hardware.get("gpus") or []
    fitting = [gpu for gpu in gpus if (gpu.get("memory_total_mib") or 0) >= 6144]
    libc, version = platform.libc_ver()
    try:
        libc_supported = libc == "glibc" and tuple(int(part) for part in version.split(".")[:2]) >= (2, 28)
    except ValueError:
        libc_supported = False
    supported = (
        platform.system() == "Linux"
        and platform.machine() in {"x86_64", "AMD64"}
        and sys.version_info[:2] == (3, 12)
        and libc_supported
        and available()
    )
    source = selection(get_settings()) or {}
    configured = bool(
        source.get("python")
        and source["python"].is_file()
        and os.access(source["python"], os.X_OK)
        and source.get("script")
        and source["script"].is_file()
        and source.get("cache")
        and source["cache"].is_dir()
    )
    total = sum(item["size_bytes"] for item in frozen["inputs"])
    cached = 0
    for item in frozen["inputs"]:
        path = root / "models/store" / item["sha256"]
        try:
            info = path.lstat()
            if path.resolve() == path and stat.S_ISREG(info.st_mode) and info.st_size == item["size_bytes"]:
                cached += item["size_bytes"]
        except OSError:
            pass
    licenses = [
        {"name": "Speech model", "url": frozen["model_license_url"]},
        {"name": "Python", "url": "https://docs.python.org/3/license.html"},
        {"name": "CUDA components", "url": "https://docs.nvidia.com/cuda/eula/index.html"},
    ]
    for item in (v for v in frozen["inputs"] if v["kind"] == "sdk"):
        repository = "resemble-ai/chatterbox" if item["name"] == "chatterbox" else "resemble-ai/Perth"
        licenses.append(
            {"name": item["name"], "url": f"https://github.com/{repository}/blob/{item['revision']}/LICENSE"}
        )
    return {
        "recipe": frozen,
        "manifest_sha256": speech_environment.fingerprint(frozen),
        "platform_supported": supported,
        "installation_available": QUALIFIED and supported and bool(fitting),
        "installation_notice": "Managed speech dispatch and guided setup are still being qualified"
        if not QUALIFIED
        else "Speech setup requires Linux x86-64 and an available user-level resource manager"
        if not supported
        else "Speech needs an NVIDIA GPU with at least 6 GiB VRAM"
        if not fitting
        else None,
        "existing_speech": {
            "configured": configured,
            "available": configured
            and (supported and bool(fitting) if source.get("managed") else bool(gpus)),
            "source": "managed" if source.get("managed") else "configured",
        },
        "hardware": {"gpus": gpus, "memory": hardware.get("memory")},
        "recommendation": {
            "fits": supported and bool(fitting),
            "minimum_vram_mib": 6144,
            "gpu_indices": [gpu["index"] for gpu in fitting],
            "reason": "Fits this workstation. Uses one NVIDIA GPU; your voice and text stay local."
            if supported and fitting
            else "This speech profile requires a supported Linux workstation and an NVIDIA GPU with at least 6 GiB VRAM.",
        },
        "storage": {
            "free_bytes": disk_usage(root).free,
            "download_bytes": total,
            "cached_bytes_estimate": cached,
            "required_bytes": total - cached + 8 * 1024**3,
        },
        "licenses": licenses,
        "speech_inference_tested_now": False,
    }


def journal(identity):
    return runtime_install.load_json(runtime_install.directory(identity) / "speech.json")


def save(identity, value):
    runtime_install.atomic_json(runtime_install.directory(identity), "speech.json", value)


def controller():
    return OwnedEnvironmentPreparation(sys.modules[__name__], speech_environment, "speech", "speech")


def inspection(manager, identity, *, stdout_offset=0, stderr_offset=0):
    return controller().inspection(
        manager, identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset
    )


def start(manager, body: Preparation):
    return controller().start(manager, body)


def cancel(manager, identity, body: Selection):
    return controller().cancel(manager, identity, body)


def adopt(manager, identity, body: Selection):
    return controller().adopt(manager, identity, body)


@router.get("")
def catalog_endpoint():
    return catalog()


@router.post("/prepare")
def prepare_endpoint(body: Preparation):
    return start(runtime_install.process_manager(), body)


@router.get("/{identity}")
def inspection_endpoint(
    identity: UUID,
    stdout_offset: int = Query(0, ge=0, le=2**63 - 1),
    stderr_offset: int = Query(0, ge=0, le=2**63 - 1),
):
    return inspection(
        runtime_install.process_manager(), identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset
    )


@router.post("/{identity}/cancel")
def cancel_endpoint(identity: UUID, body: Selection):
    return cancel(runtime_install.process_manager(), identity, body)


@router.post("/{identity}/adopt")
def adopt_endpoint(identity: UUID, body: Selection):
    return adopt(runtime_install.process_manager(), identity, body)
