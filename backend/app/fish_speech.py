"""Expressive speech reuses ordinary media execution and offline transcription."""

import hashlib
import io
import math
import re
import wave
from datetime import timedelta

from fastapi import HTTPException

from app.audio import AudioExecutor, capabilities
from app.config import get_settings
from app.db import utcnow
from app.dependencies import depend_on
from app.models import Artifact, Run
from app.paths import safe_join
from app.python_execution import read_owned_file
from app.resources import ResourceUnknown, reserve_gpu_bundle
from app.runs import create_run, create_task

PROFILE = "fish_s2_bf16_dual_v1"
RAM_MIB = 24576


def source_snapshot(source):
    if source.trashed_at or source.purge_run_id or source.purged_at:
        raise ValueError("Voice reference is no longer available")
    path = safe_join(get_settings().data_dir, source.relative_path)
    data = read_owned_file(
        source.relative_path, source.size_bytes, source.sha256, limit=20 * 1024**2, binary=True
    )
    if not path.is_file():
        raise ValueError("Voice reference is unavailable")
    return {
        "relative_path": source.relative_path,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def transcript_text(session, snapshot, transcript):
    from app.transcription import checked_report

    if (
        transcript is None
        or transcript.status != "succeeded"
        or transcript.executor_type != "whisper_transcribe"
        or transcript.parameters.get("source") != snapshot
    ):
        raise ValueError("Voice reference transcription does not match the recording")
    report = checked_report(transcript, transcript.metadata_json.get("transcription", {}))
    artifact = session.get(Artifact, report.get("artifacts", {}).get("txt"))
    if (
        artifact is None
        or artifact.run_id != transcript.id
        or artifact.trashed_at
        or artifact.purge_run_id
        or artifact.purged_at
    ):
        raise ValueError("Voice transcript artifact is unavailable")
    text = read_owned_file(
        artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=32000, binary=True
    ).decode("utf-8")
    if not text.strip() or len(text) > 8000 or text != report["text"]:
        raise ValueError("Voice transcript differs from the verified result")
    return text


def execution_reference(session, source, transcript):
    """Bind the canonical derivative to the same intact source and ASR receipt."""
    from app.audio import wav_metadata
    from app.transcription import checked_report

    snapshot = source_snapshot(source)
    if source.mime_type == "audio/wav":
        data = read_owned_file(
            snapshot["relative_path"],
            snapshot["size_bytes"],
            snapshot["sha256"],
            limit=20 * 1024**2,
            binary=True,
        )
        wav_metadata(data)
        return snapshot
    report = checked_report(transcript, transcript.metadata_json.get("transcription", {}))
    artifact = session.get(Artifact, report.get("artifacts", {}).get("reference_wav"))
    if (
        artifact is None
        or artifact.run_id != transcript.id
        or artifact.artifact_type != "audio"
        or artifact.mime_type != "audio/wav"
        or source.id not in artifact.parent_artifact_ids
        or artifact.metadata_json.get("source_sha256") != source.sha256
        or artifact.metadata_json.get("transcription_run_id") != transcript.id
    ):
        raise ValueError("Verified voice reference WAV is unavailable")
    result = source_snapshot(artifact)
    descriptor = report.get("normalized_audio", {})
    if any(result[key] != descriptor.get(key) for key in ("sha256", "size_bytes")):
        raise ValueError("Voice reference differs from the verified transcription")
    data = read_owned_file(
        result["relative_path"], result["size_bytes"], result["sha256"], limit=20 * 1024**2, binary=True
    )
    wav_metadata(data)
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
            raise ValueError("Voice reference is not the canonical PCM WAV")
    return result


def create_fish_run(session, body, source, *, task=None, parent_run_id=None):
    ready = capabilities().get("engines", {}).get("fish_s2_pro", {})
    if (
        ready.get("available") is not True
        or ready.get("profile") != PROFILE
        or ready.get("gpu_count") != 2
        or ready.get("ram_mib") != RAM_MIB
        or not re.fullmatch(r"[a-f0-9]{64}", ready.get("observation", ""))
    ):
        raise HTTPException(
            409, ready.get("reason", "Expressive speech is not configured or still being verified")
        )
    if ready.get("environment_id"):
        eligible = ready.get("eligible_gpu_indices", [])
        primary = ready.get("primary_gpu_indices", [])
        codec = ready.get("codec_gpu_indices", [])
        if (
            not re.fullmatch(r"[a-f0-9]{64}", ready["environment_id"])
            or any(
                not isinstance(group, list) or any(type(i) is not int or i < 0 for i in group)
                for group in (eligible, primary, codec)
            )
            or not set(primary) <= set(eligible)
            or not set(codec) <= set(eligible)
            or not any(a != b for a in primary for b in codec)
        ):
            raise HTTPException(
                409, "The prepared expressive voice profile is unavailable; inspect model setup"
            )
        if body.gpu != "auto" and int(body.gpu) not in primary:
            raise HTTPException(422, "Choose Auto or a compatible primary GPU for expressive voice")
    try:
        snapshot = source_snapshot(source)
        from app.recordings import FORMATS, recording_format
        from app.transcription import recording

        data = read_owned_file(
            snapshot["relative_path"],
            snapshot["size_bytes"],
            snapshot["sha256"],
            limit=20 * 1024**2,
            binary=True,
        )
        recording(data)
        if FORMATS[recording_format(data)][0] != source.mime_type:
            raise ValueError("Voice reference format changed")
        if source.mime_type == "audio/wav":
            from app.audio import wav_metadata

            wav_metadata(data)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "Voice reference changed or is unavailable") from exc
    task = task or create_task(session, title=body.text[:80], prompt=body.text, capability="audio.speech")
    cached_id = source.metadata_json.get("validated_by_run_id")
    reference_text = None
    if cached_id:
        try:
            cached = session.get(Run, cached_id)
            text = transcript_text(session, snapshot, cached)
            execution_reference(session, source, cached)
            reference_text = text
        except (ValueError, OSError, UnicodeError):
            pass  # An unavailable old transcript can be safely recreated from the owned recording.
    parameters = {
        "text": body.text,
        "language": "auto",
        "backend": "fish_s2_pro",
        "profile": PROFILE,
        "observation": ready["observation"],
        "direction": body.direction or "natural",
        "pace": body.pace or "natural",
        "reference": snapshot,
        "reference_artifact_id": source.id,
        "parent_artifact_ids": [source.id],
        **(
            {
                "environment_id": ready["environment_id"],
                "eligible_gpu_indices": ready.get("eligible_gpu_indices", []),
                "primary_gpu_indices": ready.get("primary_gpu_indices", []),
                "codec_gpu_indices": ready.get("codec_gpu_indices", []),
            }
            if ready.get("environment_id")
            else {}
        ),
    }
    if reference_text:
        parameters["reference_transcription_run_id"] = cached_id
        parameters["reference_text"] = reference_text
        parameters["reference_text_provenance"] = {
            "kind": "cached_asr",
            "run_id": cached_id,
            "sha256": source.sha256,
        }
    else:
        from app.transcription import TranscriptionRequest, create_transcription_run

        transcript = create_transcription_run(
            session,
            TranscriptionRequest(audio_artifact_id=source.id),
            task=task,
            parent_run_id=parent_run_id,
            normalize_reference=source.mime_type != "audio/wav",
        )
        parameters["reference_transcription_run_id"] = transcript.id
        parameters["reference_text_provenance"] = {
            "kind": "asr",
            "run_id": transcript.id,
            "sha256": source.sha256,
        }
    run = create_run(
        session,
        task,
        run_type="audio",
        capability="audio.speech",
        executor_type="fish_speech",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": RAM_MIB, "gpu_count": 2},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters=parameters,
    )
    if not reference_text:
        depend_on(session, run, transcript)
    return run


