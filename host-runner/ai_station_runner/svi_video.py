"""Closed typed native SVI dispatch with exact engine, source and resource admission."""

import json
import math
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner import svi_environment
from ai_station_runner.avatars import owned
from ai_station_runner.config import get_settings
from ai_station_runner.media_compose import verified_path
from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.memory_scope import available, scope_environment, scope_prefix
from ai_station_runner.svi_identity import profile_identity
from ai_station_runner.telemetry import collect
from ai_station_runner.video_prepare import driver_supported
from ai_station_runner.video_runtime_schema import SviManagedRuntime as ManagedRuntime
from ai_station_runner.wan_svi_context import MAX_BYTES, generation_dimensions, validate_checkpoint

NAME = "wan_svi_video"
RAM_MIB = 18432
PORTRAIT_QUALIFIED = True
router = APIRouter(tags=["recurrent video"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    managed_runtime: ManagedRuntime
    permissions: list[Literal["filesystem_read"]] = Field(max_length=1)
    generation_profile: Literal["landscape", "portrait"] = Field(
        default="landscape", exclude_if=lambda value: value == "landscape"
    )


class SviRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    deadline_at: float = Field(gt=0, allow_inf_nan=False, strict=True)
    managed_runtime: ManagedRuntime
    image: MediaInput
    previous_motion: MediaInput | None = None
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    seed: StrictInt = Field(ge=0, le=2147483647)
    gpu: StrictInt = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)
    generation_profile: Literal["landscape", "portrait"] = Field(
        default="landscape", exclude_if=lambda value: value == "landscape"
    )

    @model_validator(mode="after")
    def bounds(self):
        if self.image.size_bytes > 20 * 1024**2 or (
            self.previous_motion is not None and self.previous_motion.size_bytes > MAX_BYTES
        ):
            raise ValueError("SVI needs bounded original image and motion inputs")
        return self


def capabilities(runtime=None, generation_profile="landscape"):
    width, height = generation_dimensions(generation_profile)
    if not svi_environment.QUALIFIED:
        return {
            "available": False,
            "backend": "wan22-svi-pro-q4",
            "reason": "SVI Pro video is still being qualified",
        }
    if generation_profile == "portrait" and not PORTRAIT_QUALIFIED:
        return {
            "available": False,
            "backend": "wan22-svi-pro-q4",
            "reason": "SVI Pro portrait video is still being qualified",
        }
    try:
        root = get_settings().host_data_dir().resolve()
        if runtime is None:
            private = svi_environment.read_json(root / "runtime/svi-environments/active.json")
            selected = svi_environment.resolve(root, private)
            runtime = svi_environment.public_observation(selected["observation"])
        else:
            svi_environment.resolve_public(root, runtime)
        hardware = collect(root)
        eligible = [
            int(row["index"])
            for row in hardware.get("gpus", [])
            if type(row.get("memory_total_mib")) in {int, float}
            and math.isfinite(row["memory_total_mib"])
            and row["memory_total_mib"] >= 12288
        ]
        total = (hardware.get("memory") or {}).get("total_mib")
        if (
            not eligible
            or type(total) not in {int, float}
            or not math.isfinite(total)
            or total < 24576
            or not available()
            or not driver_supported(svi_environment.recipe()["driver_minimum"])
        ):
            raise ValueError(
                "SVI Pro needs a 12-GiB GPU, 24-GiB RAM, compatible driver and user memory scope"
            )
        return {
            "available": True,
            "backend": "wan22-svi-pro-q4",
            "managed_runtime": runtime,
            "eligible_gpu_indices": eligible,
            "modes": ["animate"],
            "width": width,
            "height": height,
            "generation_profiles": [
                {"id": name, "width": w, "height": h}
                for name in (("landscape", "portrait") if PORTRAIT_QUALIFIED else ("landscape",))
                for w, h in [generation_dimensions(name)]
            ],
            "fps": 15,
            "native_window_frames": 81,
            "continuation_frames": 4,
            "steps": 20,
            "cfg": 5,
            "memory_estimate_mib": RAM_MIB,
        }
    except OSError:
        return {
            "available": False,
            "backend": "wan22-svi-pro-q4",
            "reason": "The owned SVI engine is unavailable or changed",
        }
    except (ValueError, KeyError, TypeError) as exc:
        return {"available": False, "backend": "wan22-svi-pro-q4", "reason": str(exc)}


def start_video(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "SVI media read/write permissions are required")
    runtime = body.managed_runtime.model_dump(mode="json")
    observed = (
        capabilities(runtime)
        if body.generation_profile == "landscape"
        else capabilities(runtime, body.generation_profile)
    )
    if not observed["available"]:
        raise HTTPException(409, observed["reason"])
    if body.gpu not in observed["eligible_gpu_indices"]:
        raise HTTPException(422, "Choose a compatible detected SVI GPU")
    if not 0 < body.deadline_at - time.time() <= 3600:
        raise HTTPException(422, "Each SVI native window requires a future deadline within one hour")
    root = get_settings().host_data_dir().resolve()
    selected = svi_environment.resolve_public(root, runtime)
    image = verified_path(root, body.image)
    try:
        with Image.open(image) as source:
            if source.format not in {"PNG", "JPEG"} or not 32 <= min(source.size) <= max(source.size) <= 8192:
                raise ValueError("Use a bounded original PNG/JPEG image")
            source.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Invalid SVI original image") from exc
    width, height = generation_dimensions(body.generation_profile)
    identity = profile_identity(runtime, body.image.sha256, body.generation_profile)
    if body.previous_motion is not None:
        motion = verified_path(root, body.previous_motion)
        validate_checkpoint(motion, identity, width=width, height=height)
    run_id = str(body.run_id)
    work = root / "runs" / run_id / "svi"
    output = owned(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    if work.resolve() != work:
        raise HTTPException(403, "SVI work directory must not cross symlinks")
    if work.exists() or output.exists():
        raise HTTPException(409, "Inspect existing owned SVI work before retrying")
    prefix = scope_prefix(run_id, RAM_MIB)
    work.mkdir(mode=0o700, parents=True)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = work / "request.json"
    config.write_text(
        json.dumps({"root": str(root), "request": body.model_dump(mode="json"), "profile_identity": identity})
    )
    config.chmod(0o600)
    home = work / "home"
    home.mkdir(mode=0o700)
    environment = {
        **scope_environment(),
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": str(work / "cache"),
        "TMPDIR": str(work),
        "CUDA_VISIBLE_DEVICES": str(body.gpu),
        "XDG_CACHE_HOME": str(work / "cache"),
        "TORCH_HOME": str(work / "cache/torch"),
        "TRITON_CACHE_DIR": str(work / "cache/triton"),
        "TOKENIZERS_PARALLELISM": "false",
    }
    return manager.start(
        run_id=run_id,
        argv=[
            *prefix,
            str(selected["video_python"]),
            str(Path(__file__).with_name("svi_video_job.py")),
            str(config),
        ],
        cwd=work,
        executor=NAME,
        env=environment,
        deadline_at=body.deadline_at,
    )


@router.get("/v1/video/svi/capabilities")
def available_profile():
    return capabilities()


@router.post("/v1/video/svi/model-capabilities")
def selected_profile(body: Selection):
    if set(body.permissions) != {"filesystem_read"}:
        raise HTTPException(403, "SVI model inspection requires filesystem read permission")
    runtime = body.managed_runtime.model_dump(mode="json")
    return (
        capabilities(runtime)
        if body.generation_profile == "landscape"
        else capabilities(runtime, body.generation_profile)
    )


@router.post("/v1/runs/svi")
def create(body: SviRequest):
    from ai_station_runner.app import manager
    from ai_station_runner.security import PathBoundaryError

    try:
        return {**start_video(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "The selected SVI input or engine changed") from exc
