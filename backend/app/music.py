"""Queued local music generation, request receipts and general audio artifacts."""

import hashlib
import json
import secrets
import wave
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Run, Task
from app.paths import safe_join
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, run_dict

router = APIRouter(prefix="/api/audio/music")
DB = Annotated[Session, Depends(session_scope)]
MODEL_REVISION = "19671f406d603126926c1b7e2adc169acbcade22"
CODE_REVISION = "ca1e85fe9430179831e6bc6be790c332190a3866"
PROFILE_SHA256 = "912b4a5cd50f729d8874dcbd44776d87643f04d199b748ba3706b7181a69c658"


class MusicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_request_id: UUID
    caption: str = Field(min_length=1, max_length=512)
    lyrics: str = Field(default="", max_length=4096)
    instrumental: bool = True
    duration_seconds: int = Field(default=30, ge=10, le=600, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")

    @model_validator(mode="after")
    def lyrics_match_mode(self):
        if self.instrumental and self.lyrics:
            raise ValueError("Choose instrumental or supplied lyrics")
        if not self.instrumental and not self.lyrics:
            raise ValueError("Provide lyrics for a song with vocals")
        return self


@router.get("/capabilities")
def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/music/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Local music runtime is not configured"}


def fingerprint(body):
    payload = body.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def existing(session, body, task=None):
    task = task or session.get(Task, str(body.client_request_id))
    if task is None:
        return None
    prior = session.scalar(
        select(Run).where(Run.task_id == task.id, Run.operation_key == f"music:{body.client_request_id}")
    )
    if prior and prior.metadata_json.get("music_request_sha256") == fingerprint(body):
        return prior
    if prior or task.id == str(body.client_request_id):
        raise HTTPException(409, "Request ID already belongs to a different task or music request")
    return None


@router.post("/runs", status_code=202)
def generate(body: MusicRequest, session: DB):
    try:
        run = create_music_run(session, body)
        session.commit()
    except IntegrityError:
        session.rollback()
        run = existing(session, body)
        if run is None:
            raise HTTPException(409, "Music request changed during submission; retry this request") from None
    return run_dict(run)


def create_music_run(session, body, *, task=None, parent_run_id=None):
    prior = existing(session, body, task)
    if prior is not None:
        return prior
    ready = capabilities()
    if not ready.get("available") or ready.get("profile_sha256") != PROFILE_SHA256:
        raise HTTPException(409, ready.get("reason", "The approved local music preset is unavailable"))
    maximum = ready.get("max_seconds", 0)
    if type(maximum) is not int or not 10 <= body.duration_seconds <= min(600, maximum):
        raise HTTPException(422, "Duration exceeds this music runtime's supported limit")
    if task is None:
        task = Task(
            id=str(body.client_request_id),
            title=body.caption[:80],
            prompt=body.caption,
            capability="audio.music",
            metadata_json={},
        )
        session.add(task)
        session.flush()
    return create_run(
        session,
        task,
        run_type="audio",
        capability="audio.music",
        executor_type="ace_step_music",
        operation_key=f"music:{body.client_request_id}",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": 16384},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "caption": body.caption,
            "lyrics": body.lyrics,
            "instrumental": body.instrumental,
            "duration_seconds": body.duration_seconds,
            "seed": body.seed if body.seed is not None else secrets.randbelow(2**31),
            "backend": "ace-step-1.5",
            "model_revision": MODEL_REVISION,
            "code_revision": CODE_REVISION,
            "profile_sha256": PROFILE_SHA256,
        },
        metadata={"music_request_sha256": fingerprint(body)},
    )


def wav_metadata(path):
    if path.stat().st_size > 240 * 1024 * 1024:
        raise ValueError("Music WAV exceeds its output limit")
    try:
        with wave.open(str(path), "rb") as audio:
            rate, frames = audio.getframerate(), audio.getnframes()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if rate != 48000 or channels not in {1, 2} or width != 2 or not 10 <= frames / rate <= 601:
                raise ValueError("Music must be 48 kHz, 16-bit mono/stereo PCM, 10–600 s")
            remaining, audible = frames, False
            while remaining:
                count = min(remaining, 48000)
                block = audio.readframes(count)
                if len(block) != count * channels * width:
                    raise ValueError("Music WAV is truncated")
                audible = audible or bool(block.strip(b"\0"))
                remaining -= count
            if not audible:
                raise ValueError("Music output is entirely silent")
            return {"duration_seconds": frames / rate, "sample_rate": rate, "channels": channels}
    except (wave.Error, EOFError) as exc:
        raise ValueError("Music output is not an intact PCM WAV") from exc


class MusicExecutor(HostMediaExecutor):
    name = "ace_step_music"
    suffix = ".wav"
    artifact_type = "audio"
    mime_type = "audio/wav"

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/music",
            {
                "run_id": run.id,
                **{
                    name: run.parameters[name]
                    for name in ("caption", "lyrics", "instrumental", "duration_seconds", "seed")
                },
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
            },
        )

    def output_metadata(self, output):
        return wav_metadata(safe_join(get_settings().data_dir, output))

    def on_success(self, session, run, artifact):
        if abs(artifact.metadata_json["duration_seconds"] - run.parameters["duration_seconds"]) > 1:
            raise ValueError("Music output duration differs from the requested duration")
        artifact.title = run.parameters["caption"][:200]
        artifact.metadata_json = {**artifact.metadata_json, "actual_gpu": run.actual_gpu}
