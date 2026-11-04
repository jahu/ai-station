"""Owned, typed local music launch using an explicitly configured offline preset."""

import fcntl
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

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
    runtime_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)

    @model_serializer(mode="wrap")
    def legacy_identity(self, handler):
        values = handler(self)
        if self.runtime_manifest_sha256 is None:
            values.pop("runtime_manifest_sha256", None)
        return values

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
    from ai_station_runner.music_selection import selection

    settings = get_settings()
    chosen = selection(settings) or {}
    if not all(chosen.get(key) for key in ("python", "source", "models")):
        raise ValueError("Configure a separate offline ACE-Step Python, source and checkpoint first")
    python, source, model = (chosen[key].absolute() for key in ("python", "source", "models"))
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Music Python is unavailable")
    model, source = no_symlink(model), no_symlink(source)
    ensure_within(model, settings.roots())
    ensure_within(source, settings.roots())
    model_manifest(
        model,
        immutable_root=settings.host_data_dir().resolve() / "models/store" if chosen.get("managed") else None,
    )
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
        hardware = collect(get_settings().host_data_dir())
        if not hardware.get("gpus"):
            raise ValueError("Local music requires an available GPU")
        from ai_station_runner.music_selection import selection

        chosen = selection(get_settings()) or {}
        eligible = [
            int(g["index"]) for g in hardware.get("gpus", []) if (g.get("memory_total_mib") or 0) >= 12288
        ]
        if chosen.get("managed") and not eligible:
            raise ValueError("The managed music profile requires an NVIDIA GPU with 12 GiB VRAM")
        return {
            "available": True,
            "configuration_source": "managed" if chosen.get("managed") else "configured",
            **(
                {
                    "runtime_manifest_sha256": chosen["observation"]["manifest_sha256"],
                    "eligible_gpu_indices": eligible,
                }
                if chosen.get("managed")
                else {}
            ),
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
        from ai_station_runner import music_environment
        from ai_station_runner.music_selection import selection

        chosen = selection(get_settings()) or {}
        managed = chosen.get("managed") is True
        if managed:
            if body.runtime_manifest_sha256 != chosen["observation"]["manifest_sha256"]:
                raise ValueError("The managed music runtime must match its frozen manifest")
            python, source, model = (chosen[key] for key in ("python", "source", "models"))
            snapshot = root / "environment.json"
            if snapshot.exists():
                frozen = music_environment.read_json(snapshot)
                chosen = music_environment.resolve(get_settings().host_data_dir(), frozen)
                python, source, model = (chosen[key] for key in ("python", "source", "models"))
            else:
                snapshot.write_text(json.dumps(chosen["observation"]))
                snapshot.chmod(0o600)
        else:
            if body.runtime_manifest_sha256:
                raise ValueError("The selected managed music runtime is no longer active")
            python, source, model = configured()
        data_root = get_settings().host_data_dir().resolve()
        devices = collect(data_root).get("gpus", [])
        if body.gpu not in {int(device["index"]) for device in devices}:
            raise ValueError("Requested music GPU is not present")
        if managed and not any(
            int(device["index"]) == body.gpu and (device.get("memory_total_mib") or 0) >= 12288
            for device in devices
        ):
            raise ValueError("The requested GPU does not fit the managed music profile")
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
        argv = [
            str(python),
            "-m",
            "ai_station_runner.music_entry",
            run_id,
            str(data_root),
            str(model),
            str(source),
        ]
        if managed:
            from ai_station_runner.memory_scope import scope_environment, scope_prefix

            argv = [*scope_prefix(run_id, 12288 if body.duration_seconds <= 60 else 18432), *argv]
            home = root / "home"
            home.mkdir(mode=0o700, exist_ok=True)
            environment = {
                **environment,
                **scope_environment(),
                "HOME": str(home),
                "NUMBA_CACHE_DIR": str(root / "cache/numba"),
            }
        return manager.start(
            run_id=run_id,
            argv=argv,
            cwd=root,
            executor=EXECUTOR,
            env=environment,
            **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
        )
