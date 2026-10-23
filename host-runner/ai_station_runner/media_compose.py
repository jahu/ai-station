"""Typed CPU composition of proven app-owned media; never accepts codec/filter argv."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ai_station_runner.avatars import owned
from ai_station_runner.config import get_settings
from ai_station_runner.media_inputs import MediaInput


class ClipInput(MediaInput):
    expected_frames: StrictInt = Field(ge=1, le=7500)
    first_frame: StrictInt = Field(default=0, ge=0, le=7499)
    frames: StrictInt = Field(ge=1, le=7500)

    @model_validator(mode="after")
    def interval(self):
        if self.first_frame + self.frames > self.expected_frames:
            raise ValueError("Clip interval exceeds the verified video")
        return self


class AudioInput(MediaInput):
    samples: StrictInt = Field(ge=1, le=96000 * 300)
    sample_rate: StrictInt = Field(ge=8000, le=96000)


class ComposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    clips: list[ClipInput] = Field(min_length=1, max_length=256)
    fps: Literal[24, 25]
    width: StrictInt = Field(ge=128, le=1280, multiple_of=32)
    height: StrictInt = Field(ge=128, le=1280, multiple_of=32)
    target_frames: StrictInt = Field(ge=1, le=7500)
    audio: AudioInput | None = None
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def bounds(self):
        if (
            sum(clip.expected_frames for clip in self.clips) > 20000
            or sum(clip.size_bytes for clip in self.clips) > 8 * 1024**3
        ):
            raise ValueError("Composition inputs exceed the bounded decode budget")
        if self.width * self.height > 1280 * 704 or sum(c.frames for c in self.clips) != self.target_frames:
            raise ValueError("Invalid bounded output dimensions or frame count")
        if (
            self.audio
            and self.target_frames
            != (self.audio.samples * self.fps + self.audio.sample_rate - 1) // self.audio.sample_rate
        ):
            raise ValueError("Video must cover the complete canonical audio")
        return self


def verified_path(root, body, *, verify_hash=True):
    path = owned(root, body.relative_path)
    if not path.is_file() or path.stat().st_size != body.size_bytes:
        raise HTTPException(422, "Media observation changed")
    if not verify_hash:
        return path
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != body.sha256:
        raise HTTPException(422, "Media content changed")
    return path


def start_composition(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Media read/write permissions are required")
    settings = get_settings()
    if not settings.video_python:
        raise HTTPException(409, "Configure the existing video Python environment with PyAV")
    python = Path(settings.video_python).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise HTTPException(409, "Video Python is unavailable")
    root = settings.host_data_dir().resolve()
    for clip in body.clips:
        if not clip.relative_path.endswith(".mp4"):
            raise HTTPException(422, "Choose owned MP4 clips")
        verified_path(root, clip, verify_hash=False)
    if body.audio:
        if not body.audio.relative_path.endswith(".wav"):
            raise HTTPException(422, "Choose canonical PCM WAV")
        verified_path(root, body.audio, verify_hash=False)
    run_id = str(body.run_id)
    work = root / "runs" / run_id / "compose"
    if work.resolve() != work or work.exists():
        raise HTTPException(409, "Inspect existing composition work")
    output = owned(root, f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.mp4")
    if output.exists():
        raise HTTPException(409, "Composition output already exists")
    work.mkdir(parents=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = work / "request.json"
    config.write_text(
        json.dumps({"request": body.model_dump(mode="json"), "root": str(root), "output": str(output)})
    )
    config.chmod(0o600)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "PYTHONPATH", "LD_LIBRARY_PATH"}
    }
    environment.update(
        CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", TMPDIR=str(work)
    )
    return manager.start(
        run_id=run_id,
        argv=[str(python), str(Path(__file__).with_name("media_compose_job.py")), str(config)],
        cwd=work,
        executor="media_compose",
        env=environment,
        **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
    )
