"""Owned Studio soundtrack assembly; CPU worker work over completed PCM artifacts."""

import os
import stat
import tempfile
import time
import wave
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.heartbeat import cancel_expired_run
from app.models import Artifact, Run
from app.paths import safe_join
from app.permissions import require
from app.runs import create_run, create_task, run_dict, transition
from app.state import RunStatus
from app.studio_materials import DB, digest, get_material, get_revision, publish_revision
from app.studio_pcm import mix, timed_storyboard
from app.studio_render import Binding
from app.studio_schema import Fields, Storyboard
from app.studio_shots import router
from app.task_control import lock_task
from app.timelines import verify_bytes


class MixRequest(Fields):
    client_request_id: UUID
    revision_id: UUID
    narration: list[Binding] = Field(default_factory=list, max_length=60)
    music_artifact_id: UUID | None = None
    music_gain: float = Field(default=0.22, ge=0.01, le=1.0, allow_inf_nan=False, strict=True)
    duck: float = Field(default=0.28, ge=0.05, le=1.0, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def unique(self):
        if len({item.scene for item in self.narration}) != len(self.narration):
            raise ValueError("Choose one complete spoken cue per scene")
        return self


def audio_source(session, identity, *, verify=False):
    item = session.get(Artifact, str(identity), populate_existing=True)
    if (
        item is None
        or item.trashed_at
        or item.purged_at
        or item.purge_run_id
        or (item.artifact_type, item.mime_type) != ("audio", "audio/wav")
    ):
        raise ValueError("Choose an available PCM WAV from your Library")
    root = get_settings().data_dir.resolve()
    path = safe_join(root, item.relative_path)
    if (
        not item.relative_path.startswith("artifacts/")
        or path != root / item.relative_path
        or not 1 <= item.size_bytes <= 256 * 1024**2
    ):
        raise ValueError("Use canonical app-owned PCM within 256 MiB")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item.size_bytes:
            raise ValueError("Audio file identity changed")
        with wave.open(handle, "rb") as reader:
            samples, rate, channels, width = (
                reader.getnframes(),
                reader.getframerate(),
                reader.getnchannels(),
                reader.getsampwidth(),
            )
            if (
                not 8000 <= rate <= 96000
                or channels not in (1, 2)
                or width not in (1, 2, 3, 4)
                or reader.getcomptype() != "NONE"
                or not 1 <= samples <= 600 * rate
            ):
                raise ValueError("Use complete mono/stereo PCM of at most ten minutes")
            reader.setpos(samples - 1)
            if len(reader.readframes(1)) != width * channels:
                raise ValueError("PCM source is truncated")
    value = {
        "artifact_id": item.id,
        "relative_path": item.relative_path,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "samples": samples,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": width,
    }
    if verify:
        verify_bytes(value)
    return value


def inputs(session, revision, body, *, verify=False):
    plan = Storyboard.model_validate(revision.storyboard)
    if plan.audio == "silent":
        raise ValueError("This version is intentionally silent")
    wanted = {i for i, scene in enumerate(plan.scenes) if scene.narration}
    if {b.scene for b in body.narration} != wanted:
        raise ValueError("Supply the complete spoken cue for every narrated scene, and no extra cues")
    has_music = plan.audio in {"voice_music", "music"}
    if has_music != bool(body.music_artifact_id):
        raise ValueError("The mix must preserve this version's requested music policy")
    voices = {b.scene: audio_source(session, b.artifact_id, verify=verify) for b in body.narration}
    music = audio_source(session, body.music_artifact_id, verify=verify) if has_music else None
    plan = timed_storyboard(plan, voices)
    if music and music["samples"] * 30 < plan.frames * music["sample_rate"]:
        raise ValueError("The complete score must cover the measured edit; generate a longer score")
    if sum(v["size_bytes"] for v in voices.values()) + (music["size_bytes"] if music else 0) > 1024**3:
        raise ValueError("Keep one soundtrack within one GiB of source PCM")
    return plan, voices, music


def frozen_inputs(session, run, revision, body):
    plan, voices, music = inputs(session, revision, body, verify=True)
    if (
        digest(revision.storyboard) != run.parameters["revision_sha256"]
        or plan.model_dump(mode="json") != run.parameters["storyboard"]
        or {str(i): s for i, s in voices.items()} != run.parameters["voices"]
        or music != run.parameters["music"]
    ):
        raise ValueError("The frozen soundtrack sources or editorial plan changed")
    return plan, voices, music


@router.post("/{material_id}/soundtrack", status_code=202)
def soundtrack(material_id: UUID, body: MixRequest, session: DB):
    row = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, row, body.revision_id)
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id"}))
    key = "studio-soundtrack:" + str(body.client_request_id)
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key, Run.parameters["studio_material_id"].as_string() == row.id
        )
    )
    if prior:
        if prior.parameters.get("request_sha256") != fingerprint:
            raise HTTPException(409, "This mix receipt belongs to another request")
        return run_dict(prior)
    try:
        plan, voices, music = inputs(session, revision, body)
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    task = create_task(
        session, title="Soundtrack · " + row.title, prompt=revision.brief, capability="studio.soundtrack"
    )
    run = create_run(
        session,
        task,
        run_type="audio",
        capability="studio.soundtrack",
        executor_type="studio_soundtrack",
        execution_target="container",
        operation_key=key,
        retry_class="safe",
        requested_gpu="none",
        permissions=["filesystem_read", "workspace_write"],
        parameters={
            "studio_material_id": row.id,
            "studio_revision_id": revision.id,
            "request": body.model_dump(mode="json"),
            "request_sha256": fingerprint,
            "revision_sha256": digest(revision.storyboard),
            "storyboard": plan.model_dump(mode="json"),
            "voices": {str(i): s for i, s in voices.items()},
            "music": music,
            "project_snapshot": revision.project_snapshot,
            "execution_deadline_at": (utcnow() + timedelta(minutes=20)).isoformat(),
            "parent_artifact_ids": sorted(
                {s["artifact_id"] for s in voices.values()} | ({music["artifact_id"]} if music else set())
            ),
        },
    )
    session.commit()
    return run_dict(run)


