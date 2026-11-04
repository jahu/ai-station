"""Fixed offline Wan video profile; no graph, shell or ComfyUI server API."""

import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_serializer, model_validator

from ai_station_runner.avatars import owned
from ai_station_runner.config import get_settings
from ai_station_runner.media_compose import MediaInput, verified_path
from ai_station_runner.telemetry import collect
from ai_station_runner.video_runtime_schema import ManagedRuntime
from ai_station_runner.wan_guidance import apg_observation
from ai_station_runner.wan_profiles import BOUNDED, MEMORY_MIB, validate_profile


class FileObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size_bytes: int = Field(ge=0)
    mtime: float = Field(ge=0, allow_inf_nan=False)


class GuidanceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    size_bytes: int = Field(ge=1, le=65536)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    profile_observation: dict[Literal["wan_model", "wan_text_encoder", "wan_vae"], FileObservation] | None = (
        None
    )
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    continuation: MediaInput | None = None
    motion_context: MediaInput | None = None
    continuation_frames: StrictInt = Field(default=17, ge=1, le=17)
    continuation_guidance: Literal["standard", "apg_v1"] = "standard"
    guidance_observation: GuidanceObservation | None = None
    image_relative: str | None = Field(default=None, max_length=500)
    width: int = Field(default=1280, ge=128, le=1280, multiple_of=32)
    height: int = Field(default=704, ge=128, le=1280, multiple_of=32)
    frames: Literal[17, 33, 49, 65, 81] = 49
    steps: int = Field(default=20, ge=4, le=40)
    cfg: float = Field(default=5, ge=1, le=10, allow_inf_nan=False)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)
    memory_profile: Literal["default", "bounded_11g"] = "default"
    managed_runtime: ManagedRuntime | None = None

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        values = handler(self)
        if self.managed_runtime is None:
            values.pop("managed_runtime", None)
        if self.memory_profile == "default":
            values.pop("memory_profile", None)
        if self.continuation_frames == 17:
            values.pop("continuation_frames", None)
        if self.continuation_guidance == "standard":
            values.pop("continuation_guidance", None)
        if self.guidance_observation is None:
            values.pop("guidance_observation", None)
        return values

    @model_validator(mode="after")
    def area(self):
        if self.managed_runtime is not None and self.deadline_at is None:
            raise ValueError("Managed video requires its absolute execution deadline")
        validate_profile(
            {
                "memory_profile": self.memory_profile,
                "width": self.width,
                "height": self.height,
                "steps": self.steps,
            }
        )
        if self.continuation and self.image_relative:
            raise ValueError("Choose an initial image or preceding motion, not both")
        if self.motion_context and (not self.continuation or self.motion_context.size_bytes > 4 * 1024**2):
            raise ValueError("Motion checkpoints require a bounded preceding video")
        if self.continuation_frames not in (1, 17):
            raise ValueError("Choose a supported bounded continuation prefix")
        if self.continuation_frames == 1 and (not self.continuation or self.motion_context):
            raise ValueError("Single-frame continuation requires a preceding video without a raw checkpoint")
        if self.continuation_guidance != "standard" and (not self.continuation or self.motion_context):
            raise ValueError("Projected guidance requires preceding video pixels without a raw checkpoint")
        if (self.continuation_guidance == "standard") != (self.guidance_observation is None):
            raise ValueError("Projected guidance requires its frozen implementation observation")
        if self.width * self.height > 1280 * 704:
            raise ValueError("Video dimensions exceed the profile limit")
        return self


def profile(observation=None):
    from ai_station_runner.video_selection import FIELDS, selection

    settings = get_settings()
    chosen = selection(settings, observation) or {}
    if observation is not None and not chosen.get("managed"):
        raise HTTPException(409, "The exact managed video environment is no longer selected")
    if not all(chosen.get(key) for key in FIELDS):
        raise HTTPException(409, "Configure the existing Wan/ComfyUI installation and model files")
    paths = {key: chosen[key].absolute() for key in FIELDS}
    # Preserve a venv executable symlink, but fix trusted model/install targets.
    original = paths.copy()
    paths = {key: value if key == "video_python" else value.resolve() for key, value in paths.items()}
    if (
        not paths["video_python"].is_file()
        or not os.access(paths["video_python"], os.X_OK)
        or not (paths["comfy_dir"] / "nodes.py").is_file()
    ):
        raise HTTPException(409, "Video Python or ComfyUI installation is unavailable")
    for key in ("wan_model", "wan_text_encoder", "wan_vae"):
        if not paths[key].is_file() or original[key].suffix != ".safetensors":
            raise HTTPException(
                409, "Wan requires existing safetensors diffusion, text encoder and VAE files"
            )
    return paths


