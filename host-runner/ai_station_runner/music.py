"""Owned, typed local music launch using an explicitly configured offline preset."""

import fcntl
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.config import get_settings
from ai_station_runner.music_protocol import MANIFEST_SHA256, model_manifest, no_symlink, verify_source
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import ensure_within, resolve_child
from ai_station_runner.telemetry import collect

PERMISSIONS = {"filesystem_read", "workspace_write"}
EXECUTOR = "ace_step_music"


class MusicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    caption: str = Field(min_length=1, max_length=512)
    lyrics: str = Field(default="", max_length=4096)
    instrumental: bool = True
    duration_seconds: int = Field(default=30, ge=10, le=600, strict=True)
    seed: int = Field(ge=0, le=2**31 - 1, strict=True)
    gpu: int = Field(ge=0, strict=True)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)

    @model_validator(mode="after")
    def lyrics_match_mode(self):
        if self.instrumental and self.lyrics:
            raise ValueError("Choose instrumental or supplied lyrics")
        if not self.instrumental and not self.lyrics:
            raise ValueError("Provide lyrics for a song with vocals")
        return self


def directory(run_id):
    root = get_settings().host_data_dir().resolve()
    relative = f"runtime/music/{UUID(run_id)}"
    path = resolve_child(root, relative)
    if path != root / relative:
        raise ValueError("Music runtime path must not contain symlinks")
    return path


def configured():
    settings = get_settings()
    if not all((settings.music_python, settings.music_source_dir, settings.music_model_dir)):
        raise ValueError("Configure a separate offline ACE-Step Python, source and checkpoint first")
    python = Path(settings.music_python).expanduser().absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Music Python is unavailable")
    model = no_symlink(settings.music_model_dir)
    ensure_within(model, settings.roots())
    source = no_symlink(settings.music_source_dir)
    ensure_within(source, settings.roots())
    model_manifest(model)
    verify_source(source)
    return python, source, model


@lru_cache(maxsize=8)
def runtime_ready(python, source, modified):
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import torch, torchaudio, acestep.handler, acestep.inference"
    )
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", script, str(source)],
            timeout=30,
            capture_output=True,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
                "CUDA_VISIBLE_DEVICES": "",
            },
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def capabilities():
    try:
        python, source, model = configured()
        if not runtime_ready(python, source, python.stat().st_mtime_ns):
            raise ValueError("Offline music runtime dependencies are unavailable")
        if not collect(get_settings().host_data_dir()).get("gpus"):
            raise ValueError("Local music requires an available GPU")
        return {
            "available": True,
            "profile_sha256": MANIFEST_SHA256,
            "backend": "ace-step-1.5",
            "min_seconds": 10,
            "max_seconds": 600,
            "memory_estimate_mib": 16384,
            "requires_gpu": True,
            "offline": True,
        }
    except (ValueError, OSError, KeyError, TypeError):
        return {"available": False, "reason": "Configure the approved offline ACE-Step runtime and model"}


def start(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Music requires model read and artifact write permissions")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_path = resolve_child(root, "request.lock")
    if lock_path != root / "request.lock":
        raise ValueError("Music request lock must not contain symlinks")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = resolve_child(root, "request.json")
        if request != root / "request.json":
            raise ValueError("Music request must not contain symlinks")
        if request.exists():
            if (
                request.stat().st_size > 32768
                or MusicRequest.model_validate_json(request.read_text()) != body
            ):
                raise ValueError("Run already owns a different music request")
            record = manager.inspect(run_id)
            if record["executor"] != EXECUTOR:
                raise ValueError("Run belongs to another executor")
            return record
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        python, source, model = configured()
        data_root = get_settings().host_data_dir().resolve()
        if body.gpu not in {int(device["index"]) for device in collect(data_root).get("gpus", [])}:
            raise ValueError("Requested music GPU is not present")
        output_relative = f"artifacts/{run_id[:2]}/{run_id[2:4]}/{run_id}.wav"
        output = resolve_child(data_root, output_relative)
        if output != data_root / output_relative or output.exists():
            raise ValueError("Music output exists or contains symlinks; inspect instead of overwriting")
        with request.open("x") as handle:
            os.chmod(request, 0o600)
            handle.write(body.model_dump_json())
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parent.parent), str(source)]),
            "PYTHONUNBUFFERED": "1",
            "CUDA_VISIBLE_DEVICES": str(body.gpu),
            "HF_HOME": str(root / "cache/huggingface"),
            "HF_MODULES_CACHE": str(root / "cache/modules"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "TORCH_HOME": str(root / "cache/torch"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "OMP_NUM_THREADS": "2",
            "TOKENIZERS_PARALLELISM": "false",
        }
        return manager.start(
            run_id=run_id,
            argv=[
                str(python),
                "-m",
                "ai_station_runner.music_entry",
                run_id,
                str(data_root),
                str(model),
                str(source),
            ],
            cwd=root,
            executor=EXECUTOR,
            env=environment,
        )
