"""Durable speech → measured score → soundtrack steps using existing local generators."""

import hashlib
import math
import os
import stat
import tempfile
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.artifacts import register_file
from app.audio import MAX_BYTES, create_audio_run
from app.audio_schema import SpeechRequest
from app.config import get_settings
from app.db import utcnow
from app.dependencies import depend_on
from app.heartbeat import cancel_expired_run
from app.models import Artifact, Run
from app.music import MusicRequest, create_music_run
from app.paths import safe_join
from app.permissions import require
from app.runs import create_run, create_task, run_dict, transition
from app.runtime_readiness import CapabilityChecking
from app.state import RunStatus
from app.studio_mastering import PROFILE as MASTERING_PROFILE
from app.studio_materials import DB, digest, get_material, get_revision
from app.studio_pcm import timed_storyboard
from app.studio_schema import Fields, NarrationDelivery, Storyboard
from app.studio_soundtrack import MixRequest, audio_source, create_soundtrack_run, router
from app.task_control import cancel_task, lock_task

PERMISSIONS = ["filesystem_read", "workspace_write"]


class Voice(NarrationDelivery):
    engine: Literal["fish_s2_pro", "chatterbox"] = "fish_s2_pro"
    reference_artifact_id: UUID | None = None
    model_id: UUID | None = None
    language: Literal["en", "pl"] = "en"

    @model_validator(mode="after")
    def compatible(self):
        if self.engine == "chatterbox" and self.reference_artifact_id is None:
            raise ValueError("Choose a voice recording for Chatterbox")
        if self.engine == "fish_s2_pro" and self.model_id is not None:
            raise ValueError("Chatterbox model choices cannot change the expressive voice engine")
        if self.engine == "chatterbox" and (self.direction != "natural" or self.pace != "natural"):
            raise ValueError("Speaking direction/pace require expressive speech")
        return self

    def request(self, text, reference):
        values = {"text": text, "reference_artifact_id": reference, "level_volume": True}
        if self.engine == "fish_s2_pro":
            values.update(
                engine=self.engine,
                voice_source="reference" if reference else "model",
                direction=self.direction,
                pace=self.pace,
            )
        else:
            values.update(model_id=self.model_id, language=self.language)
        return SpeechRequest.model_validate(values)


class ProduceAudio(Fields):
    client_request_id: UUID
    revision_id: UUID
    reuse_from_run_id: UUID | None = None
    voice: Voice | None = None
    music_model_id: UUID | None = None
    music_caption: str | None = Field(default=None, min_length=1, max_length=512)
    music_gain: float = Field(default=0.22, ge=0.01, le=1.0, allow_inf_nan=False, strict=True)
    duck: float = Field(default=0.28, ge=0.05, le=1.0, allow_inf_nan=False, strict=True)


