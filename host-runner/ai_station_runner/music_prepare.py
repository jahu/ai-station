"""Fixed music preparation through the same owned offline lifecycle as speech."""

import platform
import sys
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import music_environment, runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.environment_prepare import OwnedEnvironmentPreparation
from ai_station_runner.memory_scope import available
from ai_station_runner.memory_scope import scope_environment as scope_environment
from ai_station_runner.memory_scope import scope_prefix as scope_prefix
from ai_station_runner.telemetry import collect
from ai_station_runner.windows_storage import disk_usage

# Complete API/worker/native installation, real generation and owned
# Stop/recovery are qualified for this fixed Linux profile; see its plan.
QUALIFIED = True
PERMISSIONS = {"manage_models", "network_read", "workspace_write"}
router = APIRouter(prefix="/v1/setup/music", tags=["managed music preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["ace-step15-turbo-linux-x86-64-python312-v1"]
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
    if set(body.permissions) != PERMISSIONS or body.profile != music_environment.PROFILE:
        raise HTTPException(
            403, "Music preparation requires its fixed profile and model/network/workspace permissions"
        )


def catalog():
    frozen = music_environment.recipe()
    settings = get_settings()
    root = settings.host_data_dir().resolve()
    hardware = collect(root)
    gpus = hardware.get("gpus") or []
    fitting = [g for g in gpus if (g.get("memory_total_mib") or 0) >= 12288]
    libc, version = platform.libc_ver()
    try:
        supported = (
            platform.system() == "Linux"
            and platform.machine() in {"x86_64", "AMD64"}
            and sys.version_info[:2] == (3, 12)
            and libc == "glibc"
            and tuple(map(int, version.split(".")[:2])) >= (2, 28)
            and available()
        )
    except ValueError:
        supported = False
    ram = (hardware.get("memory") or {}).get("total_mib", 0)
    total = sum(v["size_bytes"] for v in frozen["inputs"])
    cached = 0
    for item in frozen["inputs"]:
        path = root / "models/store" / item["sha256"]
        try:
            if path.resolve() == path and path.is_file() and path.stat().st_size == item["size_bytes"]:
                cached += item["size_bytes"]
        except OSError:
            pass
    free = disk_usage(root).free
    required = total - cached + 8 * 1024**3
    configured = any((settings.music_python, settings.music_source_dir, settings.music_model_dir))
    # A path existing is configuration, not proof that imports/model inference work.
    from ai_station_runner.music import capabilities

    existing = capabilities()
    notice = (
        "Managed music setup and inference are still being qualified"
        if not QUALIFIED
        else "Music setup requires Linux x86-64 and its user resource manager"
        if not supported
        else "This music profile requires an NVIDIA GPU with at least 12 GiB VRAM"
        if not fitting
        else "This complete music profile requires at least 24 GiB system RAM"
        if ram < 24576
        else "More free application storage is required"
        if free < required
        else None
    )
    return {
        "recipe": frozen,
        "manifest_sha256": music_environment.fingerprint(frozen),
        "platform_supported": supported,
        "installation_available": notice is None,
        "installation_notice": notice,
        "existing_music": {
            "source": "configured" if configured else "managed",
            "available": existing.get("available") is True,
        },
        "hardware": {"gpus": gpus, "memory": hardware.get("memory")},
        "recommendation": {
            "minimum_vram_mib": 12288,
            "minimum_ram_mib": 24576,
            "fits": bool(supported and fitting and ram >= 24576),
            "reason": "Uses one compatible GPU and CPU offload. The complete profile needs at least 24 GiB system RAM.",
            "gpu_indices": [g["index"] for g in fitting],
            "cpu_offload": True,
            "short_ram_mib": 12288,
            "long_ram_mib": 18432,
        },
        "storage": {
            "free_bytes": free,
            "download_bytes": total,
            "cached_bytes_estimate": cached,
            "required_bytes": required,
        },
        "licenses": [
            {"name": "ACE-Step models · MIT", "url": frozen["model_license_url"]},
            {"name": "ACE-Step SDK · MIT", "url": frozen["source_license_url"]},
            {"name": "Qwen embedding component", "url": "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B"},
            {"name": "Python", "url": "https://docs.python.org/3/license.html"},
            {"name": "CUDA components", "url": "https://docs.nvidia.com/cuda/eula/index.html"},
        ],
        "music_inference_tested_now": False,
    }


def journal(identity):
    return runtime_install.load_json(runtime_install.directory(identity) / "music.json")


def save(identity, value):
    runtime_install.atomic_json(runtime_install.directory(identity), "music.json", value)


def controller():
    return OwnedEnvironmentPreparation(
        sys.modules[__name__], music_environment, "music", "music-environments"
    )


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
