"""Typed offline Chatterbox adapter using the installed clone_pl.py contract."""

import json
import math
import os
import wave
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.config import get_settings
from ai_station_runner.security import resolve_child
from ai_station_runner.speech_checkpoints import selected_environment
from ai_station_runner.speech_chunks import text_chunks
from ai_station_runner.speech_chunks_job import delivery_arguments
from ai_station_runner.speech_delivery import inspect_delivery, inspect_language
from ai_station_runner.speech_runtime_schema import CheckpointSource, ManagedRuntime
from ai_station_runner.speech_selection import selection
from ai_station_runner.telemetry import collect


class SpeechDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exaggeration: float = Field(default=0.8, ge=0, le=1.5, strict=True, allow_inf_nan=False)
    cfg_weight: float = Field(default=0.4, ge=0, le=1, strict=True, allow_inf_nan=False)
    temperature: float = Field(default=0.6, ge=0.05, le=1.2, strict=True, allow_inf_nan=False)


class AudioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    text: str = Field(min_length=1, max_length=1000)
    language: Literal["pl", "en"] = "pl"
    language_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reference_relative: str = Field(max_length=500)
    gpu: int = Field(ge=0)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)
    delivery: SpeechDelivery | None = None
    delivery_source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    runtime_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    checkpoint: CheckpointSource | None = Field(default=None, exclude_if=lambda value: value is None)
    managed_runtime: ManagedRuntime | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def frozen_selection(self):
        if self.language != "pl" and not self.language_source_sha256:
            raise ValueError("A selected language requires its frozen CLI language contract")
        if (self.checkpoint is None) != (self.managed_runtime is None):
            raise ValueError("A selected speech checkpoint needs its exact managed environment")
        if self.checkpoint is not None and (
            self.deadline_at is None or self.runtime_manifest_sha256 != self.managed_runtime.manifest_sha256
        ):
            raise ValueError("Selected speech requires its absolute deadline and fixed runtime manifest")
        return self


def fitting_gpu(device):
    total = device.get("memory_total_mib")
    return type(total) in {int, float} and math.isfinite(total) and total >= 6144


def selected_source(settings, checkpoint, runtime):
    from ai_station_runner.memory_scope import available
    from ai_station_runner.speech_prepare import QUALIFIED

    if not QUALIFIED or not available():
        raise HTTPException(409, "The managed speech engine and user memory scope must be available")
    ram = (collect(settings.host_data_dir()).get("memory") or {}).get("total_mib")
    if type(ram) not in {int, float} or not math.isfinite(ram) or ram < 16384:
        raise HTTPException(409, "The selected speech workload needs at least 16 GiB physical RAM")
    try:
        return selected_environment(settings.host_data_dir(), checkpoint, runtime)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            409, "The selected speech engine or checkpoint is unavailable or changed"
        ) from exc


def capabilities(checkpoint=None, runtime=None):
    from ai_station_runner.fish_runtime import capabilities as fish_capabilities

    settings = get_settings()
    source = selected_source(settings, checkpoint, runtime) if checkpoint else selection(settings) or {}
    python, script, cache = (source.get(key) for key in ("python", "script", "cache"))
    configured = bool(
        python
        and python.is_file()
        and os.access(python, os.X_OK)
        and script
        and script.is_file()
        and cache
        and cache.is_dir()
    )
    gpus = collect(settings.host_data_dir()).get("gpus") or []
    supported = bool(gpus)
    eligible = [int(gpu["index"]) for gpu in gpus]
    if source.get("managed"):
        from ai_station_runner.memory_scope import available
        from ai_station_runner.speech_environment import fingerprint, recipe

        eligible = [int(gpu["index"]) for gpu in gpus if fitting_gpu(gpu)]
        supported = bool(eligible) and available()
        runtime_manifest = fingerprint(recipe())
    else:
        runtime_manifest = None
    language = inspect_language(script) if configured else None
    return {
        "available": configured and supported,
        "configuration_present": configured,
        "backend": "chatterbox",
        "configuration_source": "managed" if source.get("managed") else "configured",
        "eligible_gpu_indices": eligible,
        "runtime_manifest_sha256": runtime_manifest,
        **({"managed_runtime": runtime} if checkpoint else {}),
        "languages": language["languages"] if language else ["pl"],
        **({"language_selection": language} if language else {}),
        "max_text_characters": 1000,
        "reference_min_seconds": 0.1,
        "reference_max_seconds": 60,
        "offline": True,
        "delivery": inspect_delivery(script) if configured else None,
        "engines": {"fish_s2_pro": fish_capabilities()},
    }


