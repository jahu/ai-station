"""Clean measured narration for avatar postproduction; no speech generation or host I/O."""

import os
import stat
import tempfile
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.heartbeat import cancel_expired_run
from app.models import Artifact, Run
from app.paths import safe_join
from app.permissions import require
from app.resources import release_run_locks
from app.run_transactions import RunStopped, database_step_sync
from app.runs import create_run, create_task, run_dict, transition
from app.serialize import artifact_dict
from app.state import RunStatus
from app.studio_materials import DB, digest, get_material, get_revision
from app.studio_narration_pcm import split
from app.studio_pcm import mix
from app.studio_render import audio_snapshot
from app.studio_schema import Fields, Storyboard
from app.studio_soundtrack import audio_source, router
from app.task_control import lock_task

PROFILE = "studio-narration-pcm48-v1"
PERMISSIONS = ["filesystem_read", "workspace_write"]


class NarrationRequest(Fields):
    client_request_id: UUID
    revision_id: UUID
    portrait_artifact_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)


def inputs(session, revision, *, verify=False):
    plan = Storyboard.model_validate(revision.storyboard)
    origin = session.get(Run, revision.source_run_id) if revision.source_run_id else None
    if (
        plan.audio not in {"voice", "voice_music"}
        or origin is None
        or origin.executor_type != "studio_soundtrack"
        or origin.status != "succeeded"
        or origin.parameters.get("studio_material_id") != revision.material_id
        or origin.metadata_json.get("studio_revision_id") != revision.id
        or origin.parameters.get("storyboard") != plan.model_dump(mode="json")
    ):
        raise ValueError("Choose the measured version of a successfully completed narrated soundtrack")
    soundtrack_id = origin.metadata_json.get("soundtrack_artifact_id")
    soundtrack = session.get(Artifact, soundtrack_id) if soundtrack_id else None
    if soundtrack is None or soundtrack.run_id != origin.id or soundtrack.metadata_json.get("partial"):
        raise ValueError("The approved complete soundtrack is unavailable")
    frozen_mix = audio_snapshot(session, soundtrack.id, plan.frames, verify=verify)
    frozen_voices = origin.parameters.get("voices") or {}
    wanted = {str(i) for i, scene in enumerate(plan.scenes) if scene.narration}
    if not wanted or set(frozen_voices) != wanted:
        raise ValueError("The complete measured narration cues are missing")
    voices = {}
    for index, frozen in frozen_voices.items():
        current = audio_source(session, frozen["artifact_id"], verify=verify)
        item = session.get(Artifact, current["artifact_id"])
        parent = session.get(Run, item.run_id) if item.run_id else None
        if current != frozen or item.metadata_json.get("partial") or parent and parent.status != "succeeded":
            raise ValueError("A complete approved narration cue changed or became unavailable")
        voices[int(index)] = current
    if sum(source["size_bytes"] for source in voices.values()) > 1024**3:
        raise ValueError("Keep one narration within one GiB of source PCM")
    return plan, voices, frozen_mix


def create_narration(session, material_id, body):
    material = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, material, body.revision_id)
    key = "studio-narration:" + str(body.client_request_id)
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key,
            Run.parameters["studio_material_id"].as_string() == material.id,
        )
    )
    if prior:
        if prior.parameters["studio_revision_id"] != revision.id or (
            prior.parameters.get("portrait") or {}
        ).get("artifact_id") != (str(body.portrait_artifact_id) if body.portrait_artifact_id else None):
            raise HTTPException(409, "This narration receipt belongs to another saved edit")
        return prior
    try:
        plan, voices, soundtrack = inputs(session, revision)
        from app.studio_presenter_sources import portrait_snapshot

        portrait = (
            portrait_snapshot(session, body.portrait_artifact_id) if body.portrait_artifact_id else None
        )
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    narration_parents = {soundtrack["artifact_id"], *(v["artifact_id"] for v in voices.values())}
    task = create_task(
        session,
        title="Prepare presenter narration · " + material.title,
        prompt=revision.brief,
        capability="studio.narration",
    )
    return create_run(
        session,
        task,
        run_type="audio",
        capability="studio.narration",
        executor_type=StudioNarrationExecutor.name,
        execution_target="container",
        operation_key=key,
        retry_class="safe",
        requested_gpu="none",
        requested_resources={"ram_mib": 512},
        permissions=list(PERMISSIONS),
        parameters={
            "profile": PROFILE,
            "studio_material_id": material.id,
            "studio_revision_id": revision.id,
            "revision_sha256": digest(plan.model_dump(mode="json")),
            "voices": {str(i): source for i, source in voices.items()},
            "soundtrack": soundtrack,
            **({"portrait": portrait} if portrait else {}),
            "parent_artifact_ids": sorted(
                narration_parents | ({portrait["artifact_id"]} if portrait else set())
            ),
            "narration_parent_artifact_ids": sorted(narration_parents),
            "execution_deadline_at": (utcnow() + timedelta(minutes=20)).isoformat(),
        },
    )


