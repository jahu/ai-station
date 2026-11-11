"""Full-HD Studio export of completed owned media; planned footage is never faked."""

import json
import os
import re
import stat
import wave
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from ai_station_runner.motion_contract import RAM_MIB, Composition, MotionRequest, Scene, Source, Style
from fastapi import HTTPException
from pydantic import Field, StrictInt, model_validator
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, Run
from app.paths import safe_join
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict
from app.serialize import artifact_dict
from app.studio_director import router
from app.studio_materials import DB, digest, get_material, get_revision, source_snapshot
from app.studio_schema import Fields, Storyboard
from app.timelines import verify_bytes

PERMISSIONS = ["filesystem_read", "workspace_write"]


class Binding(Fields):
    scene: StrictInt = Field(ge=0, le=59)
    artifact_id: UUID


class RenderRequest(Fields):
    client_request_id: UUID
    revision_id: UUID
    bindings: list[Binding] = Field(default_factory=list, max_length=60)
    soundtrack_artifact_id: UUID | None = None

    @model_validator(mode="after")
    def distinct(self):
        if len({b.scene for b in self.bindings}) != len(self.bindings):
            raise ValueError("Bind each scene once")
        return self


def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/motion/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Connect and prepare the isolated Studio renderer"}


@router.get("/renderer/capabilities")
def renderer_capabilities():
    return capabilities()


def audio_snapshot(session, identity, frames, *, verify=False):
    item = session.get(Artifact, str(identity), populate_existing=True)
    if (
        item is None
        or item.trashed_at
        or item.purged_at
        or item.purge_run_id
        or (item.artifact_type, item.mime_type) != ("audio", "audio/wav")
    ):
        raise ValueError("Choose an available complete PCM soundtrack from your Library")
    root = get_settings().data_dir.resolve()
    path = safe_join(root, item.relative_path)
    if (
        not item.relative_path.startswith("artifacts/")
        or path != root / item.relative_path
        or path.suffix.lower() != ".wav"
        or not 1 <= item.size_bytes <= 256 * 1024**2
    ):
        raise ValueError("Use a canonical app-owned PCM soundtrack within 256 MiB")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item.size_bytes:
            raise ValueError("The soundtrack file changed")
        with wave.open(handle, "rb") as reader:
            if (
                reader.getframerate(),
                reader.getnchannels(),
                reader.getsampwidth(),
                reader.getcomptype(),
            ) != (48000, 2, 2, "NONE"):
                raise ValueError("Use the final 48-kHz stereo PCM mix")
            if reader.getnframes() != frames * 1600:
                raise ValueError(
                    "The complete soundtrack must cover all storyboard frames without cutting narration"
                )
    value = Source(
        artifact_id=item.id,
        kind="audio",
        relative_path=item.relative_path,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
    ).model_dump(mode="json")
    if verify:
        verify_bytes(value)
    return value


def composition_inputs(session, revision, bindings, soundtrack_id, *, verify=False):
    plan = Storyboard.model_validate(revision.storyboard)
    selected = {b.scene: str(b.artifact_id) for b in bindings}
    if any(i >= len(plan.scenes) for i in selected):
        raise ValueError("A binding refers to a scene outside this saved version")
    sources, scenes = {}, []
    for index, shot in enumerate(plan.scenes):
        identity = selected.get(index)
        if shot.visual_kind == "library":
            if identity and identity != str(shot.source_artifact_id):
                raise ValueError("Save a new storyboard version to replace its selected Library source")
            identity = str(shot.source_artifact_id)
        elif shot.visual_kind == "graphics":
            if identity:
                raise ValueError("An editorial graphics shot cannot acquire an unrequested source")
        elif not identity:
            raise ValueError(f"Generate or select the actual media for shot {index + 1} before exporting")
        if identity:
            source = source_snapshot(session, identity, verify=verify)
            if shot.visual_kind in {"image", "video"} and source["kind"] != shot.visual_kind:
                raise ValueError(
                    f"Shot {index + 1} requires actual {shot.visual_kind}; do not silently substitute another medium"
                )
            sources[identity] = Source.model_validate(source).model_dump(mode="json")
        values = {
            key: getattr(shot, key)
            for key in (
                "layout",
                "duration_frames",
                "eyebrow",
                "title",
                "body",
                "points",
                "media_motion",
                "media_fit",
                "media_start_seconds",
            )
        }
        scenes.append(Scene(**values, media=identity))
    has_sound = plan.audio != "silent"
    if has_sound != bool(soundtrack_id):
        raise ValueError("Provide the complete requested soundtrack, or explicitly save a silent version")
    if soundtrack_id:
        source = audio_snapshot(session, soundtrack_id, plan.frames, verify=verify)
        sources[source["artifact_id"]] = source
    identity = revision.project_snapshot.get("identity") or {}
    dimensions = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
    width, height = dimensions[revision.options["aspect"]]
    composition = Composition(
        width=width,
        height=height,
        style=Style(
            palette=identity.get("colors") or ["#A8CC74", "#101311", "#F7F8F4"],
            typography=identity.get("typography", "sans"),
            brand=revision.project_snapshot.get("name", ""),
            motion="dynamic" if revision.options["format"] == "reel" else "gentle",
        ),
        scenes=scenes,
    )
    if sum(s["size_bytes"] for s in sources.values()) > 2 * 1024**3:
        raise ValueError("Keep one material within two GiB of source media")
    return composition.model_dump(mode="json"), sources


