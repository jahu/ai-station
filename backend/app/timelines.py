"""Private immutable edits around existing creative workspaces and media Runs."""

import hashlib
import json
import os
import re
import stat
import wave
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.creative_sessions import get_session
from app.db import session_scope, utcnow
from app.effects import video_snapshot
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, Run, TimelineRevision
from app.paths import safe_join
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict
from app.timeline_schema import Fields, Manifest, inspect_manifest

router = APIRouter(prefix="/api/timelines", tags=["media editing"])
DB = Annotated[Session, Depends(session_scope)]
RAM_MIB = 4096


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SaveRevision(Fields):
    client_request_id: UUID
    manifest: Manifest
    parent_revision_id: UUID | None = None


class RenderRequest(Fields):
    revision_id: UUID
    manifest: Manifest


def revision_dict(row):
    return {
        "id": row.id,
        "session_id": row.session_id,
        "parent_revision_id": row.parent_revision_id,
        "position": row.position,
        "manifest": row.manifest,
        "created_at": row.created_at,
    }


def verify_bytes(source):
    path = get_settings().data_dir.resolve() / source["relative_path"]
    if path.resolve() != path:
        raise ValueError("Timeline media traverses a symlink")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != source["size_bytes"]:
            raise ValueError("Timeline source is not the recorded regular file")
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
        if (
            actual != source["sha256"]
            or path.resolve() != path
            or any(
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                for s in (after, current)
            )
        ):
            raise ValueError("Timeline source changed during inspection")


