"""Guided preparation of the fixed optional Live runtime through ordinary workers."""

import platform
import sys
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import live_environment, runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.environment_prepare import OwnedEnvironmentPreparation
from ai_station_runner.live_hardware import compatible_gpus
from ai_station_runner.memory_scope import available
from ai_station_runner.memory_scope import scope_environment as scope_environment
from ai_station_runner.memory_scope import scope_prefix as scope_prefix
from ai_station_runner.telemetry import collect
from ai_station_runner.video_prepare import driver_supported
from ai_station_runner.windows_storage import disk_usage

PERMISSIONS = {"manage_models", "network_read", "workspace_write"}
PREPARATION_QUALIFIED = True
router = APIRouter(prefix="/v1/setup/live", tags=["live runtime preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["live-identity-linux-x86-64-python312-v1"]
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)


class Preparation(Selection):
    run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: datetime

    @model_validator(mode="after")
    def aware(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Live preparation needs an absolute timezone-aware deadline")
        return self


def permitted(body):
    from fastapi import HTTPException

    if set(body.permissions) != PERMISSIONS or body.profile != live_environment.PROFILE:
        raise HTTPException(
            403, "Live preparation needs its fixed profile and model/network/workspace permissions"
        )


def catalog():
    frozen = live_environment.recipe()
    root = get_settings().host_data_dir().resolve()
    hardware = collect(root)
    libc, version = platform.libc_ver()
    try:
        supported = (
            platform.system() == "Linux"
            and platform.machine() == "x86_64"
            and libc == "glibc"
            and tuple(map(int, version.split(".")[:2])) >= (2, 28)
            and available()
        )
    except ValueError:
        supported = False
    eligible = compatible_gpus(hardware)
    driver_ok = driver_supported(frozen["driver_minimum"])
    total = sum(v["size_bytes"] for v in frozen["inputs"])
    cached = 0
    for item in frozen["inputs"]:
        path = root / "models/store" / item["sha256"]
        if path.resolve() == path and path.is_file() and path.stat().st_size == item["size_bytes"]:
            cached += item["size_bytes"]
    required = total - cached + 9 * 1024**3
    free = disk_usage(root).free
    notice = (
        "Live preparation is still being qualified"
        if not PREPARATION_QUALIFIED
        else "Live needs Linux x86-64, its user resource manager and compatible CUDA GPUs"
        if not supported or not eligible or not driver_ok
        else "Live needs at least 16 GiB system RAM"
        if (hardware.get("memory") or {}).get("total_mib", 0) < 16384
        else "More free application storage is required"
        if free < required
        else None
    )
    from ai_station_runner.live_api import capabilities

    return {
        "recipe": frozen,
        "manifest_sha256": live_environment.MANIFEST,
        "platform_supported": supported,
        "installation_available": notice is None,
        "installation_notice": notice,
        "managed_live": capabilities(),
        "hardware": {"gpus": hardware.get("gpus"), "memory": hardware.get("memory")},
        "storage": {
            "free_bytes": free,
            "download_bytes": total,
            "cached_bytes_estimate": cached,
            "required_bytes": required,
        },
        "licenses": [
            {"name": "Face weights · noncommercial research only", "url": frozen["model_license_url"]},
            {"name": "Independent Seed-VC engine · GPL-3.0", "url": frozen["source_license_url"]},
            {
                "name": "Voice companion models · Apache-2.0",
                "url": "https://huggingface.co/facebook/wav2vec2-xls-r-300m",
            },
            {"name": "CUDA components", "url": "https://docs.nvidia.com/cuda/eula/index.html"},
        ],
    }


def journal(identity):
    return runtime_install.load_json(runtime_install.directory(identity) / "live.json")


def save(identity, value):
    runtime_install.atomic_json(runtime_install.directory(identity), "live.json", value)


def __getattr__(name):
    if name == "QUALIFIED":
        return live_environment.QUALIFIED
    raise AttributeError(name)


def controller():
    return OwnedEnvironmentPreparation(
        sys.modules[__name__], live_environment, "live", live_environment.NAMESPACE, live_environment.remember
    )


@router.get("")
def catalog_endpoint():
    return catalog()


@router.post("/prepare")
def prepare_endpoint(body: Preparation):
    return controller().start(runtime_install.process_manager(), body)


@router.get("/{identity}")
def inspection_endpoint(
    identity: UUID,
    stdout_offset: int = Query(0, ge=0, le=2**63 - 1),
    stderr_offset: int = Query(0, ge=0, le=2**63 - 1),
):
    return controller().inspection(
        runtime_install.process_manager(), identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset
    )


@router.post("/{identity}/cancel")
def cancel_endpoint(identity: UUID, body: Selection):
    return controller().cancel(runtime_install.process_manager(), identity, body)


@router.post("/{identity}/adopt")
def adopt_endpoint(identity: UUID, body: Selection):
    return controller().adopt(runtime_install.process_manager(), identity, body)