def native_request(run):
    return MotionRequest.model_validate(
        {
            "run_id": run.id,
            "deadline_at": datetime.fromisoformat(run.parameters["execution_deadline_at"]).timestamp(),
            "composition": run.parameters["composition"],
            "sources": list(run.parameters["sources"].values()),
            "audio_artifact_id": run.parameters["soundtrack_artifact_id"],
            "observation": run.parameters["observation"],
            "permissions": run.effective_permissions,
        }
    ).model_dump(mode="json")


def create_render(session, material_id, body, *, task=None, parent_run_id=None, observed_profile=None):
    row = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, row, body.revision_id)
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id"}))
    key = "studio-render:" + str(body.client_request_id)
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key, Run.parameters["studio_material_id"].as_string() == row.id
        )
    )
    if prior:
        if prior.parameters.get("request_sha256") != fingerprint:
            raise HTTPException(409, "This export receipt belongs to another request")
        return prior
    try:
        composition, sources = composition_inputs(
            session, revision, body.bindings, body.soundtrack_artifact_id
        )
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    ready = capabilities() if observed_profile is None else observed_profile
    if (
        not ready.get("available")
        or ready.get("ram_mib") != RAM_MIB
        or not isinstance(ready.get("observation"), str)
        or not re.fullmatch("[a-f0-9]{64}", ready["observation"])
    ):
        raise HTTPException(409, ready.get("reason", "Prepare the isolated Studio renderer"))
    from app.permissions import require

    parent = session.get(Run, parent_run_id) if parent_run_id else None
    if parent_run_id and parent is None:
        raise ValueError("Choose an owned parent Run")
    if parent:
        require(parent.effective_permissions, "filesystem_read")
        require(parent.effective_permissions, "workspace_write")
        if task is not None and parent.task_id != task.id:
            raise ValueError("Studio children must belong to the originating Task")
        task = task or parent.task
    deadline = utcnow() + timedelta(hours=1)
    if parent and parent.parameters.get("execution_deadline_at"):
        inherited = datetime.fromisoformat(parent.parameters["execution_deadline_at"])
        if inherited.tzinfo is None:
            raise ValueError("Studio deadlines require an explicit timezone")
        deadline = min(deadline, inherited)
    task = task or create_task(
        session, title="Export · " + row.title, prompt=revision.brief, capability="studio.render"
    )
    run = create_run(
        session,
        task,
        run_type="media",
        capability="studio.render",
        executor_type="motion_render",
        execution_target="container",
        operation_key=key,
        requested_gpu="none",
        requested_resources={"ram_mib": RAM_MIB},
        permissions=list(PERMISSIONS),
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            "studio_material_id": row.id,
            "studio_revision_id": revision.id,
            "project_snapshot": revision.project_snapshot,
            "options": revision.options,
            "prompt": revision.brief,
            "material_title": row.title,
            "storyboard_revision_position": revision.position,
            "revision_sha256": digest(revision.storyboard),
            "request_sha256": fingerprint,
            "bindings": [b.model_dump(mode="json") for b in body.bindings],
            "soundtrack_artifact_id": str(body.soundtrack_artifact_id)
            if body.soundtrack_artifact_id
            else None,
            "composition": composition,
            "sources": sources,
            "observation": ready["observation"],
            "execution_deadline_at": deadline.isoformat(),
            "parent_artifact_ids": sorted(sources),
        },
    )
    run.parameters = {**run.parameters, "native_request_sha256": digest(native_request(run))}
    return run