def capabilities():
    try:
        paths = profile()
        from ai_station_runner.video_environment import public_observation
        from ai_station_runner.video_prepare import driver_supported
        from ai_station_runner.video_selection import selection

        chosen = selection(get_settings()) or {}
        managed = chosen.get("managed") is True
        eligible = (
            [
                int(g["index"])
                for g in collect(get_settings().host_data_dir()).get("gpus", [])
                if (g.get("memory_total_mib") or 0) >= 12288
            ]
            if managed
            else []
        )
        if managed and (not eligible or not driver_supported("580.126.20")):
            raise HTTPException(
                409, "The managed video profile requires its compatible NVIDIA GPU and driver"
            )
        guidance = apg_observation(paths)
        observation = {
            key: {"size_bytes": paths[key].stat().st_size, "mtime": paths[key].stat().st_mtime}
            for key in ("wan_model", "wan_text_encoder", "wan_vae")
        }
        memory_mib = (
            (
                max(paths["wan_model"].stat().st_size, paths["wan_text_encoder"].stat().st_size)
                + paths["wan_vae"].stat().st_size
            )
            // (1024 * 1024)
            + 4096
            + 81 * 1280 * 704 * 12 // (1024 * 1024)
        )
        return {
            "available": True,
            "configuration_source": "managed" if managed else "configured",
            **(
                {
                    "managed_runtime": public_observation(chosen["observation"]),
                    "eligible_gpu_indices": eligible,
                }
                if managed
                else {}
            ),
            "backend": "wan2.2-5b",
            "continuation_frames": [1, 17],
            "continuation_guidance": ["standard", "apg_v1"] if guidance else ["standard"],
            **({"guidance_observation": guidance} if guidance else {}),
            "modes": ["generate", "animate"],
            "fps": 24,
            "memory_estimate_mib": memory_mib,
            "profile_observation": observation,
            "memory_profiles": memory_profiles(),
        }
    except HTTPException as exc:
        return {"available": False, "backend": "wan2.2-5b", "reason": exc.detail}


def memory_profiles():
    from ai_station_runner.memory_scope import available
    from ai_station_runner.video_selection import selection

    enabled = (
        get_settings().wan_bounded_profile or bool((selection(get_settings()) or {}).get("managed"))
    ) and available()
    return [
        {
            "id": BOUNDED,
            "available": enabled,
            "ram_mib": MEMORY_MIB,
            "width": 1280,
            "height": 704,
            "minimum_steps": 20,
            **(
                {}
                if enabled
                else {
                    "reason": "The bounded Wan profile is not enabled or user memory scopes are unavailable"
                }
            ),
        }
    ]