def source_snapshot(session, identity, *, verify=False):
    a = session.get(Artifact, str(identity), populate_existing=True)
    if a is None or a.trashed_at or a.purge_run_id or a.purged_at:
        raise ValueError("Choose available media from your Library")
    if a.artifact_type == "video":
        snapshot = {"artifact_id": a.id, "kind": "video", **video_snapshot(session, identity)}
        if verify:
            verify_bytes(snapshot)
        return snapshot
    if a.artifact_type != "audio" or a.mime_type != "audio/wav":
        raise ValueError("Choose an inspected MP4 or PCM WAV")
    path = safe_join(get_settings().data_dir, a.relative_path)
    if (
        not a.relative_path.startswith("artifacts/")
        or not a.relative_path.endswith(".wav")
        or not 1 <= a.size_bytes <= 64 * 1024**2
        or path.stat().st_size != a.size_bytes
    ):
        raise ValueError("Audio changed or exceeds the timeline profile")
    with wave.open(str(path)) as source:
        samples, rate, channels, width = (
            source.getnframes(),
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
    if (
        not 8000 <= rate <= 96000
        or channels not in (1, 2)
        or width not in (1, 2, 3, 4)
        or not 1 <= samples <= rate * 300
    ):
        raise ValueError("Use complete mono/stereo PCM WAV of at most five minutes")
    if verify:
        verify_bytes({"relative_path": a.relative_path, "size_bytes": a.size_bytes, "sha256": a.sha256})
    return {
        "artifact_id": a.id,
        "kind": "audio",
        "relative_path": a.relative_path,
        "size_bytes": a.size_bytes,
        "sha256": a.sha256,
        "samples": samples,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": width,
    }


def snapshots(session, manifest, *, verify=False):
    identities = sorted({str(v.artifact_id) for v in [*manifest.clips, *manifest.tracks]})
    values = {identity: source_snapshot(session, identity, verify=verify) for identity in identities}
    if sum(v["size_bytes"] for v in values.values()) > 8 * 1024**3:
        raise ValueError("Timeline source bytes exceed eight GiB")
    if sum(v["size_bytes"] for v in values.values() if v["kind"] == "audio") > 512 * 1024**2:
        raise ValueError("Timeline WAV inputs exceed 512 MiB")
    inspect_manifest(manifest, values)
    return values


def project(session, identity, *, lock=False):
    row = get_session(session, identity, lock=lock)
    if row.capability != "timeline":
        raise HTTPException(404, "Timeline workspace not found")
    return row


@router.get("/capabilities")
def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/timeline/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Host Runner timeline renderer is unavailable"}


@router.get("/sources/{artifact_id}")
def source_info(artifact_id: UUID, session: DB):
    try:
        value = source_snapshot(session, artifact_id)
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(404, "Timeline source is unavailable") from exc
    artifact = session.get(Artifact, str(artifact_id))
    return {
        **{k: v for k, v in value.items() if k != "relative_path"},
        "title": artifact.title or artifact.original_filename,
        "capability": artifact.metadata_json.get("capability", ""),
    }


@router.get("/revisions/{revision_id}")
def revision(revision_id: UUID, session: DB):
    row = session.get(TimelineRevision, str(revision_id))
    if row is None:
        raise HTTPException(404, "Saved edit not found")
    return revision_dict(row)


@router.get("/revisions/{revision_id}/render")
def saved_render(revision_id: UUID, session: DB):
    if session.get(TimelineRevision, str(revision_id)) is None:
        raise HTTPException(404, "Saved edit not found")
    run = session.scalar(
        select(Run)
        .where(
            Run.executor_type == "timeline_render",
            Run.parameters["revision_id"].as_string() == str(revision_id),
            Run.status == "succeeded",
        )
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    return run_dict(run) if run else None


@router.get("/{session_id}/revisions")
def revisions(
    session_id: UUID,
    session: DB,
    before: int | None = Query(None, ge=1),
    limit: int = Query(30, ge=1, le=100),
):
    row = project(session, session_id)
    query = select(TimelineRevision).where(TimelineRevision.session_id == row.id)
    if before is not None:
        query = query.where(TimelineRevision.position < before)
    return [
        revision_dict(r)
        for r in session.scalars(query.order_by(TimelineRevision.position.desc()).limit(limit))
    ]


@router.post("/{session_id}/revisions", status_code=201)
def save(session_id: UUID, body: SaveRevision, session: DB):
    row = project(session, session_id, lock=True)
    if row.archived_at:
        raise HTTPException(409, "Restore this workspace before saving edits")
    manifest = body.manifest.model_dump(mode="json")
    fingerprint = digest(
        {
            "manifest": manifest,
            "parent_revision_id": str(body.parent_revision_id) if body.parent_revision_id else None,
        }
    )
    prior = session.scalar(
        select(TimelineRevision).where(
            TimelineRevision.session_id == row.id,
            TimelineRevision.client_request_id == str(body.client_request_id),
        )
    )
    if prior:
        if prior.request_sha256 != fingerprint:
            raise HTTPException(409, "This save receipt belongs to another edit")
        return revision_dict(prior)
    if body.parent_revision_id:
        parent = session.get(TimelineRevision, str(body.parent_revision_id))
        if parent is None or parent.session_id != row.id:
            raise HTTPException(404, "Choose an earlier edit in this workspace")
    try:
        sources = snapshots(session, body.manifest)
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    position = (
        session.scalar(
            select(func.max(TimelineRevision.position)).where(TimelineRevision.session_id == row.id)
        )
        or 0
    ) + 1
    saved = TimelineRevision(
        session_id=row.id,
        parent_revision_id=str(body.parent_revision_id) if body.parent_revision_id else None,
        client_request_id=str(body.client_request_id),
        request_sha256=fingerprint,
        position=position,
        manifest=manifest,
        sources=sources,
    )
    session.add(saved)
    session.commit()
    return revision_dict(saved)


def create_timeline_run(session, body, *, task=None, parent_run_id=None):
    saved = session.get(TimelineRevision, str(body.revision_id))
    if saved is None:
        raise HTTPException(404, "Saved edit not found")
    if saved.manifest != body.manifest.model_dump(mode="json"):
        raise HTTPException(409, "Save the changed edit before rendering")
    try:
        if snapshots(session, body.manifest) != saved.sources:
            raise ValueError("The saved media changed; inspect or restore it")
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    ready = capabilities()
    if (
        not ready.get("available")
        or ready.get("ram_mib") != RAM_MIB
        or not isinstance(ready.get("observation"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", ready["observation"])
    ):
        raise HTTPException(409, ready.get("reason", "Timeline renderer needs setup"))
    task = task or create_task(
        session,
        title="Render saved film edit",
        prompt="Render the inspected private timeline",
        capability="video.timeline",
    )
    return create_run(
        session,
        task,
        run_type="video",
        capability="video.timeline",
        executor_type="timeline_render",
        requested_gpu="none",
        requested_resources={"ram_mib": RAM_MIB},
        permissions=["filesystem_read", "workspace_write"],
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "revision_id": saved.id,
            "timeline_session_id": saved.session_id,
            "manifest": saved.manifest,
            "sources": saved.sources,
            "manifest_sha256": digest(saved.manifest),
            "observation": ready["observation"],
            "target_frames": inspect_manifest(body.manifest, saved.sources),
            "parent_artifact_ids": sorted(saved.sources),
        },
    )


class TimelineExecutor(HostMediaExecutor):
    name = "timeline_render"
    requires_gpu = False
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def validate_inputs(self, session, run):
        manifest = Manifest.model_validate(run.parameters["manifest"])
        saved = session.get(TimelineRevision, run.parameters["revision_id"])
        if (
            saved is None
            or saved.manifest != run.parameters["manifest"]
            or saved.sources != run.parameters["sources"]
            or digest(saved.manifest) != run.parameters["manifest_sha256"]
        ):
            raise ValueError("The frozen timeline revision changed")
        if snapshots(session, manifest, verify=True) != saved.sources:
            raise ValueError("Timeline media changed")
        run.parameters = {
            **run.parameters,
            "execution_deadline_at": run.parameters.get("execution_deadline_at")
            or (utcnow() + timedelta(minutes=30)).isoformat(),
        }

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/timeline",
            {
                "run_id": run.id,
                "manifest": run.parameters["manifest"],
                "sources": list(run.parameters["sources"].values()),
                "observation": run.parameters["observation"],
                "permissions": run.effective_permissions,
                **self.native_budget(run),
            },
        )

    def output_metadata(self, output):
        path = safe_join(get_settings().data_dir, output).with_suffix(".json")
        if path.stat().st_size > 32768:
            raise ValueError("Timeline report exceeds its bound")
        report = json.loads(path.read_text())
        if report.get("verified") is not True:
            raise ValueError("Timeline export was not verified")
        return report

    def on_success(self, session, run, artifact):
        self.validate_inputs(session, run)
        params = run.parameters
        if artifact.metadata_json.get("frames") != params["target_frames"] or any(
            artifact.metadata_json.get(k) != params["manifest"][k] for k in ("fps", "width", "height")
        ):
            raise ValueError("Timeline export timing or size changed")
        report = artifact.metadata_json
        expected_samples = params["target_frames"] * 48000 // params["manifest"]["fps"]
        if (
            report.get("timeline_audio_samples") != expected_samples
            or report.get("timeline_audio_rate") != 48000
            or report.get("observation") != params["observation"]
            or report.get("source_ids") != sorted(params["sources"])
        ):
            raise ValueError("Timeline export audio or provenance changed")
        artifact.metadata_json = {
            **artifact.metadata_json,
            "timeline_revision_id": params["revision_id"],
            "manifest_sha256": params["manifest_sha256"],
        }
