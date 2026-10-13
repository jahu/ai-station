"""Fixed offline Wan video profile; no graph, shell or ComfyUI server API."""

import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.avatars import owned
from ai_station_runner.config import get_settings
from ai_station_runner.telemetry import collect


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    image_relative: str | None = Field(default=None, max_length=500)
    width: int = Field(default=1280, ge=128, le=1280, multiple_of=32)
    height: int = Field(default=704, ge=128, le=1280, multiple_of=32)
    frames: Literal[17, 33, 49, 65, 81] = 49
    steps: int = Field(default=20, ge=4, le=40)
    cfg: float = Field(default=5, ge=1, le=10, allow_inf_nan=False)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def area(self):
        if self.width * self.height > 1280 * 704:
            raise ValueError("Video dimensions exceed the profile limit")
        return self


def profile():
    settings = get_settings()
    names = ("video_python", "comfy_dir", "wan_model", "wan_text_encoder", "wan_vae")
    if not all(getattr(settings, key) for key in names):
        raise HTTPException(409, "Configure the existing Wan/ComfyUI installation and model files")
    paths = {key: Path(getattr(settings, key)).expanduser().absolute() for key in names}
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
        profile()
        return {"available": True, "backend": "wan2.2-5b", "modes": ["generate", "animate"], "fps": 24}
    except HTTPException as exc:
        return {"available": False, "backend": "wan2.2-5b", "reason": exc.detail}


def start_video(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Video read/write permissions are required")
    paths = profile()
    root = get_settings().host_data_dir().resolve()
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
                "output": str(output),
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
    return manager.start(
        run_id=run_id,
        argv=[str(paths["video_python"]), "-m", "ai_station_runner.video_job", str(config)],
        cwd=work,
        executor="wan_video",
        env=environment,
    )
