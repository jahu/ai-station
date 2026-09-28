"""Validated local avatar operations, with owned outputs and offline models."""

import os
import wave
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.security import resolve_child
from ai_station_runner.telemetry import collect


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    image_relative: str = Field(max_length=500)
    audio_relative: str = Field(max_length=500)
    prompt: str = Field(min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    frames: Literal[17, 33, 49, 65, 81] = 81
    steps: int = Field(default=8, ge=4, le=30)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)


def owned(root, relative):
    path = resolve_child(root, relative)
    if not relative.startswith("artifacts/") or path != root / relative:
        raise HTTPException(403, "Use owned artifacts without symlinks")
    return path


def start_avatar(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Avatar read/write permissions are required")
    settings = get_settings()
    if not all((settings.echomimic_python, settings.echomimic_dir, settings.echomimic_models)):
        raise HTTPException(
            409, "Configure the existing EchoMimic Python, installation and flash model directory"
        )
    # Keep the venv executable path: resolving its symlink loses site-packages.
    python = Path(settings.echomimic_python).expanduser().absolute()
    runtime = Path(settings.echomimic_dir).expanduser().resolve()
    models = Path(settings.echomimic_models).expanduser().resolve()
    base = models / "Wan2.1-Fun-V1.1-1.3B-InP"
    checkpoint = models / "transformer/diffusion_pytorch_model.safetensors"
    if not all(
        p.is_file()
        for p in (
            python,
            runtime / "infer_flash.py",
            runtime / "config/config.yaml",
            checkpoint,
            base / "Wan2.1_VAE.pth",
            base / "models_t5_umt5-xxl-enc-bf16.pth",
            base / "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
        )
    ):
        raise HTTPException(409, "EchoMimic installation or existing model files are incomplete")
    root = settings.host_data_dir().resolve()
    portrait, speech = owned(root, body.image_relative), owned(root, body.audio_relative)
    try:
        if portrait.stat().st_size > 20 * 1024 * 1024 or speech.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Input is too large")
        with Image.open(portrait) as image:
            if (
                image.format not in {"PNG", "JPEG"}
                or max(image.size) > 8192
                or min(image.size) < 32
                or max(image.size) / min(image.size) > 4
            ):
                raise ValueError("Use a bounded PNG/JPEG image")
            image.verify()
        with wave.open(str(speech), "rb") as wav:
            frames, rate, channels = wav.getnframes(), wav.getframerate(), wav.getnchannels()
            if not 8000 <= rate <= 96000 or channels not in {1, 2} or not 0.68 <= frames / rate <= 60:
                raise ValueError("Use PCM WAV, 0.68–60 seconds")
            if len(wav.readframes(frames)) != frames * channels * wav.getsampwidth():
                raise ValueError("Truncated WAV")
    except (OSError, ValueError, EOFError, wave.Error, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Invalid portrait or speech input") from exc
    if body.gpu not in {int(g["index"]) for g in collect(root).get("gpus", [])}:
        raise HTTPException(422, "GPU is not present")
    run_id = str(body.run_id)
    output = owned(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    work = resolve_child(root, f"runs/{run_id}/avatar")
    if work != root / f"runs/{run_id}/avatar":
        raise HTTPException(403, "Work directory must not contain symlinks")
    if output.exists() or work.exists():
        raise HTTPException(409, "Inspect existing avatar work before retrying")
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(python),
        str(Path(__file__).with_name("echomimic_entry.py")),
        "--runtime-dir",
        str(runtime),
        "--output-path",
        str(output),
        "--image_path",
        str(portrait),
        "--audio_path",
        str(speech),
        "--prompt",
        body.prompt,
        "--config_path",
        str(runtime / "config/config.yaml"),
        "--model_name",
        str(base),
        "--transformer_path",
        str(checkpoint),
        "--wav2vec_model_dir",
        str(models / "chinese-wav2vec2-base"),
        "--save_path",
        str(work),
        "--sample_size",
        str(body.size),
        str(body.size),
        "--video_length",
        str(body.frames),
        "--num_inference_steps",
        str(body.steps),
        "--seed",
        str(body.seed),
        "--num_skip_start_steps",
        "1",
        "--teacache_offload",
    ]
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": str(work / "cache"),
        "TMPDIR": str(work),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "CUDA_VISIBLE_DEVICES": str(body.gpu),
    }
    return manager.start(run_id=run_id, argv=argv, cwd=work, executor="echomimic", env=environment)