@router.get("/{material_id}/exports")
def exports(material_id: UUID, session: DB, revision_id: UUID | None = None):
    row = get_material(session, material_id)
    if revision_id:
        get_revision(session, row, revision_id)
    query = select(Run).where(
        Run.executor_type == "motion_render",
        Run.parameters["studio_material_id"].as_string() == row.id,
    )
    if revision_id:
        query = query.where(Run.parameters["studio_revision_id"].as_string() == str(revision_id))
    runs = list(session.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(50)))
    outputs = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.run_id.in_([r.id for r in runs if r.status == "succeeded"]),
                Artifact.artifact_type == "video",
                Artifact.mime_type == "video/mp4",
                Artifact.trashed_at.is_(None),
                Artifact.purged_at.is_(None),
                Artifact.purge_run_id.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    )
    return {
        "runs": [run_dict(r) for r in runs],
        "artifacts": [
            artifact_dict(a)
            for a in outputs
            if not a.metadata_json.get("partial") and not a.metadata_json.get("internal_media")
        ],
    }


@router.post("/{material_id}/render", status_code=202)
def render(material_id: UUID, body: RenderRequest, session: DB):
    run = create_render(session, material_id, body)
    session.commit()
    return run_dict(run)


def fence_missing_dispatch(runner, run):
    receipt = runner.request("POST", f"/v1/motion/{run.id}/cancel", {"permissions": PERMISSIONS})
    if receipt.get("cleanup_confirmed") is not True:
        raise ValueError("The delayed Studio dispatch has not been safely fenced")
    return {
        "run_id": run.id,
        "executor": "motion_render",
        "alive": False,
        "known": False,
        "completion_pending": False,
        "cleanup_confirmed": True,
    }


class StudioRenderExecutor(HostMediaExecutor):
    name = "motion_render"
    requires_gpu = False
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def validate_inputs(self, session, run):
        row = get_material(session, run.parameters["studio_material_id"])
        revision = get_revision(session, row, run.parameters["studio_revision_id"])
        if digest(revision.storyboard) != run.parameters["revision_sha256"]:
            raise ValueError("The immutable storyboard changed")
        composition, sources = composition_inputs(
            session,
            revision,
            [Binding.model_validate(b) for b in run.parameters["bindings"]],
            run.parameters["soundtrack_artifact_id"],
            verify=True,
        )
        if (
            composition != run.parameters["composition"]
            or sources != run.parameters["sources"]
            or digest(native_request(run)) != run.parameters["native_request_sha256"]
        ):
            raise ValueError("The frozen Studio composition or media changed")

    def _start(self, runner, run, allocated, output):
        return runner.request("POST", "/v1/runs/motion", native_request(run))

    def fence_missing_dispatch(self, runner, run):
        return fence_missing_dispatch(runner, run)

    def on_inspection(self, session, run, info):
        if info.get("run_id") != run.id or info.get("executor") != self.name:
            raise ValueError("Studio process ownership changed")
        if (
            not info.get("alive")
            and not info.get("completion_pending")
            and info.get("cleanup_confirmed") is not True
        ):
            raise ValueError("Studio container cleanup still requires inspection")

    def output_metadata(self, output):
        relative = str(PurePosixPath(output).with_suffix(".json"))
        root = get_settings().data_dir.resolve()
        path = safe_join(root, relative)
        if path != root / relative:
            raise ValueError("Studio output report crosses a symlink")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 1 <= info.st_size <= 64000:
                raise ValueError("Studio output report is not a bounded regular file")
            report = json.loads(handle.read(64001))
        if not isinstance(report, dict) or report.get("verified") is not True:
            raise ValueError("Studio export was not verified")
        return report

    def on_success(self, session, run, artifact):
        self.validate_inputs(session, run)
        request = MotionRequest.model_validate(native_request(run))
        report = artifact.metadata_json
        artifact.title = (
            f"{run.parameters['material_title']} · v{run.parameters['storyboard_revision_position']}"
        )
        if (
            report.get("run_id") != run.id
            or report.get("request_sha256") != run.parameters["native_request_sha256"]
            or report.get("observation") != request.observation
            or report.get("frames") != request.composition.frames
            or (report.get("width"), report.get("height"))
            != (request.composition.width, request.composition.height)
            or report.get("fps") != 30
            or report.get("has_audio") is not bool(request.audio_artifact_id)
        ):
            raise ValueError("The Studio export does not match its frozen request")
