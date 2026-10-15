"""Worker-owned offline transcription and portable transcript artifacts."""

import hashlib
import io
import json
import math
import tempfile
import wave
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.audio import MAX_BYTES, wav_metadata
from app.config import get_settings
from app.db import session_scope
from app.models import Artifact
from app.native_job_executor import NativeJobExecutor
from app.paths import safe_join
from app.recordings import FORMATS, recording_format
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict, transition
from app.serialize import artifact_dict
from app.state import RunStatus

router = APIRouter(prefix="/api/audio/transcription")
DB = Annotated[Session, Depends(session_scope)]


def recording(data):
    fmt = recording_format(data)
    if fmt != "wav":
        return {"input_format": fmt, "duration_validation": "pending_transcription"}
    result = wav_metadata(data, max_seconds=300)
    with wave.open(io.BytesIO(data), "rb") as source:
        if source.getsampwidth() not in {1, 2, 3, 4}:
            raise ValueError("Use 8–32 bit PCM WAV for transcription")
    return result


@router.get("/capabilities")
def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/transcription/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "device": "cpu", "reason": "Host Runner transcription is unavailable"}


@router.post("/uploads", status_code=201)
def upload(session: DB, file: Annotated[UploadFile, File()]):
    data = file.file.read(MAX_BYTES + 1)
    try:
        metadata = recording(data)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    with tempfile.NamedTemporaryFile(suffix=FORMATS[recording_format(data)][1]) as handle:
        handle.write(data)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="audio",
            mime_type=FORMATS[recording_format(data)][0],
            original_filename=Path(file.filename or "recording.wav").name[:300],
            run_id=None,
            metadata={**metadata, "source": "upload", "operation": "transcription.input"},
        )
    session.commit()
    return artifact_dict(artifact)


class TranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_artifact_id: UUID
    language: Literal["auto", "pl", "en", "de", "fr", "es", "it", "pt", "uk", "ru"] = "auto"


@router.post("/runs", status_code=202)
def generate(body: TranscriptionRequest, session: DB):
    run = create_transcription_run(session, body)
    session.commit()
    return run_dict(run)


def create_transcription_run(session, body, *, task=None, parent_run_id=None):
    source = session.get(Artifact, str(body.audio_artifact_id))
    if (
        source is None
        or source.artifact_type != "audio"
        or source.mime_type not in {value[0] for value in FORMATS.values()}
        or source.trashed_at
    ):
        raise HTTPException(422, "Choose an available audio recording")
    try:
        path = safe_join(get_settings().data_dir, source.relative_path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Recording exceeds 20 MiB")
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        recording(data)
        fmt = recording_format(data)
        if source.mime_type != FORMATS[fmt][0]:
            raise ValueError("Recording format changed since submission")
        digest = hashlib.sha256(data).hexdigest()
        if source.sha256 != digest:
            raise ValueError("Recording changed since it was saved")
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "Recording is unavailable, changed or not a supported recording") from exc
    ready = capabilities()
    if not ready.get("available") or not ready.get("profile_sha256"):
        raise HTTPException(409, ready.get("reason", "Offline transcription is unavailable"))
    if fmt not in ready.get("formats", ["wav"]):
        raise HTTPException(409, "Update the Host Runner to transcribe this recording format")
    task = task or create_task(
        session,
        title=f"Transcribe {source.original_filename}"[:100],
        prompt="Transcribe this recording locally",
        capability="audio.transcribe",
    )
    return create_run(
        session,
        task,
        run_type="audio",
        capability="audio.transcribe",
        executor_type="whisper_transcribe",
        execution_target="host",
        requested_gpu="none",
        requested_resources={"cpu_threads": 2},
        permissions=["filesystem_read", "workspace_write"],
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "source": {"relative_path": source.relative_path, "sha256": digest, "size_bytes": len(data)},
            "language": body.language,
            "input_format": fmt,
            "profile_sha256": ready["profile_sha256"],
            "parent_artifact_ids": [source.id],
        },
    )


