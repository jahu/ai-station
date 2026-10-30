"""Owned video-to-effects generation and a separate inspectable sound preview."""

import math
import re
import secrets
import wave
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.effects_schema import EffectsRequest
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, Run
from app.paths import safe_join
from app.python_execution import read_owned_file
from app.resources import ResourceUnknown, reserve_gpu
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict

PROFILE = "mmaudio_large44_bf16_v1"
RAM_MIB = 18432
VRAM_MIB = 8192
router = APIRouter(prefix="/api/audio/effects", tags=["sound effects"])
DB = Annotated[Session, Depends(session_scope)]


def descriptive_fields(parameters):
    fields = {k: parameters[k] for k in ("prompt", "negative_prompt") if parameters.get(k)}
    fields.update({f"cue_{index}": cue["prompt"] for index, cue in enumerate(parameters.get("cues", []))})
    return fields


def apply_descriptions(parameters, fields):
    expected = set(descriptive_fields(parameters))
    if set(fields) != expected:
        raise ValueError("Sound description fields changed")
    output = {**parameters, **{k: v for k, v in fields.items() if not k.startswith("cue_")}}
    if parameters.get("cues"):
        output["cues"] = [
            {**cue, "prompt": fields[f"cue_{index}"]} for index, cue in enumerate(parameters["cues"])
        ]
    return output


@router.get("/capabilities")
def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/audio/effects/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {
            "available": False,
            "readiness": "unavailable",
            "reason": "Host Runner sound effects is unavailable",
        }


def video_snapshot(session, identity, *, verify=False):
    source = session.get(Artifact, str(identity))
    if (
        source is None
        or source.artifact_type != "video"
        or source.mime_type != "video/mp4"
        or source.trashed_at
        or source.purge_run_id
        or source.purged_at
    ):
        raise ValueError("Choose an available video from Library")
    original = session.get(Run, source.run_id) if source.run_id else None
    if (
        original is None
        or original.status != "succeeded"
        or original.executor_type
        not in {
            "wan_video",
            "media_compose",
            "echomimic",
            "sonic_whole",
            "effects_preview",
            "timeline_render",
        }
    ):
        raise ValueError("Choose a completed AI Station video with inspected timing")
    values = {k: source.metadata_json.get(k) for k in ("frames", "fps", "width", "height")}
    if (
        any(type(v) is not int for k, v in values.items() if k != "fps")
        or type(values["fps"]) not in (int, float)
        or values["fps"] not in (24, 25)
    ):
        raise ValueError("The video has no supported inspected timing")
    values["fps"] = int(values["fps"])
    if (
        not 1 <= values["frames"] <= 300 * values["fps"]
        or not all(128 <= values[k] <= 1280 and values[k] % 32 == 0 for k in ("width", "height"))
        or values["width"] * values["height"] > 1280 * 704
    ):
        raise ValueError("The video exceeds the five-minute effects profile")
    path = safe_join(get_settings().data_dir, source.relative_path)
    if (
        not source.relative_path.startswith("artifacts/")
        or not source.relative_path.endswith(".mp4")
        or path.stat().st_size != source.size_bytes
        or not 1 <= source.size_bytes <= 2 * 1024**3
    ):
        raise ValueError("Video changed or is unavailable")
    if verify:
        read_owned_file(source.relative_path, source.size_bytes, source.sha256, limit=2 * 1024**3)
    return {
        "relative_path": source.relative_path,
        "size_bytes": source.size_bytes,
        "sha256": source.sha256,
        **values,
    }


def verify_source(session, run):
    if video_snapshot(session, run.parameters["video_artifact_id"], verify=True) != run.parameters["video"]:
        raise ValueError("Frozen sound video changed")


def available_profile(ready):
    return bool(
        ready.get("available")
        and ready.get("profile") == PROFILE
        and ready.get("ram_mib") == RAM_MIB
        and ready.get("vram_mib") == VRAM_MIB
        and isinstance(ready.get("observation"), str)
        and re.fullmatch(r"[a-f0-9]{64}", ready["observation"])
    )


def create_effects_run(session, body, *, task=None, parent_run_id=None, observed_profile=None):
    ready = capabilities() if observed_profile is None else observed_profile
    if not available_profile(ready):
        raise HTTPException(
            409, ready.get("reason", "Sound effects is not configured or still being verified")
        )
    try:
        video = video_snapshot(session, body.video_artifact_id)
        if any(cue.end_frame > video["frames"] for cue in body.cues):
            raise ValueError("Sound cue exceeds the inspected film")
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    task = task or create_task(
        session, title=body.prompt[:80], prompt=body.prompt, capability="audio.effects"
    )
    run = create_run(
        session,
        task,
        run_type="audio",
        capability="audio.effects",
        executor_type="mmaudio_effects",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": RAM_MIB},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            **body.model_dump(mode="json", exclude={"gpu", "seed", "translation"}),
            "video": video,
            "backend": "mmaudio",
            "model": ready["model"],
            "model_revision": ready["model_revision"],
            "source_revision": ready["source_revision"],
            "profile": PROFILE,
            "observation": ready["observation"],
            "seed": body.seed if body.seed is not None else secrets.randbelow(2147483648),
            "parent_artifact_ids": [str(body.video_artifact_id)],
        },
    )
    from app.media_translation import enqueue_translation

    enqueue_translation(session, run, body.translation)
    return run


@router.post("/runs", status_code=202)
def generate(body: EffectsRequest, session: DB):
    run = create_effects_run(session, body)
    session.commit()
    return run_dict(run)


