"""Typed offline Chatterbox adapter using the installed clone_pl.py contract."""

import os
import wave
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.security import resolve_child
from ai_station_runner.telemetry import collect


class AudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    reference_relative: str = Field(max_length=500)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)


def start_audio(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Audio read/write permissions are required")
    settings = get_settings()
    if not all((settings.chatterbox_python, settings.chatterbox_script, settings.chatterbox_cache)):
        raise HTTPException(409, "Configure Chatterbox Python, script and existing offline cache")
    if not all(
        Path(value).expanduser().is_file()
        for value in (settings.chatterbox_python, settings.chatterbox_script)
    ):
        raise HTTPException(409, "Chatterbox Python or script is unavailable")
    if not Path(settings.chatterbox_cache).expanduser().is_dir():
        raise HTTPException(409, "Chatterbox cache is unavailable")
    root = settings.host_data_dir().resolve()
    reference = resolve_child(root, body.reference_relative)
    if not body.reference_relative.startswith("artifacts/") or reference != root / body.reference_relative:
        raise HTTPException(403, "Reference must be an owned artifact without symlinks")
    try:
        if reference.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Oversized reference")
        with wave.open(str(reference), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if (
                wav.getnchannels() not in {1, 2}
                or not 8000 <= rate <= 96000
                or not 0.1 <= frames / rate <= 60
            ):
                raise ValueError("Invalid audio dimensions")
            if len(wav.readframes(frames)) != frames * wav.getnchannels() * wav.getsampwidth():
                raise ValueError("Truncated reference")
    except (OSError, wave.Error, EOFError, ValueError) as exc:
        raise HTTPException(422, "Use an intact PCM WAV reference, 0.1–60 seconds, at most 20 MiB") from exc
    if body.gpu not in {int(g["index"]) for g in collect(root).get("gpus", [])}:
        raise HTTPException(422, "GPU is not present")
    run_id = str(body.run_id)
    relative = f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
    output = resolve_child(root, relative)
    if output != root / relative:
        raise HTTPException(403, "Output must not contain symlinks")
    if output.exists():
        raise HTTPException(409, "Run output already exists; inspect it instead of overwriting")
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(Path(settings.chatterbox_python).expanduser()),
        str(Path(settings.chatterbox_script).expanduser()),
        "--ref",
        str(reference),
        "--text",
        body.text,
        "--out",
        str(output),
    ]
    environment = {
        **os.environ,
        "HF_HOME": str(Path(settings.chatterbox_cache).expanduser()),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": str(body.gpu),
        "PYTHONUNBUFFERED": "1",
    }
    return manager.start(run_id=run_id, argv=argv, cwd=root, executor="chatterbox", env=environment)
