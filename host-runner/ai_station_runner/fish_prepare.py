"""Fixed fish preparation through the same owned offline lifecycle as speech."""

import platform
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import fish_environment, runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.environment_prepare import OwnedEnvironmentPreparation
from ai_station_runner.memory_scope import available
from ai_station_runner.memory_scope import scope_environment as scope_environment
from ai_station_runner.memory_scope import scope_prefix as scope_prefix
from ai_station_runner.telemetry import collect

# Fixed Linux profile passed actual setup, inference, recovery, Stop and privacy checks.
QUALIFIED = True
PERMISSIONS = {"manage_models", "network_read", "workspace_write"}
router = APIRouter(prefix="/v1/setup/fish", tags=["managed fish preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Literal["fish-s2-pro-linux-x86-64-python312-v1"]
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
    if set(body.permissions) != PERMISSIONS or body.profile != fish_environment.PROFILE:
        raise HTTPException(
            403, "Fish preparation requires its fixed profile and model/network/workspace permissions"
        )


def driver_supported(minimum):
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        versions = [
            tuple(map(int, line.strip().split("."))) for line in result.stdout.splitlines() if line.strip()
        ]
        return (
            result.returncode == 0
            and bool(versions)
            and all(v >= tuple(map(int, minimum.split("."))) for v in versions)
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def compatible_devices(gpus):
    """The fixed BF16 profile requires observed Ampere-or-newer CUDA devices."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode:
            return []
        supported = set()
        for line in result.stdout.splitlines():
            index, capability = [v.strip() for v in line.split(",")]
            if int(capability.split(".")[0]) >= 8:
                supported.add(int(index))
        return [g for g in gpus if int(g["index"]) in supported and (g.get("memory_total_mib") or 0) >= 5120]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def catalog():
    frozen = fish_environment.recipe()
    settings = get_settings()
    root = settings.host_data_dir().resolve()
    hardware = collect(root)
    gpus = hardware.get("gpus") or []
    fitting = compatible_devices(gpus)
    pairs = [
        (primary, codec)
        for primary in fitting
        for codec in fitting
        if primary["index"] != codec["index"] and (primary.get("memory_total_mib") or 0) >= 10240
    ]
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
    free = shutil.disk_usage(root).free
    required = total - cached + 12 * 1024**3
    configured = settings.fish_speech_enabled or any(
        getattr(settings, key) for key in ("fish_speech_python", "fish_speech_dir", "fish_speech_models")
    )
    # A path existing is configuration, not proof that imports/model inference work.
    from ai_station_runner.fish_runtime import capabilities

    existing = capabilities()
    driver_ok = driver_supported(frozen["driver_minimum"])
    notice = (
        "Managed fish setup and inference are still being qualified"
        if not QUALIFIED
        else "Fish setup requires Linux x86-64 and its user resource manager"
        if not supported
        else "This Fish profile needs two BF16-capable NVIDIA GPUs: at least 10 GiB primary and 5 GiB codec VRAM"
        if not pairs
        else "This complete fish profile requires at least 24 GiB system RAM"
        if ram < 24576
        else "This fish profile requires a compatible NVIDIA driver; inspect Diagnostics"
        if not driver_ok
        else "More free application storage is required"
        if free < required
        else None
    )
    return {
        "recipe": frozen,
        "manifest_sha256": fish_environment.fingerprint(frozen),
        "platform_supported": supported,
        "installation_available": notice is None,
        "installation_notice": notice,
        "existing_fish": {
            "source": "configured" if configured else "managed",
            "available": existing.get("available") is True,
            "readiness": existing.get("readiness"),
        },
        "hardware": {"gpus": gpus, "memory": hardware.get("memory")},
        "recommendation": {
            "minimum_vram_mib": 10240,
            "codec_vram_mib": 5120,
            "gpu_count": 2,
            "minimum_ram_mib": 24576,
            "fits": bool(supported and pairs and ram >= 24576 and driver_ok),
            "reason": "Semantic and codec weights stay on two distinct BF16 GPUs. Loading and generation require 24 GiB available host RAM in a zero-swap scope. Offline reference transcription uses its own CPU environment.",
            "gpu_indices": sorted({g["index"] for pair in pairs for g in pair}),
            "primary_gpu_indices": sorted({a["index"] for a, _ in pairs}),
            "codec_gpu_indices": sorted({b["index"] for _, b in pairs}),
            "cpu_offload": False,
            "ram_mib": 24576,
            "minimum_driver": frozen["driver_minimum"],
            "driver_supported": driver_ok,
        },
        "storage": {
            "free_bytes": free,
            "download_bytes": total,
            "cached_bytes_estimate": cached,
            "required_bytes": required,
        },
        "licenses": frozen["component_licenses"],
        "fish_inference_tested_now": False,
    }


def journal(identity):
    return runtime_install.load_json(runtime_install.directory(identity) / "fish.json")


def save(identity, value):
    runtime_install.atomic_json(runtime_install.directory(identity), "fish.json", value)


def controller():
    return OwnedEnvironmentPreparation(
        sys.modules[__name__],
        fish_environment,
        "fish",
        "fish-environments",
        fish_environment.remember,
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