def resolve_reference_text(session, run):
    source = session.get(Artifact, run.parameters["reference_artifact_id"])
    if source is None or source_snapshot(source) != run.parameters["reference"]:
        raise ValueError("Frozen voice reference changed or is unavailable")
    transcription_id = run.parameters["reference_transcription_run_id"]
    transcript = session.get(Run, transcription_id)
    provenance = run.parameters["reference_text_provenance"]
    if (
        provenance.get("run_id") != transcription_id
        or provenance.get("sha256") != source.sha256
        or provenance.get("kind") not in {"asr", "cached_asr"}
        or transcript is None
        or provenance["kind"] == "asr"
        and transcript.task_id != run.task_id
    ):
        raise ValueError("Voice reference transcription is not the frozen prerequisite")
    text = transcript_text(session, run.parameters["reference"], transcript)
    frozen = run.parameters.get("reference_text")
    if frozen is not None and frozen != text:
        raise ValueError("Frozen voice transcript changed")
    selected = execution_reference(session, source, transcript)
    if run.parameters.get("execution_reference", selected) != selected:
        raise ValueError("Frozen canonical voice reference changed")
    return text


class FishSpeechExecutor(AudioExecutor):
    name = "fish_speech"

    def reserve_devices_from_hardware(self, session, run, hardware):
        if run.parameters.get("environment_id"):
            eligible = run.parameters.get("eligible_gpu_indices", [])
            hardware = {
                **hardware,
                "gpus": [g for g in hardware.get("gpus", []) if int(g["index"]) in eligible],
            }
        devices = {}
        for gpu in hardware.get("gpus", []):
            total, used = gpu.get("memory_total_mib"), gpu.get("memory_used_mib")
            if all(
                type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in (total, used)
            ):
                devices[int(gpu["index"])] = total - used
        all_ids = {int(gpu["index"]) for gpu in hardware.get("gpus", [])}
        if len(all_ids) < 2:
            raise ResourceUnknown("This speech profile needs two discovered GPUs")
        if run.requested_gpu != "auto" and int(run.requested_gpu) not in all_ids:
            raise ResourceUnknown("Requested speech GPU is not present")
        if run.requested_gpu != "auto":
            requested = next(g for g in hardware["gpus"] if int(g["index"]) == int(run.requested_gpu))
            total = requested.get("memory_total_mib")
            if type(total) in (int, float) and total < 10240:
                raise ResourceUnknown(
                    "The selected speech GPU cannot fit this profile; choose Auto or a larger primary GPU"
                )
        ordered = sorted(devices, key=devices.get, reverse=True)
        for primary in ordered:
            if run.parameters.get("environment_id") and primary not in run.parameters["primary_gpu_indices"]:
                continue
            if devices[primary] < 10240 or (
                run.requested_gpu != "auto" and primary != int(run.requested_gpu)
            ):
                continue
            for secondary in ordered:
                if (
                    run.parameters.get("environment_id")
                    and secondary not in run.parameters["codec_gpu_indices"]
                ):
                    continue
                if secondary == primary or devices[secondary] < 5120:
                    continue
                selected = reserve_gpu_bundle(session, run, [primary, secondary], 2)
                if selected is not None:
                    return selected
        return None

    def validate_inputs(self, session, run):
        super().validate_inputs(session, run)
        text = resolve_reference_text(session, run)
        selected = execution_reference(
            session,
            session.get(Artifact, run.parameters["reference_artifact_id"]),
            session.get(Run, run.parameters["reference_transcription_run_id"]),
        )
        run.parameters = {
            **run.parameters,
            "reference_text": text,
            **({"execution_reference": selected} if selected != run.parameters["reference"] else {}),
            "execution_deadline_at": run.parameters.get("execution_deadline_at")
            or (utcnow() + timedelta(minutes=30)).isoformat(),
        }

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/fish-speech",
            {
                "run_id": run.id,
                "text": run.parameters["text"],
                "direction": run.parameters["direction"],
                "pace": run.parameters["pace"],
                "reference": run.parameters.get("execution_reference", run.parameters["reference"]),
                "reference_text": run.parameters["reference_text"],
                "observation": run.parameters["observation"],
                "gpus": [int(device) for device in run.allocated_resources["gpus"]],
                "permissions": run.effective_permissions,
                **self.native_budget(run),
                **(
                    {"environment_id": run.parameters["environment_id"]}
                    if run.parameters.get("environment_id")
                    else {}
                ),
            },
        )

    def on_success(self, session, run, artifact):
        resolve_reference_text(session, run)
        artifact.metadata_json = {
            **artifact.metadata_json,
            "speech_engine": "fish_s2_pro",
            "direction": run.parameters["direction"],
            "pace": run.parameters["pace"],
            "profile": PROFILE,
            "observation": run.parameters["observation"],
            "attribution": "Built with Fish Audio",
            **(
                {"environment_id": run.parameters["environment_id"]}
                if run.parameters.get("environment_id")
                else {}
            ),
        }
        super().on_success(session, run, artifact)
