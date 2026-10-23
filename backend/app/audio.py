"""Bounded PCM uploads and queued local Polish speech generation."""

import io
import tempfile
import wave
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.audio_schema import SpeechRequest
from app.config import get_settings
from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.paths import safe_join
from app.runs import create_run, create_task, run_dict
from app.serialize import artifact_dict

router = APIRouter(prefix="/api/audio")
DB = Annotated[Session, Depends(session_scope)]
MAX_BYTES = 20 * 1024 * 1024


def wav_metadata(data, *, max_seconds=60):
    if len(data) > MAX_BYTES:
        raise ValueError("WAV must be at most 20 MiB")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate, frames, channels = wav.getframerate(), wav.getnframes(), wav.getnchannels()
            if channels not in {1, 2} or not 8000 <= rate <= 96000 or not 0.1 <= frames / rate <= max_seconds:
                raise ValueError(f"Use mono/stereo PCM WAV, 8000–96000 Hz, 0.1–{max_seconds:g} seconds")
            if len(wav.readframes(frames)) != frames * channels * wav.getsampwidth():
                raise ValueError("Truncated WAV")
            return {"sample_rate": rate, "channels": channels, "duration_seconds": frames / rate}
    except (wave.Error, EOFError) as exc:
        raise ValueError("Use a valid PCM WAV file") from exc


@router.post("/uploads", status_code=201)
def upload(session: DB, file: Annotated[UploadFile, File()]):
    data = file.file.read(MAX_BYTES + 1)
    try:
        metadata = wav_metadata(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with tempfile.NamedTemporaryFile(suffix=".wav") as temporary:
        temporary.write(data)
        temporary.flush()
        artifact = register_file(
            session,
            source=Path(temporary.name),
            artifact_type="audio",
            mime_type="audio/wav",
            original_filename=Path(file.filename or "reference.wav").name[:300],
            run_id=None,
            metadata={**metadata, "source": "upload"},
        )
    session.commit()
    return artifact_dict(artifact)


@router.post("/runs", status_code=202)
def generate(body: SpeechRequest, session: DB):
    run = create_audio_run(session, body)
    session.commit()
    return run_dict(run)


def create_audio_run(session, body, *, task=None, parent_run_id=None):
    reference = session.get(Artifact, str(body.reference_artifact_id))
    if reference is None or reference.artifact_type != "audio" or reference.mime_type != "audio/wav":
        raise HTTPException(422, "Choose a WAV reference artifact")
    path = safe_join(get_settings().data_dir, reference.relative_path)
    try:
        with path.open("rb") as source:
            wav_metadata(source.read(MAX_BYTES + 1))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "Reference audio is unavailable or invalid") from exc
    task = task or create_task(session, title=body.text[:80], prompt=body.text, capability="audio.speech")
    run = create_run(
        session,
        task,
        run_type="audio",
        capability="audio.speech",
        executor_type="chatterbox",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "text": body.text,
            "language": "pl",
            "reference_relative": reference.relative_path,
            "parent_artifact_ids": [reference.id],
            "backend": "chatterbox",
        },
    )
    return run


class AudioExecutor(HostMediaExecutor):
    name = "chatterbox"
    suffix = ".wav"
    artifact_type = "audio"
    mime_type = "audio/wav"

    def on_success(self, session, run, artifact):
        definition = run.parameters.get("avatar_after_speech")
        if not definition:
            return
        from app.avatars import AvatarRequest, create_avatar_run
        from app.events import append_event

        if run.metadata_json.get("avatar_run_id"):
            raise ValueError("Avatar workflow already published its child")
        child = create_avatar_run(
            session,
            AvatarRequest(**definition, audio_artifact_id=artifact.id),
            task=run.task,
            parent_run_id=run.id,
        )
        child.effective_permissions = list(run.effective_permissions)
        child.triggered_by = run.triggered_by
        run.metadata_json = {**run.metadata_json, "avatar_run_id": child.id}
        append_event(
            session, run.id, "workflow.step.queued", {"run_id": child.id, "capability": child.capability}
        )

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/audio",
            {
                "run_id": run.id,
                "text": run.parameters["text"],
                "reference_relative": run.parameters["reference_relative"],
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **self.native_budget(run),
            },
        )

    def output_metadata(self, output):
        with safe_join(get_settings().data_dir, output).open("rb") as source:
            return wav_metadata(source.read(MAX_BYTES + 1), max_seconds=300)