def start_video(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Video read/write permissions are required")
    from ai_station_runner.video_selection import selection

    observation = body.managed_runtime.model_dump(mode="json") if body.managed_runtime else None
    chosen = selection(get_settings(), observation) or {}
    managed = chosen.get("managed") is True
    if managed and (observation is None or body.memory_profile != BOUNDED):
        raise HTTPException(409, "Managed video requires its frozen environment and bounded memory profile")
    paths = profile(observation) if observation is not None else profile()
    if body.continuation_guidance != "standard":
        guidance = apg_observation(paths)
        if guidance is None:
            raise HTTPException(409, "The configured ComfyUI installation has no compatible APG method")
        if guidance != body.guidance_observation.model_dump():
            raise HTTPException(409, "The APG implementation changed after this video plan was prepared")
    prefix = []
    if body.memory_profile == BOUNDED:
        from ai_station_runner.memory_scope import scope_prefix

        if not memory_profiles()[0]["available"]:
            raise HTTPException(409, "The bounded Wan memory profile is unavailable")
        try:
            prefix = scope_prefix(str(body.run_id), MEMORY_MIB)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if body.profile_observation is not None:
        observed = {
            key: {"size_bytes": paths[key].stat().st_size, "mtime": paths[key].stat().st_mtime}
            for key in ("wan_model", "wan_text_encoder", "wan_vae")
        }
        if {key: value.model_dump() for key, value in body.profile_observation.items()} != observed:
            raise HTTPException(409, "Wan model files changed after this job was prepared")
    root = get_settings().host_data_dir().resolve()
    previous = verified_path(root, body.continuation, verify_hash=False) if body.continuation else None
    if previous and previous.suffix != ".mp4":
        raise HTTPException(422, "Choose an owned prior video segment")
    motion = verified_path(root, body.motion_context, verify_hash=False) if body.motion_context else None
    if motion and motion.suffix != ".safetensors":
        raise HTTPException(422, "Use an owned safe motion checkpoint")
    if motion:
        from ai_station_runner.wan_motion import profile_key, validate_checkpoint

        try:
            validate_checkpoint(motion, body.width, body.height, profile_key(paths, body.memory_profile))
        except (ValueError, OSError) as exc:
            raise HTTPException(422, "Invalid bounded motion checkpoint") from exc
    image = None
    if body.image_relative:
        image = owned(root, body.image_relative)
        try:
            if image.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Image is too large")
            with Image.open(image) as source:
                if (
                    source.format not in {"PNG", "JPEG"}
                    or not 32 <= min(source.size) <= max(source.size) <= 8192
                ):
                    raise ValueError("Use a bounded PNG/JPEG image")
                source.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "Invalid video image input") from exc
    if body.gpu not in {int(g["index"]) for g in collect(root).get("gpus", [])}:
        raise HTTPException(422, "GPU is not present")
    if managed:
        from ai_station_runner.video_prepare import driver_supported

        if not driver_supported("580.126.20") or not any(
            int(g["index"]) == body.gpu and (g.get("memory_total_mib") or 0) >= 12288
            for g in collect(root).get("gpus", [])
        ):
            raise HTTPException(409, "The selected GPU or driver does not fit the managed video profile")
    run_id = str(body.run_id)
    output = owned(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    work = root / "runs" / run_id / "video"
    if work.resolve() != work:
        raise HTTPException(403, "Video work directory must not contain symlinks")
    if work.exists() or output.exists():
        raise HTTPException(409, "Inspect existing video work before retrying")
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = work / "request.json"
    config.write_text(
        json.dumps(
            {
                "request": body.model_dump(mode="json"),
                "paths": {key: str(value) for key, value in paths.items()},
                "image": str(image) if image else None,
                "previous_video": str(previous) if previous else None,
                "motion_context": str(motion) if motion else None,
                "output": str(output),
                "root": str(root),
                "work": str(work),
            }
        )
    )
    config.chmod(0o600)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "LD_LIBRARY_PATH", "PYTHONPATH"}
    }
    environment.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HOME=str(work / "cache"),
        TMPDIR=str(work),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        CUDA_VISIBLE_DEVICES=str(body.gpu),
        XDG_CACHE_HOME=str(work / "cache"),
        TORCH_HOME=str(work / "cache" / "torch"),
        TRITON_CACHE_DIR=str(work / "cache" / "triton"),
    )
    if managed:
        home = work / "home"
        home.mkdir(mode=0o700)
        environment = {
            key: value for key, value in environment.items() if key not in {"HOME", "LD_LIBRARY_PATH"}
        }
        environment.update(
            PATH="/usr/bin:/bin",
            HOME=str(home),
            PYTHONPATH=str(Path(__file__).resolve().parent.parent),
            OMP_NUM_THREADS="2",
            TOKENIZERS_PARALLELISM="false",
        )
    if prefix:
        from ai_station_runner.memory_scope import scope_environment

        environment.update(scope_environment())
    return manager.start(
        run_id=run_id,
        argv=[*prefix, str(paths["video_python"]), "-m", "ai_station_runner.video_job", str(config)],
        cwd=work,
        executor="wan_video",
        env=environment,
        **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
    )