@router.post("/{material_id}/narration", status_code=202)
def prepare_narration(material_id: UUID, body: NarrationRequest, session: DB):
    run = create_narration(session, material_id, body)
    session.commit()
    return run_dict(run)


@router.get("/{material_id}/narrations")
def narrations(material_id: UUID, session: DB, revision_id: UUID):
    material = get_material(session, material_id)
    get_revision(session, material, revision_id)
    runs = list(
        session.scalars(
            select(Run)
            .where(
                Run.executor_type == StudioNarrationExecutor.name,
                Run.parameters["studio_material_id"].as_string() == material.id,
                Run.parameters["studio_revision_id"].as_string() == str(revision_id),
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(50)
        )
    )
    return [
        {
            "run": run_dict(run),
            "artifacts": [
                artifact_dict(a)
                for a in session.scalars(
                    select(Artifact).where(
                        Artifact.run_id == run.id,
                        Artifact.trashed_at.is_(None),
                        Artifact.purged_at.is_(None),
                        Artifact.purge_run_id.is_(None),
                    )
                )
            ]
            if run.status == "succeeded"
            else [],
        }
        for run in runs
    ]


def frozen_inputs(session, run):
    material = get_material(session, run.parameters["studio_material_id"])
    revision = get_revision(session, material, run.parameters["studio_revision_id"])
    plan, voices, soundtrack = inputs(session, revision, verify=True)
    if run.parameters.get("portrait"):
        from app.studio_presenter_sources import portrait_snapshot

        frozen = run.parameters["portrait"]
        if portrait_snapshot(session, frozen["artifact_id"], verify=True) != frozen:
            raise ValueError("The frozen presenter portrait changed")
    if (
        run.parameters["profile"] != PROFILE
        or digest(plan.model_dump(mode="json")) != run.parameters["revision_sha256"]
        or {str(i): source for i, source in voices.items()} != run.parameters["voices"]
        or soundtrack != run.parameters["soundtrack"]
    ):
        raise ValueError("The frozen presenter narration or approved edit changed")
    return material, revision, plan, voices


def recover_narration(session, run):
    """Only pure local PCM may recompute after losing its worker; never native AI."""
    if (
        run.parameters.get("profile") != PROFILE
        or run.pid
        or run.process_group_id
        or run.metadata_json.get("dispatch_attempted")
    ):
        return False
    lock_task(session, run.task)
    session.refresh(run)
    if (
        run.status not in {"claimed", "preparing", "running", "cancel_requested"}
        or run.lease_expires_at is None
        or run.lease_expires_at >= utcnow()
    ):
        return True
    release_run_locks(session, run.id)
    if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
        if run.status != "cancel_requested":
            transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
    else:
        transition(
            session,
            run,
            RunStatus.INTERRUPTED,
            event_type="run.interrupted",
            payload={"reason": "Resume pure PCM narration; no native dispatch or synthesis replay"},
        )
        run.worker_id = run.lease_expires_at = run.finished_at = None
        run.error_type = run.error_message = ""
        transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"pcm_only": True})
    return True


