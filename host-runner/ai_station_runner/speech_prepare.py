"""Typed, journaled lifecycle for the qualified fixed speech preparation profile."""

import os
import platform
import shutil
import stat
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import runtime_install, speech_environment
from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import available, scope_environment, scope_prefix
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child

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
            "free_bytes": shutil.disk_usage(root).free,
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


def inspection(manager, identity, *, stdout_offset=0, stderr_offset=0):
    identity = str(UUID(str(identity)))
    record = journal(identity)
    if record is None:
        raise HTTPException(404, "Speech preparation was not found")
    if record.get("profile") != speech_environment.PROFILE:
        raise HTTPException(409, "This native preparation belongs to a different profile")
    result = {
        "run_id": identity,
        "profile": record["profile"],
        "manifest_sha256": record.get("manifest_sha256"),
        "environment_prepared": False,
        "status": "interrupted",
        "alive": False,
        "requires_inspection": True,
        "process": None,
    }
    try:
        process = manager.inspect(identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset)
    except ProcessNotOwned:
        if record.get("cancellation_requested"):
            result.update(status="canceled", requires_inspection=False)
        return result
    if process.get("executor") != "speech_environment_setup":
        raise HTTPException(409, "This process belongs to another executor")
    result.update(process=process, alive=process["alive"])
    if process["alive"] or process.get("completion_pending"):
        result.update(
            status="cancel_requested" if record.get("cancellation_requested") else "running",
            requires_inspection=False,
        )
    elif record.get("cancellation_requested"):
        result.update(status="canceled", requires_inspection=False)
    elif process.get("status") == "exited" and process.get("exit_code") == 0:
        root = get_settings().host_data_dir().resolve()
        relative = f"runtime/speech/{record['manifest_sha256']}/{identity}/ready.json"
        path = resolve_child(root, relative)
        if path != root / relative:
            raise HTTPException(409, "Speech readiness cannot cross a symlink")
        receipt = runtime_install.load_json(path)
        if receipt and all(
            receipt.get(key) == value
            for key, value in {
                "profile": record["profile"],
                "operation_id": identity,
                "manifest_sha256": record["manifest_sha256"],
                "environment_prepared": True,
                "relative_path": str(Path(relative).parent),
            }.items()
        ):
            result.update(status="succeeded", environment_prepared=True, requires_inspection=False)
    elif process.get("status") in {"exited", "canceled"}:
        result.update(status="failed", requires_inspection=False)
    return result


def start(manager, body: Preparation):
    permitted(body)
    identity = str(body.run_id)
    value = body.model_dump(mode="json")
    value["permissions"] = sorted(value["permissions"])
    request_hash = speech_environment.fingerprint(value)
    with runtime_install.locked():
        if old := journal(identity):
            if (
                old.get("manifest_sha256") not in {None, body.manifest_sha256}
                or old.get("profile") != body.profile
            ):
                raise HTTPException(409, "This operation belongs to a different speech preparation")
            if (
                not (old.get("cancellation_requested") and old.get("manifest_sha256") is None)
                and old.get("request_hash") != request_hash
            ):
                raise HTTPException(409, "Native speech preparation identity is immutable")
            return inspection(manager, identity)
        observed = catalog()
        if not observed["installation_available"]:
            raise HTTPException(409, observed["installation_notice"])
        if body.manifest_sha256 != observed["manifest_sha256"]:
            raise HTTPException(409, "The speech recipe changed; review the current manifest")
        if not 0 < body.deadline_at.timestamp() - time.time() <= 4 * 3600:
            raise HTTPException(422, "Speech preparation needs a future deadline within four hours")
        root = get_settings().host_data_dir().resolve()
        record = {
            "profile": body.profile,
            "run_id": identity,
            "manifest_sha256": body.manifest_sha256,
            "deadline_at": body.deadline_at.isoformat(),
            "request_hash": request_hash,
            "cancellation_requested": False,
        }
        save(identity, record)
        folder = runtime_install.directory(identity)
        runtime_install.atomic_json(folder, "speech-request.json", {**record, "data_root": str(root)})
        manager.start(
            run_id=identity,
            argv=[
                *scope_prefix(identity, 4096),
                sys.executable,
                "-m",
                "ai_station_runner.speech_environment_job",
                str(folder / "speech-request.json"),
            ],
            cwd=root,
            executor="speech_environment_setup",
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                **scope_environment(),
            },
            deadline_at=body.deadline_at.timestamp(),
        )
        return inspection(manager, identity)


def cancel(manager, identity, body: Selection):
    permitted(body)
    identity = str(UUID(str(identity)))
    with runtime_install.locked():
        record = journal(identity) or {"profile": body.profile, "run_id": identity, "manifest_sha256": None}
        if record.get("profile") != body.profile:
            raise HTTPException(409, "This native preparation belongs to a different profile")
        record["cancellation_requested"] = True
        save(identity, record)  # A durable pre-dispatch Stop also prevents a lost-ACK start.
        try:
            process = manager.inspect(identity)
            if process.get("executor") != "speech_environment_setup":
                raise HTTPException(409, "This process belongs to another executor")
            manager.cancel(identity)
        except ProcessNotOwned:
            pass
        return inspection(manager, identity)


def adopt(manager, identity, body: Selection):
    permitted(body)
    if not QUALIFIED:
        raise HTTPException(409, "Managed speech activation is still being qualified")
    identity = str(UUID(str(identity)))
    with runtime_install.locked():
        result = inspection(manager, identity)
        if result["status"] != "succeeded" or not result["environment_prepared"] or result["alive"]:
            raise HTTPException(409, "Inspect the completed native speech preparation before activation")
        current = speech_environment.fingerprint(speech_environment.recipe())
        if current != result["manifest_sha256"]:
            raise HTTPException(409, "The native speech recipe changed before activation")
        root = get_settings().host_data_dir().resolve()
        folder = speech_environment.directory(root / "runtime", "speech")
        selected = {"profile": body.profile, "operation_id": identity, "manifest_sha256": current}
        runtime_install.atomic_json(folder, "active.json", selected)
        return {**selected, "environment_prepared": True, "speech_inference_tested_now": False}


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