def checked_report(run, report):
    if (
        report.get("run_id") != run.id
        or report.get("source_sha256") != run.parameters["source"]["sha256"]
        or report.get("profile_sha256") != run.parameters["profile_sha256"]
        or report.get("device") != "cpu"
        or len(json.dumps(report).encode()) > 512000
    ):
        raise ValueError("Transcript ownership or size differs from the request")
    if report.get("input_format", "wav") != run.parameters.get("input_format", "wav"):
        raise ValueError("Transcript recording format differs from the request")
    duration, segments, text = report.get("duration_seconds"), report.get("segments"), report.get("text")
    if type(duration) not in {int, float} or not math.isfinite(duration) or not 0.1 <= duration <= 300:
        raise ValueError("Invalid transcript duration")
    if (
        not isinstance(segments, list)
        or len(segments) > 2000
        or not isinstance(text, str)
        or len(text) > 100000
    ):
        raise ValueError("Invalid transcript content")
    language = report.get("language")
    if not isinstance(language, str) or not 2 <= len(language) <= 3 or not language.isalpha():
        raise ValueError("Invalid transcript language")
    previous = 0.0
    for item in segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or len(item["text"]) > 10000:
            raise ValueError("Invalid transcript segment")
        start, end = item.get("start"), item.get("end")
        if any(type(v) not in {int, float} or not math.isfinite(v) for v in (start, end)):
            raise ValueError("Invalid transcript timestamps")
        if not previous <= start <= end <= duration:
            raise ValueError("Transcript timestamps exceed the recording")
        previous = end
    if text != "\n".join(item["text"] for item in segments):
        raise ValueError("Transcript text differs from segments")
    return report


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


class TranscriptionExecutor(NativeJobExecutor):
    name = "whisper_transcribe"
    permissions = ("filesystem_read", "workspace_write")
    error_type = "TranscriptionFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "source": run.parameters["source"],
            "language": run.parameters["language"],
            "profile_sha256": run.parameters["profile_sha256"],
            "permissions": list(run.effective_permissions),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/transcription", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/transcription/{run_id}/report")

    def finish(self, session, run, report):
        checked_report(run, report)
        source = session.get(Artifact, run.parameters["parent_artifact_ids"][0])
        if source and source.sha256 == run.parameters["source"]["sha256"]:
            source.metadata_json = {
                **source.metadata_json,
                "duration_seconds": report["duration_seconds"],
                "duration_validation": "decoded",
                "validated_by_run_id": run.id,
            }
        srt = "\n\n".join(
            f"{i}\n{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text']}"
            for i, s in enumerate(report["segments"], 1)
        )
        outputs = [
            (".txt", "text", "text/plain", report["text"]),
            (".srt", "document", "application/x-subrip", srt),
            (".json", "json", "application/json", json.dumps(report, ensure_ascii=False)),
        ]
        artifacts = {}
        for suffix, kind, mime, content in outputs:
            with tempfile.NamedTemporaryFile(mode="w+", suffix=suffix, encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                artifact = register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type=kind,
                    mime_type=mime,
                    original_filename="transcript" + suffix,
                    run_id=run.id,
                    parent_artifact_ids=run.parameters["parent_artifact_ids"],
                    metadata={
                        "operation": "audio.transcribe",
                        "language": report["language"],
                        "duration_seconds": report["duration_seconds"],
                        "device": "cpu",
                    },
                )
            artifacts[suffix[1:]] = artifact.id
        run.metadata_json = {**run.metadata_json, "transcription": {**report, "artifacts": artifacts}}
        run.allocated_resources = {**run.allocated_resources, "cpu_threads": 2, "gpu": "none"}
        run.summary = f"Transcribed {report['duration_seconds']:.1f}s locally ({report['language']})."
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        if run.parameters.get("answer_after_transcription") is True:
            from app.audio_analysis import publish_answer

            publish_answer(session, run)
        return "done"