def start_audio(manager, body):
    if set(body.permissions) != {"filesystem_read", "workspace_write"}:
        raise HTTPException(403, "Audio read/write permissions are required")
    settings = get_settings()
    source = (
        selected_source(settings, body.checkpoint, body.managed_runtime.model_dump(mode="json"))
        if body.checkpoint
        else selection(settings) or {}
    )
    python, script, cache = (source.get(key) for key in ("python", "script", "cache"))
    if not all((python, script, cache)):
        raise HTTPException(409, "Configure Chatterbox Python, script and existing offline cache")
    if body.runtime_manifest_sha256:
        from ai_station_runner.speech_environment import fingerprint, recipe

        if not source.get("managed") or body.runtime_manifest_sha256 != fingerprint(recipe()):
            raise HTTPException(409, "The selected speech runtime changed; inspect it before generating")
    if not all(value.is_file() for value in (python, script)):
        raise HTTPException(409, "Chatterbox Python or script is unavailable")
    if not cache.is_dir():
        raise HTTPException(409, "Chatterbox cache is unavailable")
    if body.delivery_source_sha256 and body.delivery is None:
        raise HTTPException(422, "A delivery snapshot requires delivery settings")
    delivery = body.delivery.model_dump() if body.delivery is not None else None
    if delivery is not None:
        inspected = inspect_delivery(script)
        if not inspected or inspected["source_sha256"] != body.delivery_source_sha256:
            raise HTTPException(409, "Speech delivery runtime changed or does not support these controls")
    if body.language_source_sha256:
        language = inspect_language(script)
        if (
            not language
            or body.language not in language["languages"]
            or language["source_sha256"] != body.language_source_sha256
        ):
            raise HTTPException(409, "Speech language runtime changed or does not support this language")
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
        str(python),
        str(script),
        "--ref",
        str(reference),
        "--text",
        body.text,
        "--out",
        str(output),
        *delivery_arguments(delivery),
        *(["--language", body.language] if body.language != "pl" else []),
    ]
    chunks = text_chunks(body.text)
    if len(chunks) > 1 and not source.get("managed"):
        work = resolve_child(root, f"runs/{run_id}/speech")
        if work != root / f"runs/{run_id}/speech" or work.exists():
            raise HTTPException(409, "Inspect existing speech work before retrying")
        work.mkdir(parents=True, mode=0o700)
        config = work / "request.json"
        config.write_text(
            json.dumps(
                {
                    "script": argv[1],
                    "reference": str(reference),
                    "output": str(output),
                    "chunks": chunks,
                    **({"delivery": delivery} if delivery is not None else {}),
                    **({"language": body.language} if body.language != "pl" else {}),
                },
                ensure_ascii=False,
            )
        )
        config.chmod(0o600)
        argv = [argv[0], str(Path(__file__).with_name("speech_chunks_job.py")), str(config)]
    environment = {
        **os.environ,
        "HF_HOME": str(cache),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": str(body.gpu),
        "PYTHONUNBUFFERED": "1",
    }
    if source.get("managed"):
        from ai_station_runner.memory_scope import scope_environment, scope_prefix
        from ai_station_runner.speech_environment import offline_environment

        if body.checkpoint:
            devices = collect(root).get("gpus", [])
            if not any(int(device["index"]) == body.gpu and fitting_gpu(device) for device in devices):
                raise HTTPException(409, "The selected speech GPU needs at least 6 GiB VRAM")
            work = resolve_child(root, f"runs/{run_id}/speech")
            if work != root / f"runs/{run_id}/speech" or work.exists():
                raise HTTPException(409, "Inspect existing selected speech work before retrying")
            work.mkdir(parents=True, mode=0o700)
            config = work / "checkpoint.json"
            config.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "deadline_at": body.deadline_at,
                        "checkpoint": body.checkpoint.model_dump(mode="json"),
                        "managed_runtime": body.managed_runtime.model_dump(mode="json"),
                    }
                )
            )
            config.chmod(0o600)
            argv.extend(("--checkpoint-request", str(config)))
        argv.extend(("--environment", str(source["environment"]), "--run-id", run_id))
        argv = [*scope_prefix(run_id, 11264), *argv]
        environment = {
            **offline_environment(source["environment"]),
            **scope_environment(),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "CUDA_VISIBLE_DEVICES": str(body.gpu),
        }
    return manager.start(
        run_id=run_id,
        argv=argv,
        cwd=root,
        executor="chatterbox",
        env=environment,
        **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
    )