class MixStopped(Exception):
    pass


class MixClaimLost(Exception):
    pass


class StudioSoundtrackExecutor:
    name = "studio_soundtrack"

    def execute(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        claim = (run.worker_id, run.claimed_at)
        last = 0.0

        def check(force=False):
            nonlocal last
            if not force and time.monotonic() - last < 0.25:
                return
            last = time.monotonic()
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim or run.status not in {
                "claimed",
                "preparing",
                "running",
                "cancel_requested",
            }:
                session.rollback()
                raise MixClaimLost()
            cancel_expired_run(session, run.id)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                raise MixStopped()
            session.commit()

        try:
            check(True)
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            row = get_material(session, run.parameters["studio_material_id"])
            revision = get_revision(session, row, run.parameters["studio_revision_id"])
            body = MixRequest.model_validate(run.parameters["request"])
            plan, voices, music = frozen_inputs(session, run, revision, body)
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            root = get_settings().data_dir.resolve()
            staging = safe_join(root, "runs/" + run.id)
            staging.mkdir(parents=True, exist_ok=True, mode=0o700)
            if staging.resolve() != root / "runs" / run.id:
                raise ValueError("Soundtrack staging crosses a symlink")

            def open_source(stack, source):
                path = safe_join(root, source["relative_path"])
                if path != root / source["relative_path"]:
                    raise ValueError("PCM source crosses a symlink")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                handle = stack.enter_context(os.fdopen(fd, "rb"))
                info = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size != source["size_bytes"]
                ):
                    raise ValueError("The soundtrack source changed")
                return handle

            with tempfile.TemporaryDirectory(prefix="studio-pcm-", dir=staging) as temporary:
                output = Path(temporary) / "soundtrack.wav"
                report = mix(
                    plan,
                    voices,
                    music,
                    open_source,
                    Path(temporary) / "bus.f32",
                    output,
                    music_gain=body.music_gain,
                    duck=body.duck,
                    check=check,
                )
                check(True)
                # Recheck bytes after decoding, then serialize publication with Stop.
                frozen_inputs(session, run, revision, body)
                lock_task(session, run.task)
                session.refresh(run)
                cancel_expired_run(session, run.id)
                if (run.worker_id, run.claimed_at) != claim or run.status not in {
                    "running",
                    "cancel_requested",
                }:
                    session.rollback()
                    return "done"
                if run.status == "cancel_requested":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                    return "done"
                row = get_material(session, row.id, lock=True)
                saved = publish_revision(
                    session,
                    row,
                    plan,
                    client_request_id=body.client_request_id,
                    request_sha256=run.parameters["request_sha256"],
                    parent=revision,
                    source_run_id=run.id,
                    frozen={
                        "brief": revision.brief,
                        "options": revision.options,
                        "project_snapshot": revision.project_snapshot,
                    },
                )
                artifact = register_file(
                    session,
                    source=output,
                    artifact_type="audio",
                    mime_type="audio/wav",
                    original_filename="soundtrack.wav",
                    run_id=run.id,
                    parent_artifact_ids=run.parameters["parent_artifact_ids"],
                    metadata={
                        **report,
                        "studio_material_id": row.id,
                        "studio_revision_id": saved.id,
                        "narration": body.model_dump(mode="json")["narration"],
                        "music_artifact_id": str(body.music_artifact_id) if body.music_artifact_id else None,
                    },
                )
                artifact.title = row.title + " · soundtrack"
                run.metadata_json = {
                    **run.metadata_json,
                    "studio_revision_id": saved.id,
                    "soundtrack_artifact_id": artifact.id,
                    "mix": report,
                }
                transition(
                    session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload=run.metadata_json
                )
                session.commit()
        except (MixStopped, MixClaimLost):
            return "done"
        return "done"