class EffectsExecutor(HostMediaExecutor):
    name = "mmaudio_effects"
    suffix = ".wav"
    artifact_type = "audio"
    mime_type = "audio/wav"

    def reserve_devices_from_hardware(self, session, run, hardware):
        devices = {int(g["index"]): g for g in hardware.get("gpus", [])}
        eligible = []
        for idx, gpu in devices.items():
            total, used = gpu.get("memory_total_mib"), gpu.get("memory_used_mib")
            if (
                all(type(v) in (int, float) and math.isfinite(v) for v in (total, used))
                and total - used >= VRAM_MIB
            ):
                eligible.append(idx)
        if run.requested_gpu != "auto":
            wanted = int(run.requested_gpu)
            if wanted not in devices or devices[wanted].get("memory_total_mib", 0) < VRAM_MIB:
                raise ResourceUnknown("Selected GPU cannot fit the sound profile")
            if wanted not in eligible:
                return None
        return reserve_gpu(session, run, eligible) if eligible else None

    def validate_inputs(self, session, run):
        from app.media_translation import validate_media_translation

        validate_media_translation(session, run)
        if run.parameters.get("media_inputs"):
            from app.agent_media import verify_published_inputs

            verify_published_inputs(session, run)
        verify_source(session, run)
        run.parameters = {
            **run.parameters,
            "execution_deadline_at": run.parameters.get("execution_deadline_at")
            or (utcnow() + timedelta(minutes=30)).isoformat(),
        }

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/effects",
            {
                "run_id": run.id,
                **{
                    k: run.parameters[k]
                    for k in ("video", "prompt", "negative_prompt", "steps", "cfg", "seed", "observation")
                },
                **({"cues": run.parameters["cues"]} if run.parameters.get("cues") else {}),
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **self.native_budget(run),
            },
        )

    def output_metadata(self, output):
        path = safe_join(get_settings().data_dir, output)
        if path.stat().st_size > 32 * 1024**2:
            raise ValueError("Effects WAV exceeds its limit")
        with wave.open(str(path)) as wav:
            frames = wav.getnframes()
            if (
                (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 44100)
                or not 1 <= frames <= 300 * 44100
                or len(wav.readframes(frames)) != frames * 2
            ):
                raise ValueError("Invalid effects PCM")
        return {"samples": frames, "sample_rate": 44100, "duration_seconds": frames / 44100, "channels": 1}

    def on_success(self, session, run, artifact):
        verify_source(session, run)
        video = run.parameters["video"]
        expected = video["frames"] * 44100 // video["fps"]
        if artifact.metadata_json.get("samples") != expected:
            raise ValueError("Effects sample count differs from the source timeline")
        if run.parameters.get("effects_mix"):
            from app.effects_mix import publish

            publish(session, run, artifact)
            return
        child = create_run(
            session,
            run.task,
            run_type="video",
            capability="video.effects_preview",
            executor_type="effects_preview",
            permissions=list(run.effective_permissions),
            requested_gpu="none",
            retry_class="inspect",
            parent_run_id=run.id,
            parameters={
                "video": video,
                "video_artifact_id": run.parameters["video_artifact_id"],
                "audio_artifact_id": artifact.id,
                "parent_artifact_ids": [run.parameters["video_artifact_id"], artifact.id],
                "execution_deadline_at": run.parameters["execution_deadline_at"],
            },
        )
        run.metadata_json = {**run.metadata_json, "effects_preview_run_id": child.id}
        from app.events import append_event

        append_event(
            session, run.id, "workflow.step.queued", {"run_id": child.id, "capability": child.capability}
        )
        from app.dependencies import depend_on

        depend_on(session, child, run)


class EffectsPreviewExecutor(HostMediaExecutor):
    name = "effects_preview"
    requires_gpu = False
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def validate_inputs(self, session, run):
        verify_source(session, run)
        a = session.get(Artifact, run.parameters["audio_artifact_id"])
        if a is None or a.trashed_at or a.purge_run_id or a.purged_at or a.run_id != run.parent_run_id:
            raise ValueError("Generated effects stem is unavailable")
        read_owned_file(a.relative_path, a.size_bytes, a.sha256, limit=32 * 1024**2)
        sound = {
            "relative_path": a.relative_path,
            "size_bytes": a.size_bytes,
            "sha256": a.sha256,
            "sample_rate": 44100,
            "samples": a.metadata_json["samples"],
        }
        if run.parameters.get("audio") is not None and run.parameters["audio"] != sound:
            raise ValueError("Frozen effects stem changed")
        run.parameters = {**run.parameters, "audio": sound}

    def _start(self, runner, run, allocated, output):
        v = run.parameters["video"]
        clip = {k: v[k] for k in ("relative_path", "size_bytes", "sha256")}
        return runner.request(
            "POST",
            "/v1/runs/effects-preview",
            {
                "run_id": run.id,
                "clips": [{**clip, "expected_frames": v["frames"], "frames": v["frames"], "first_frame": 0}],
                "fps": v["fps"],
                "width": v["width"],
                "height": v["height"],
                "target_frames": v["frames"],
                "audio": run.parameters["audio"],
                "permissions": run.effective_permissions,
                **self.native_budget(run),
            },
        )

    def output_metadata(self, output):
        import json

        path = safe_join(get_settings().data_dir, output).with_suffix(".json")
        if path.stat().st_size > 8192:
            raise ValueError("Composition report exceeds its limit")
        report = json.loads(path.read_text())
        if report.get("verified") is not True:
            raise ValueError("Sound preview was not verified")
        return report

    def on_success(self, session, run, artifact):
        self.validate_inputs(session, run)
        v = run.parameters["video"]
        if any(artifact.metadata_json.get(k) != v[k] for k in ("frames", "fps", "width", "height")):
            raise ValueError("Sound preview timing/dimensions changed")
