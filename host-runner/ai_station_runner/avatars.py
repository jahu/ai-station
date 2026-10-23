"""Validated local avatar operations, with owned outputs and offline models."""

import os
import wave
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.config import get_settings
from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.security import resolve_child
from ai_station_runner.telemetry import collect


class AudioWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_frame: StrictInt = Field(ge=0, le=7499)


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    audio_window: AudioWindow | None = None
    previous_video: MediaInput | None = None
    motion_context: MediaInput | None = None
    image_relative: str = Field(max_length=500)
    audio_relative: str = Field(max_length=500)
    prompt: str = Field(min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    frames: Literal[17, 33, 49, 65, 81] = 81
    steps: int = Field(default=8, ge=4, le=30)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def motion_scope(self):
        if self.motion_context and (self.previous_video is None or self.audio_window is None):
            raise ValueError("Avatar motion checkpoint needs a preceding full-job video window")
        return self


def owned(root, relative):
    path = resolve_child(root, relative)
    if not relative.startswith("artifacts/") or path != root / relative:
        raise HTTPException(403, "Use owned artifacts without symlinks")
    return path


def installation():
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
    return settings, python, runtime, models, base, checkpoint


def capabilities():
    try:
        settings, python, *_ = installation()
        ready = os.access(python, os.X_OK) and bool(collect(settings.host_data_dir()).get("gpus"))
        return {
            "available": ready,
            "backend": "echomimic-v3",
            "fps": 25,
            "max_audio_seconds": 60,
            "offline": True,
        }
    except HTTPException as exc:
        return {"available": False, "backend": "echomimic-v3", "reason": exc.detail}


def start_avatar(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Avatar read/write permissions are required")
    settings, python, runtime, models, base, checkpoint = installation()
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
    if body.audio_window is not None:
        sliced = work / "audio-window.wav"
        with wave.open(str(speech), "rb") as source:
            start = body.audio_window.start_frame * rate // 25
            count = (body.frames * rate + 24) // 25 + (rate + 24) // 25
            if start >= source.getnframes():
                raise HTTPException(422, "Audio window starts beyond the canonical recording")
            source.setpos(start)
            raw = source.readframes(count)
            padding = count * channels * source.getsampwidth() - len(raw)
            raw += (b"\x80" if source.getsampwidth() == 1 else b"\x00") * padding
            with wave.open(str(sliced), "wb") as target:
                target.setparams(source.getparams())
                target.writeframes(raw)
        speech = sliced
        # Upstream derives output dimensions from the portrait's aspect ratio.
        # Full jobs need one fixed canvas across all windows and composition.
        canvas = work / "portrait-canvas.png"
        with Image.open(portrait) as image:
            ImageOps.pad(image.convert("RGB"), (body.size, body.size), color="black").save(canvas)
        portrait = canvas
    previous = owned(root, body.previous_video.relative_path) if body.previous_video else None
    if previous and (
        previous.suffix != ".mp4"
        or not previous.is_file()
        or previous.stat().st_size != body.previous_video.size_bytes
    ):
        raise HTTPException(422, "Choose a bounded owned preceding video segment")
    motion = owned(root, body.motion_context.relative_path) if body.motion_context else None
    from ai_station_runner.echo_motion import profile_key, validate_checkpoint

    profile = profile_key(runtime, models) if body.audio_window is not None else None
    if motion:
        try:
            if (
                motion.suffix != ".safetensors"
                or not motion.is_file()
                or motion.stat().st_size != body.motion_context.size_bytes
            ):
                raise ValueError("Choose a bounded owned avatar motion checkpoint")
            import hashlib

            validate_checkpoint(motion, body.size, profile)
            if hashlib.sha256(motion.read_bytes()).hexdigest() != body.motion_context.sha256:
                raise ValueError("Avatar motion checkpoint content changed")
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
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
    if previous:
        argv.extend(["--previous-video", str(previous), "--previous-hash", body.previous_video.sha256])
    if profile is not None:
        argv.extend(
            [
                "--motion-output",
                str(output.with_suffix(".safetensors")),
                "--motion-profile",
                profile,
                "--motion-relative",
                str(output.with_suffix(".safetensors").relative_to(root)),
            ]
        )
    if motion:
        argv.extend(["--motion-context", str(motion), "--motion-hash", body.motion_context.sha256])
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
    return manager.start(
        run_id=run_id,
        argv=argv,
        cwd=work,
        executor="echomimic",
        env=environment,
        **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
    )