def create_audio_production(session, material_id, body):
    row = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, row, body.revision_id)
    plan = Storyboard.model_validate(revision.storyboard)
    if plan.audio == "silent":
        raise HTTPException(422, "This saved version is intentionally silent")
    score = body.music_caption or plan.music_brief
    if plan.audio in {"music", "voice_music"} and not 1 <= len(score) <= 512:
        raise HTTPException(422, "Review the music direction within 512 characters before production")
    key = "studio-audio:" + str(body.client_request_id)
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id"}))
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key, Run.parameters["studio_material_id"].as_string() == row.id
        )
    )
    if prior:
        if prior.parameters.get("request_sha256") != fingerprint:
            raise HTTPException(409, "This audio production receipt belongs to another request")
        return prior
    active = session.scalar(
        select(Run.id)
        .where(
            Run.parameters["studio_material_id"].as_string() == row.id,
            Run.parameters["studio_revision_id"].as_string() == revision.id,
            Run.parameters["studio_audio_root_id"].as_string().is_not(None),
            Run.status.not_in({"succeeded", "failed", "interrupted", "canceled"}),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(409, "Sound production is already active for this saved version")
    if body.voice is None:
        body = body.model_copy(update={"voice": Voice(**plan.narration_delivery.model_dump())})
    reference = None
    if body.voice.reference_artifact_id:
        try:
            reference = audio_source(session, body.voice.reference_artifact_id)
            if (
                not 0.1 <= reference["samples"] / reference["sample_rate"] <= 60
                or reference["size_bytes"] > MAX_BYTES
            ):
                raise ValueError("Choose a narrator recording of 0.1–60 seconds within 20 MiB")
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
    voices, music, reused = reusable_audio(session, body, plan) if body.reuse_from_run_id else ({}, None, {})
    task = create_task(
        session, title="Produce sound · " + row.title, prompt=revision.brief, capability="studio.audio"
    )
    run = create_run(
        session,
        task,
        run_type="planning",
        capability="studio.audio",
        executor_type="studio_audio_step",
        execution_target="container",
        operation_key=key,
        permissions=list(PERMISSIONS),
        retry_class="safe",
        parameters={
            "studio_material_id": row.id,
            "studio_revision_id": revision.id,
            "revision_sha256": digest(revision.storyboard),
            "request_sha256": fingerprint,
            "request": body.model_dump(mode="json"),
            "music_caption": score,
            "mastering_profile": MASTERING_PROFILE,
            "reference_snapshot": reference,
            "voice_artifacts": voices,
            "reused_music_artifact_id": music,
            "reused_audio_sources": reused,
            "pending": None,
            "execution_deadline_at": (utcnow() + timedelta(hours=4)).isoformat(),
        },
        metadata={"studio_enqueue_only": True},
    )
    run.parameters = {**run.parameters, "studio_audio_root_id": run.id}
    task.metadata_json = {**task.metadata_json, "studio_audio_root_id": run.id}
    return run


@router.post("/{material_id}/audio/produce", status_code=202)
def produce(material_id: UUID, body: ProduceAudio, session: DB):
    run = create_audio_production(session, material_id, body)
    session.commit()
    return run_dict(run)


def reusable_audio(session, body, plan):
    previous = session.get(Run, str(body.reuse_from_run_id))
    if not (
        previous
        and previous.executor_type == "studio_audio_step"
        and previous.parameters.get("studio_audio_root_id") == previous.id
        and previous.parameters.get("studio_revision_id") == str(body.revision_id)
        and previous.parameters.get("revision_sha256") == digest(plan.model_dump(mode="json"))
    ):
        raise HTTPException(404, "Choose an owned audio production of this saved script")
    if previous.parameters.get("reference_snapshot"):
        reference = previous.parameters["reference_snapshot"]
        if audio_source(session, reference["artifact_id"]) != reference:
            raise HTTPException(409, "The original narrator reference changed")
    old = ProduceAudio.model_validate(previous.parameters["request"])
    excluded = {"client_request_id", "reuse_from_run_id"}
    if old.model_dump(mode="json", exclude=excluded) != body.model_dump(mode="json", exclude=excluded):
        raise HTTPException(409, "Audio reuse requires the same narrator, score and mix settings")
    stages = list(
        session.scalars(select(Run).where(Run.task_id == previous.task_id).order_by(Run.created_at, Run.id))
    )
    if any(r.status not in {"succeeded", "failed", "interrupted", "canceled"} for r in stages):
        raise HTTPException(409, "Stop the previous sound production before continuing it")
    voices, music, sources = {}, None, {}
    for stage in stages:
        if stage.executor_type != "studio_audio_step":
            continue
        candidates = dict(stage.parameters.get("voice_artifacts", {}))
        pending = stage.parameters.get("pending")
        if pending and pending["kind"] in {"voice", "music"}:
            try:
                identity = completed_audio(session, stage, previous, pending, verify=False)
                if pending["kind"] == "voice":
                    candidates[str(pending["scene"])] = identity
                else:
                    music = identity
            except (ValueError, OSError):
                pass
        for scene, identity in candidates.items():
            try:
                source = audio_source(session, identity)
                item = session.get(Artifact, identity)
                origin = session.get(Run, item.run_id) if item.run_id else None
                if (
                    not origin
                    or origin.status != "succeeded"
                    or item.metadata_json.get("partial")
                    or item.metadata_json.get("internal_media")
                ):
                    continue
                voices[scene] = identity
                sources[identity] = source
            except (ValueError, OSError):
                continue
    if music and set(voices) == {str(i) for i, s in enumerate(plan.scenes) if s.narration}:
        sources[music] = audio_source(session, music)
    else:
        music = None
    return voices, music, sources


def completed_audio(session, stage, root, pending, *, verify=True):
    child = session.get(Run, pending["run_id"])
    if (
        child is None
        or child.task_id != root.task_id
        or child.status != "succeeded"
        or child.parameters.get("studio_audio_root_id") != root.id
    ):
        raise ValueError("The owned audio prerequisite is unfinished or changed")
    outputs = list(
        session.scalars(
            select(Artifact).where(
                Artifact.run_id == child.id,
                Artifact.artifact_type == "audio",
                Artifact.mime_type == "audio/wav",
                Artifact.trashed_at.is_(None),
                Artifact.purged_at.is_(None),
                Artifact.purge_run_id.is_(None),
            )
        )
    )
    outputs = [
        a
        for a in outputs
        if not a.metadata_json.get("partial")
        and (
            a.metadata_json.get("studio_voice_reference") is True
            if pending["kind"] == "reference"
            else not a.metadata_json.get("internal_media")
        )
    ]
    if len(outputs) != 1:
        raise ValueError("Audio production requires exactly one complete owned PCM result")
    audio_source(session, outputs[0].id, verify=verify)
    return outputs[0].id


def tag_children(session, stage, root):
    for child in session.scalars(
        select(Run).where(Run.task_id == stage.task_id, Run.parent_run_id == stage.id)
    ):
        expiry = min(
            datetime.fromisoformat(
                child.parameters.get("execution_deadline_at", root.parameters["execution_deadline_at"])
            ),
            datetime.fromisoformat(root.parameters["execution_deadline_at"]),
        )
        child.parameters = {
            **child.parameters,
            "studio_material_id": root.parameters["studio_material_id"],
            "studio_revision_id": root.parameters["studio_revision_id"],
            "studio_audio_root_id": root.id,
            "execution_deadline_at": expiry.isoformat(),
        }


def continuation(session, stage, root, voices, child, kind, scene=None, voice_reference=None):
    next_step = create_run(
        session,
        stage.task,
        run_type="planning",
        capability="studio.audio",
        executor_type="studio_audio_step",
        execution_target="container",
        operation_key="studio-audio-step:" + stage.id,
        parent_run_id=stage.id,
        retry_class="safe",
        permissions=list(PERMISSIONS),
        metadata={"studio_enqueue_only": True},
        parameters={
            "studio_material_id": root.parameters["studio_material_id"],
            "studio_revision_id": root.parameters["studio_revision_id"],
            "studio_audio_root_id": root.id,
            "voice_artifacts": voices,
            "voice_reference_id": voice_reference,
            "pending": {"kind": kind, "scene": scene, "run_id": child.id},
            "execution_deadline_at": root.parameters["execution_deadline_at"],
        },
    )
    depend_on(session, next_step, child)
    stage.metadata_json = {**stage.metadata_json, "audio_run_id": child.id, "next_step_id": next_step.id}


class StudioAudioStepExecutor:
    name = "studio_audio_step"

    def execute(self, session, run):
        claim = (run.worker_id, run.claimed_at)
        try:
            return self.publish(session, run)
        except CapabilityChecking as exc:
            # These publishers validate readiness before creating any child.
            # Roll back the publication transaction, then reacquire the Task
            # fence: Stop or stale-claim recovery may have won in the meantime.
            session.rollback()
            lock_task(session, run.task)
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim or run.status not in {"running", "cancel_requested"}:
                return "done"
            if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return "done"
            now = utcnow()
            key = "studio_audio_verification"
            previous = run.metadata_json.get(key, {})
            started = previous.get("started_at") if previous.get("capability") == exc.capability else None
            if started and now - datetime.fromisoformat(started) >= timedelta(minutes=5):
                raise ValueError(
                    "Audio model verification did not finish; inspect model readiness before continuing"
                ) from exc
            run.metadata_json = {
                **run.metadata_json,
                key: {"capability": exc.capability, "started_at": started or now.isoformat()},
            }
            from app.resources import defer_resource_run

            defer_resource_run(run)
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="studio.audio.verifying",
                payload={"capability": exc.capability, "reason": exc.detail},
            )
            run.worker_id = None
            run.lease_expires_at = None
            run.finished_at = None
            transition(
                session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"queue_only": True}
            )
            session.commit()
            return "done"

    def publish(self, session, run):
        for permission in PERMISSIONS:
            require(run.effective_permissions, permission)
        claim = (run.worker_id, run.claimed_at)
        lock_task(session, run.task)
        session.refresh(run)
        if (run.worker_id, run.claimed_at) != claim:
            return "done"
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        root = session.get(Run, run.parameters["studio_audio_root_id"])
        if root is None or root.executor_type != self.name or root.task_id != run.task_id:
            raise ValueError("Audio production root ownership changed")
        body = ProduceAudio.model_validate(root.parameters["request"])
        row = get_material(session, root.parameters["studio_material_id"])
        revision = get_revision(session, row, root.parameters["studio_revision_id"])
        if digest(revision.storyboard) != root.parameters["revision_sha256"]:
            raise ValueError("The saved audio script changed")
        plan = Storyboard.model_validate(revision.storyboard)
        if body.voice is None:
            raise ValueError("The frozen narrator configuration is missing")
        if (
            body.voice.reference_artifact_id
            and audio_source(session, body.voice.reference_artifact_id, verify=True)
            != root.parameters["reference_snapshot"]
        ):
            raise ValueError("The selected narrator reference changed before production")
        if run.id == root.id:
            for identity, frozen in root.parameters.get("reused_audio_sources", {}).items():
                if audio_source(session, identity, verify=True) != frozen:
                    raise ValueError("A reused sound source changed before continuation")
        voices = dict(run.parameters["voice_artifacts"])
        pending = run.parameters.get("pending")
        music = root.parameters.get("reused_music_artifact_id")
        voice_reference = run.parameters.get("voice_reference_id")
        if pending:
            result = completed_audio(session, run, root, pending)
            if pending["kind"] == "voice":
                voices[str(pending["scene"])] = result
            elif pending["kind"] == "music":
                music = result
            elif pending["kind"] == "reference":
                voice_reference = result
            else:
                raise ValueError("Unknown Studio audio prerequisite")
        # Serialize durable queue publication with Task Stop and stale claims.
        session.commit()
        lock_task(session, run.task)
        session.refresh(run)
        if (run.worker_id, run.claimed_at) != claim or run.status not in {"running", "cancel_requested"}:
            return "done"
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        next_scene = next(
            (i for i, shot in enumerate(plan.scenes) if shot.narration and str(i) not in voices), None
        )
        if next_scene is not None:
            # A generated first voice becomes the same reference for every later
            # cue, rather than re-rolling the narrator for each shot.
            reference = (
                str(body.voice.reference_artifact_id)
                if body.voice.reference_artifact_id
                else voice_reference or next(iter(voices.values()), None)
            )
            source = audio_source(session, reference) if reference else None
            if source and (
                source["samples"] > 60 * source["sample_rate"] or source["size_bytes"] > MAX_BYTES
            ):
                child = create_run(
                    session,
                    run.task,
                    run_type="audio",
                    capability="audio.reference",
                    executor_type=StudioVoiceReferenceExecutor.name,
                    execution_target="container",
                    parent_run_id=run.id,
                    operation_key="studio-voice-reference:" + root.id,
                    permissions=list(PERMISSIONS),
                    retry_class="safe",
                    requested_gpu="none",
                    requested_resources={"ram_mib": 128},
                    parameters={"source": source},
                )
                continuation(session, run, root, voices, child, "reference")
            else:
                child = create_audio_run(
                    session,
                    body.voice.request(plan.scenes[next_scene].narration, reference),
                    task=run.task,
                    parent_run_id=run.id,
                )
                continuation(session, run, root, voices, child, "voice", next_scene, voice_reference)
        elif plan.audio in {"music", "voice_music"} and music is None:
            measured = timed_storyboard(plan, {int(i): audio_source(session, a) for i, a in voices.items()})
            child = create_music_run(
                session,
                MusicRequest(
                    client_request_id=uuid5(UUID(run.id), "score"),
                    caption=root.parameters["music_caption"],
                    duration_seconds=max(10, math.ceil(measured.frames / 30)),
                    instrumental=True,
                    model_id=body.music_model_id,
                ),
                task=run.task,
                parent_run_id=run.id,
            )
            continuation(session, run, root, voices, child, "music", voice_reference=voice_reference)
        else:
            child = create_soundtrack_run(
                session,
                row.id,
                MixRequest(
                    client_request_id=uuid5(UUID(root.id), "final-mix"),
                    revision_id=revision.id,
                    narration=[{"scene": int(i), "artifact_id": a} for i, a in voices.items()],
                    music_artifact_id=music,
                    music_gain=body.music_gain,
                    duck=body.duck,
                ),
                task=run.task,
                parent_run_id=run.id,
                default_mastering=root.parameters.get("mastering_profile"),
            )
            run.task.metadata_json = {**run.task.metadata_json, "studio_mix_run_id": child.id}
            run.metadata_json = {**run.metadata_json, "mix_run_id": child.id}
        tag_children(session, run, root)
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=run.metadata_json)
        session.commit()
        return "done"