class StudioNarrationExecutor:
    name = "studio_narration"

    def execute(self, session, run):
        for permission in PERMISSIONS:
            require(run.effective_permissions, permission)
        claim = run.worker_id, run.claimed_at
        deadline = datetime.fromisoformat(run.parameters["execution_deadline_at"])
        last = 0.0

        def phase(action):
            return database_step_sync(session, run, claim, deadline, action)

        def check(force=False):
            nonlocal last
            if not force and time.monotonic() - last < 0.25:
                return
            last = time.monotonic()
            phase(lambda: cancel_expired_run(session, run.id))
            if run.status == "cancel_requested":
                phase(lambda: None)

        def initialize():
            cancel_expired_run(session, run.id)
            if run.status == "cancel_requested":
                return None
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            value = frozen_inputs(session, run)
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            return value

        try:
            initial = phase(initialize)
            if initial is None:
                check(True)
                return "done"
            material, revision, plan, voices = initial
            root = get_settings().data_dir.resolve()
            staging = safe_join(root, "runs/" + run.id)
            staging.mkdir(mode=0o700, parents=True, exist_ok=True)
            if staging.resolve() != root / "runs" / run.id:
                raise ValueError("Narration staging crosses a symlink")

            def open_source(stack, source):
                path = safe_join(root, source["relative_path"])
                if path != root / source["relative_path"]:
                    raise ValueError("Narration source crosses a symlink")
                handle = stack.enter_context(
                    os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb")
                )
                info = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size != source["size_bytes"]
                ):
                    raise ValueError("The narration source changed")
                return handle

            with tempfile.TemporaryDirectory(prefix="narration-", dir=staging) as temporary:
                folder = Path(temporary)
                stem = folder / "narration.wav"
                report = mix(plan, voices, None, open_source, folder / "bus.f32", stem, check=check)
                parts = split(stem, plan, folder, check=check)
                portrait_path = None
                if run.parameters.get("portrait"):
                    from app.studio_presenter_sources import normalize_portrait

                    check(True)
                    portrait_path = folder / "presenter.png"
                    normalize_portrait(run.parameters["portrait"], portrait_path)
                check(True)

                def publish():
                    lock_task(session, run.task)
                    session.refresh(run)
                    cancel_expired_run(session, run.id)
                    if (run.worker_id, run.claimed_at) != claim:
                        raise RunStopped()
                    if run.task.metadata_json.get("stop_requested_at") or run.status == "cancel_requested":
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                        session.commit()
                        raise RunStopped()
                    frozen_inputs(session, run)
                    common = {
                        "internal_media": True,
                        "profile": PROFILE,
                        "studio_material_id": material.id,
                        "studio_revision_id": revision.id,
                    }
                    # Stable IDs make local publication retry-safe. No synthesis/codec
                    # work is repeated after a short SQL contention rollback.
                    artifact = register_file(
                        session,
                        source=stem,
                        artifact_type="audio",
                        mime_type="audio/wav",
                        original_filename="narration.wav",
                        run_id=run.id,
                        artifact_id=str(uuid5(UUID(run.id), "stem")),
                        parent_artifact_ids=run.parameters.get(
                            "narration_parent_artifact_ids", run.parameters["parent_artifact_ids"]
                        ),
                        metadata={**common, **report, "studio_role": "narration_stem"},
                    )
                    artifact.title = material.title + " · clean narration"
                    result = []
                    for index, part in enumerate(parts):
                        interval = {key: value for key, value in part.items() if key != "path"}
                        child = register_file(
                            session,
                            source=part["path"],
                            artifact_type="audio",
                            mime_type="audio/wav",
                            original_filename=part["path"].name,
                            run_id=run.id,
                            artifact_id=str(uuid5(UUID(run.id), "part:" + str(index))),
                            parent_artifact_ids=[artifact.id],
                            metadata={
                                **common,
                                **interval,
                                "sample_rate": 48000,
                                "channels": 2,
                                "studio_role": "narration_part",
                                "part_index": index,
                            },
                        )
                        result.append({**interval, "artifact_id": child.id})
                    run.metadata_json = {
                        **run.metadata_json,
                        "narration_artifact_id": artifact.id,
                        "parts": result,
                        "samples": plan.frames * 1600,
                    }
                    if portrait_path:
                        picture = register_file(
                            session,
                            source=portrait_path,
                            artifact_type="image",
                            mime_type="image/png",
                            original_filename="presenter.png",
                            run_id=run.id,
                            artifact_id=str(uuid5(UUID(run.id), "portrait")),
                            parent_artifact_ids=[run.parameters["portrait"]["artifact_id"]],
                            metadata={**common, "studio_role": "presenter_portrait"},
                        )
                        run.metadata_json = {**run.metadata_json, "portrait_artifact_id": picture.id}
                    transition(
                        session,
                        run,
                        RunStatus.SUCCEEDED,
                        event_type="run.completed",
                        payload=run.metadata_json,
                    )

                phase(publish)
        except RunStopped:
            return "done"
        return "done"
