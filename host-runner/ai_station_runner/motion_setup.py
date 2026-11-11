"""Atomic adoption of a packaged-recipe local renderer; never a Docker command API."""

import hashlib
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.config import get_settings
from ai_station_runner.memory_scope import available
from ai_station_runner.motion_docker import connection, docker
from ai_station_runner.motion_image import image, inspect_image
from ai_station_runner.motion_image import recipe as renderer_recipe
from ai_station_runner.motion_installation import observation
from ai_station_runner.runtime_install import (
    atomic_json,
    directory,
    load_json,
    locked,
    permitted,
)
from ai_station_runner.runtime_setup import fingerprint, platform_supported

PROFILE = "hyperframes-cpu-linux-amd64-v1"
QUALIFIED = True
router = APIRouter(prefix="/v1/setup/motion", tags=["Studio export preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["hyperframes-cpu-linux-amd64-v1"]


class Prepare(Selection):
    run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: datetime
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)

    @model_validator(mode="after")
    def aware(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Use an absolute timezone-aware setup deadline")
        return self


class Cancel(Selection):
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)


def recipe():
    return {
        "profile": PROFILE,
        "name": "Studio · Full-HD film export",
        "capability": "motion",
        "platform": "linux/amd64",
        "renderer_recipe_sha256": renderer_recipe(),
        "activation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "image_reference": "local:ai-station-motion:" + renderer_recipe(),
        "download_bytes": 0,
        "minimum_free_bytes": 0,
        "license": "Installed renderer component licenses; no new software or model download in this activation step",
        "license_url": "https://github.com/heygen-com/hyperframes/blob/main/LICENSE",
        "preparation_mode": "existing_image",
    }


def record(identity):
    return load_json(directory(identity) / "motion-setup.json")


def save(identity, value):
    atomic_json(directory(identity), "motion-setup.json", value)


def selection_path():
    root = get_settings().host_data_dir().resolve()
    folder = root
    for part in ("runtime", "motion"):
        folder = folder / part
        if folder.is_symlink() or folder.resolve() != folder:
            raise ValueError("Renderer selection crosses a symlink")
        folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def candidate():
    settings = get_settings()
    if settings.motion_image:
        return image(settings)
    try:
        return image(settings)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    bound = connection()
    raw = docker(
        [
            "image",
            "ls",
            "--filter",
            "label=ai-station.motion.recipe=" + renderer_recipe(),
            "--no-trunc",
            "--format",
            "{{.ID}}",
        ],
        bound=bound,
    )
    identities = sorted(set(raw.splitlines()))
    if len(identities) > 20:
        raise ValueError("Too many local renderer candidates; inspect local setup")
    for identity in identities:
        try:
            return inspect_image(identity, bound=bound)
        except ValueError:
            continue
    raise ValueError(
        "No compatible local Studio export engine; automatic fresh installation is still being implemented"
    )


def descriptor(installed):
    return {"id": installed["image_id"], "reference": recipe()["image_reference"], "platform": "linux/amd64"}


def current():
    installed = image(get_settings())
    return descriptor(installed), observation(installed)


@router.get("")
def catalog():
    frozen = recipe()
    supported = platform_supported()
    report = {
        "recipe": frozen,
        "manifest_sha256": fingerprint(frozen),
        "platform_supported": supported,
        "usable_image": False,
        "installation_available": False,
        "installation_notice": "Studio export preparation is still being qualified",
        "image": {"present": False, "status": "unavailable"},
    }
    if not supported or not available():
        report["installation_notice"] = (
            "Studio export requires the supported local Linux/WSL runner and user task limits"
        )
        return report
    try:
        installed = candidate()
        report["image"] = {"present": True, "status": "available", "id": installed["image_id"]}
        report["installation_available"] = QUALIFIED
        try:
            selected, observed = current()
            report.update(usable_image=True, renderer_observation=observed, selected_image=selected)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        if QUALIFIED:
            report["installation_notice"] = (
                "The compatible engine is already on this station; activation downloads no models"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report["installation_notice"] = str(exc)
    return report


def snapshot(identity, saved):
    result = {
        "run_id": str(identity),
        "runner_id": get_settings().runner_id,
        "status": "canceled" if saved.get("cancel_requested") else "interrupted",
        "alive": False,
        "requires_inspection": False,
        "process": None,
        "manifest_sha256": saved.get("manifest_sha256"),
        "image": None,
    }
    if result["status"] == "canceled":
        return result
    if saved.get("request_hash") and saved.get("recipe") == recipe():
        try:
            selected, observed = current()
            receipt = load_json(selection_path() / "selection.json")
            explicit = bool(get_settings().motion_image)
            if (
                selected == saved.get("image")
                and observed == saved.get("renderer_observation")
                and (explicit or receipt and receipt.get("activation_request_hash") == saved["request_hash"])
            ):
                result.update(status="succeeded", image=selected, renderer_observation=observed)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return result


@router.post("/prepare")
def prepare(body: Prepare):
    permitted(body)
    value = body.model_dump(mode="json")
    identity, request_hash = str(body.run_id), fingerprint(value)
    with locked():
        old = record(identity)
        if old:
            if old.get("cancel_requested") and old.get("request_hash") is None:
                return snapshot(identity, old)
            if old.get("request_hash") != request_hash:
                raise HTTPException(409, "Renderer activation identity is immutable")
            return snapshot(identity, old)
        frozen = recipe()
        if not QUALIFIED or not platform_supported() or fingerprint(frozen) != body.manifest_sha256:
            raise HTTPException(409, "Renderer activation is unavailable or its recipe changed")
        if not 0 < body.deadline_at.timestamp() - time.time() <= 4 * 3600 or not available():
            raise HTTPException(422, "Use a supported bounded local renderer activation")
        try:
            installed = candidate()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HTTPException(
                409, "The compatible local export engine is unavailable; refresh setup"
            ) from exc
        if time.time() >= body.deadline_at.timestamp():
            raise HTTPException(422, "Renderer activation deadline passed before publication")
        saved = {
            "request": value,
            "request_hash": request_hash,
            "manifest_sha256": body.manifest_sha256,
            "recipe": frozen,
            "image": descriptor(installed),
            "renderer_observation": observation(installed),
            "cancel_requested": False,
        }
        save(identity, saved)  # Intent precedes the single atomic selection publication.
        try:
            if not get_settings().motion_image:
                atomic_json(
                    selection_path(),
                    "selection.json",
                    {
                        "protocol": 1,
                        "recipe_sha256": installed["recipe_sha256"],
                        "image_id": installed["image_id"],
                        "activation_request_hash": request_hash,
                    },
                )
        except (OSError, ValueError):
            # Reobserve a lost/failed publication; never replay that identity.
            return snapshot(identity, saved)
        return snapshot(identity, saved)


@router.get("/{identity}")
def inspect(
    identity: UUID,
    stdout_offset: int = Query(0, ge=0, le=2**63 - 1),
    stderr_offset: int = Query(0, ge=0, le=2**63 - 1),
):
    with locked():
        saved = record(identity)
        if saved is None:
            raise HTTPException(404, "Renderer activation not found")
        return snapshot(identity, saved)


@router.post("/{identity}/cancel")
def cancel(identity: UUID, body: Cancel):
    permitted(body)
    with locked():
        saved = record(identity) or {"request_hash": None}
        saved["cancel_requested"] = True
        save(identity, saved)
        return snapshot(identity, saved)