@router.post("/{material_id}/audio/{run_id}/stop")
def stop_audio(material_id: UUID, run_id: UUID, session: DB):
    row = get_material(session, material_id)
    root = session.get(Run, str(run_id))
    if (
        root is None
        or root.executor_type != "studio_audio_step"
        or root.parameters.get("studio_material_id") != row.id
    ):
        raise HTTPException(404, "Studio audio production not found")
    result = cancel_task(session, root.task)
    session.commit()
    return result


def recover_enqueue_step(session, run):
    """Replay only transactional queue publication, never native speech/music work."""
    if (
        run.metadata_json.get("studio_enqueue_only") is not True
        or run.metadata_json.get("dispatch_attempted")
        or run.pid
        or run.process_group_id
    ):
        return False
    key = {
        "studio_audio_step": "studio_audio_root_id",
        "studio_production_step": "studio_production_root_id",
    }.get(run.executor_type)
    if run.executor_type == "assistant_studio":
        from app.assistant_controller import verify_wrapper

        try:
            verify_wrapper(session, run)
        except ValueError:
            return False
        root = run
    else:
        root = session.get(Run, run.parameters.get(key, "")) if key else None
    if (
        root is None
        or root.executor_type != run.executor_type
        or root.task_id != run.task_id
        or root.owner_id != run.owner_id
    ):
        return False
    lock_task(session, run.task)
    session.refresh(run)
    if (
        run.status not in {"claimed", "preparing", "running", "cancel_requested"}
        or run.lease_expires_at is None
        or run.lease_expires_at >= utcnow()
    ):
        return True  # A live owner renewed/completed while the recovery lock waited.
    if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
    else:
        transition(session, run, RunStatus.INTERRUPTED, event_type="studio.queue_publication_recovered")
        run.worker_id = None
        run.lease_expires_at = None
        run.finished_at = None
        transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"queue_only": True})
    return True


