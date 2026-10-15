"""Typed, owned CPU transcription; no model downloads or caller-selected paths."""

import fcntl
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.media_inputs import MediaInput
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.recordings import FORMATS
from ai_station_runner.security import resolve_child
from ai_station_runner.transcription_protocol import audio_bytes, profile, validate_report

PERMISSIONS = {"filesystem_read", "workspace_write"}


class TranscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    source: MediaInput
    language: Literal["auto", "pl", "en", "de", "fr", "es", "it", "pt", "uk", "ru"] = "auto"
    profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    permissions: list[str] = Field(max_length=2)


def directory(run_id):
    return resolve_child(get_settings().host_data_dir(), f"runtime/transcription/{UUID(run_id)}")


def configured():
    settings = get_settings()
    if not settings.transcription_python or not settings.transcription_model_dir:
        raise ValueError("Configure an offline Whisper runtime and model first")
    python = Path(settings.transcription_python).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Transcription Python is unavailable")
    model = Path(settings.transcription_model_dir).expanduser().resolve(strict=True)
    return python, model


@lru_cache(maxsize=8)
def runtime_ready(python, modified):
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", "import faster_whisper, av, numpy"],
            timeout=10,
            capture_output=True,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "HF_HUB_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": ""},
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def capabilities():
    try:
        python, model = configured()
        if not runtime_ready(python, python.stat().st_mtime_ns):
            raise ValueError("Transcription runtime dependencies are unavailable")
        return {
            "available": True,
            "device": "cpu",
            "profile_sha256": profile(model),
            "max_seconds": 300,
            "formats": list(FORMATS),
        }
    except (ValueError, OSError, KeyError, TypeError):
        return {
            "available": False,
            "device": "cpu",
            "reason": "Offline Whisper runtime/model is not configured or invalid",
        }


def load_request(run_id):
    path = resolve_child(directory(run_id), "request.json")
    if path.stat().st_size > 8192:
        raise ValueError("Transcription request exceeds its limit")
    body = TranscriptionRequest.model_validate_json(path.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise ValueError("Transcription request ownership changed")
    return body


def start(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Transcription requires recording read and artifact write permissions")
    root = directory(str(body.run_id))
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with resolve_child(root, "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = resolve_child(root, "request.json")
        if path.exists():
            if load_request(str(body.run_id)) != body:
                raise ValueError("Run owns another transcription request")
            record = manager.inspect(str(body.run_id))
            if record["executor"] != "whisper_transcribe":
                raise ValueError("Run belongs to another executor")
            return record
        try:
            manager.inspect(str(body.run_id))
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        python, model = configured()
        if profile(model) != body.profile_sha256:
            raise ValueError("Transcription model changed since submission")
        audio_bytes(get_settings().host_data_dir(), body.source.model_dump())
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            handle.write(body.model_dump_json())
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "PYTHONUNBUFFERED": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "CUDA_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "2",
        }
        return manager.start(
            run_id=str(body.run_id),
            argv=[
                str(python),
                "-m",
                "ai_station_runner.transcription_entry",
                str(body.run_id),
                str(get_settings().host_data_dir().resolve()),
                str(model),
            ],
            cwd=root,
            executor="whisper_transcribe",
            env=env,
        )


def report(manager, run_id):
    import json

    body = load_request(run_id)
    record = manager.inspect(run_id)
    if (
        record["executor"] != "whisper_transcribe"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record["status"] in {"canceled", "interrupted"}
    ):
        raise ValueError("Transcription has no confirmed successful completion")
    path = resolve_child(directory(run_id), "report.json")
    if path.stat().st_size > 512000:
        raise ValueError("Transcript exceeds its limit")
    return validate_report(
        json.loads(path.read_text()),
        run_id=run_id,
        source_hash=body.source.sha256,
        profile_hash=body.profile_sha256,
    )