@router.get("/{material_id}/audio/productions")
def productions(material_id: UUID, session: DB, revision_id: UUID | None = None):
    from app.serialize import artifact_dict

    row = get_material(session, material_id)
    if revision_id:
        get_revision(session, row, revision_id)
    roots = list(
        session.scalars(
            select(Run)
            .where(
                Run.executor_type == "studio_audio_step",
                Run.parameters["studio_material_id"].as_string() == row.id,
                Run.parameters["studio_audio_root_id"].as_string() == Run.id,
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(20)
        )
    )
    result = []
    terminal = {"succeeded", "failed", "interrupted", "canceled"}
    for root in roots:
        runs = list(
            session.scalars(
                select(Run).where(Run.task_id == root.task_id).order_by(Run.created_at, Run.id).limit(400)
            )
        )
        mixed = next(
            (r for r in runs if r.executor_type == "studio_soundtrack" and r.status == "succeeded"), None
        )
        measured = mixed.metadata_json.get("studio_revision_id") if mixed else None
        if revision_id and str(revision_id) not in {root.parameters["studio_revision_id"], measured}:
            continue
        artifact = session.get(Artifact, mixed.metadata_json.get("soundtrack_artifact_id")) if mixed else None
        if artifact and (
            artifact.run_id != mixed.id or artifact.trashed_at or artifact.purged_at or artifact.purge_run_id
        ):
            artifact = None
        active = [r for r in runs if r.status not in terminal]
        failed = next((r for r in runs if r.status in {"failed", "interrupted", "canceled"}), None)
        stopped = root.task.metadata_json.get("stop_requested_at")
        status = (
            ("cancel_requested" if active else "canceled")
            if stopped
            else "succeeded"
            if artifact
            else "failed"
            if failed
            else "running"
            if active
            else "interrupted"
        )
        result.append(
            {
                "root_run": run_dict(root),
                "status": status,
                "runs": [run_dict(r) for r in runs],
                "active_run_ids": [r.id for r in active],
                "failed_run": run_dict(failed) if failed else None,
                "soundtrack": artifact_dict(artifact) if artifact else None,
                "measured_revision_id": measured,
            }
        )
    return result


class StudioVoiceReferenceExecutor:
    """A bounded lossless voice sample; the complete spoken passage stays intact."""

    name = "studio_voice_reference"

    def execute(self, session, run):
        for permission in PERMISSIONS:
            require(run.effective_permissions, permission)
        claim = run.worker_id, run.claimed_at
        last = 0.0

        def live(force=False):
            nonlocal last
            if not force and time.monotonic() - last < 0.25:
                return True
            last = time.monotonic()
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim or run.status not in {
                "claimed",
                "preparing",
                "running",
                "cancel_requested",
            }:
                session.rollback()
                return False
            cancel_expired_run(session, run.id)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return False
            session.commit()
            return True

        def verify():
            frozen = run.parameters["source"]
            source = audio_source(session, frozen["artifact_id"], verify=True)
            artifact = session.get(Artifact, source["artifact_id"])
            origin = session.get(Run, artifact.run_id)
            if (
                source != frozen
                or origin is None
                or origin.task_id != run.task_id
                or origin.status != "succeeded"
                or origin.parameters.get("studio_audio_root_id") != run.parameters["studio_audio_root_id"]
            ):
                raise ValueError("The completed narrator source changed")
            return source

        if not live(True):
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        source = verify()
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        root = get_settings().data_dir.resolve()
        staging = safe_join(root, "runs/" + run.id)
        staging.mkdir(parents=True, exist_ok=True, mode=0o700)
        if staging.resolve() != root / "runs" / run.id:
            raise ValueError("Voice reference staging crosses a symlink")
        with tempfile.TemporaryDirectory(prefix="voice-reference-", dir=staging) as temporary:
            output = Path(temporary) / "reference.wav"
            path = safe_join(root, source["relative_path"])
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size != source["size_bytes"]
                    or hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]
                ):
                    raise ValueError("Voice source file identity changed")
                handle.seek(0)
                with wave.open(handle, "rb") as reader, wave.open(str(output), "wb") as writer:
                    samples = min(source["samples"], 15 * source["sample_rate"])
                    writer.setparams(
                        (
                            source["channels"],
                            source["sample_width"],
                            source["sample_rate"],
                            0,
                            "NONE",
                            "not compressed",
                        )
                    )
                    remaining = samples
                    while remaining:
                        if not live():
                            return "done"
                        frames = min(remaining, 16384)
                        chunk = reader.readframes(frames)
                        if len(chunk) != frames * source["channels"] * source["sample_width"]:
                            raise ValueError("The narrator source is truncated")
                        writer.writeframesraw(chunk)
                        remaining -= frames
                handle.seek(0)
                if hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]:
                    raise ValueError("Voice source changed while sampling")
            if not live(True):
                return "done"
            verify()
            lock_task(session, run.task)
            session.refresh(run)
            cancel_expired_run(session, run.id)
            if (run.worker_id, run.claimed_at) != claim or run.status not in {"running", "cancel_requested"}:
                session.rollback()
                return "done"
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                return "done"
            register_file(
                session,
                source=output,
                artifact_type="audio",
                mime_type="audio/wav",
                original_filename="narrator-reference.wav",
                run_id=run.id,
                parent_artifact_ids=[source["artifact_id"]],
                metadata={
                    "internal_media": True,
                    "studio_voice_reference": True,
                    "duration_seconds": samples / source["sample_rate"],
                },
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        return "done"
