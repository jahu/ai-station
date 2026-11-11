"""Durable whole-material coordination over the existing audio/shot/export Tasks."""

from datetime import datetime, timedelta
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from app import studio_render
from app.db import utcnow
from app.dependencies import depend_on
from app.models import Artifact, Run, Task
from app.permissions import require
from app.runs import create_run, create_task, run_dict, transition
from app.serialize import artifact_dict
from app.state import TERMINAL, RunStatus
from app.studio_audio_production import ProduceAudio, Voice, create_audio_production
from app.studio_materials import DB, digest, get_material, get_revision, source_snapshot
from app.studio_render import Binding, RenderRequest, create_render
from app.studio_schema import Fields, Storyboard
from app.studio_shots import ShotRequest, enqueue_shot, production
from app.studio_soundtrack import audio_source, router
from app.task_control import cancel_task, lock_task

NAME = "studio_production_step"
INTENT = "studio.material.produce"
PERMISSIONS = ["filesystem_read", "workspace_write"]


class Produce(Fields):
    client_request_id: UUID
    revision_id: UUID
    bindings: list[Binding] = Field(default_factory=list, max_length=60)
    voice: Voice | None = None
    music_model_id: UUID | None = None
    image_model: str | None = Field(default=None, min_length=1, max_length=100)
    video_model_id: UUID | None = None
    reuse_from_run_id: UUID | None = None


def root_run(session, identity, material_id=None):
    root = session.get(Run, str(identity))
    if (
        root is None
        or root.executor_type != NAME
        or root.parameters.get("studio_production_root_id") != root.id
        or root.task.intent != INTENT
        or root.task.metadata_json.get("studio_production_root_id") != root.id
        or material_id
        and root.parameters.get("studio_material_id") != str(material_id)
    ):
        raise HTTPException(404, "Material production not found")
    return root


def children(session, root):
    result = []
    for item in root.metadata_json.get("child_tasks", []):
        task = session.get(Task, item["task_id"])
        primary = session.get(Run, item["run_id"])
        parent = session.get(Run, primary.parent_run_id) if primary else None
        if not (
            task
            and primary
            and parent
            and task.id != root.task_id
            and task.owner_id == root.owner_id
            and primary.task_id == task.id
            and primary.owner_id == root.owner_id
            and task.metadata_json.get("studio_production_root_id") == root.id
            and parent.task_id == root.task_id
            and parent.executor_type == NAME
            and parent.parameters.get("studio_production_root_id") == root.id
            and parent.owner_id == root.owner_id
        ):
            raise ValueError("Material production child ownership changed")
        result.append(task)
        if len(result) > 128:
            raise ValueError("Material production exceeds its child-task bound")
    return result


def all_runs(session, root):
    task_ids = [root.task_id] + [t.id for t in children(session, root)]
    return list(
        session.scalars(select(Run).where(Run.task_id.in_(task_ids)).order_by(Run.created_at, Run.id))
    )


def complete_media(session, identity, kind, *, verify=False):
    source = source_snapshot(session, identity, verify=verify)
    if source["kind"] != kind:
        raise ValueError("A selected take has the wrong media type")
    item = session.get(Artifact, str(identity))
    origin = session.get(Run, item.run_id) if item.run_id else None
    if (
        item.metadata_json.get("partial")
        or item.metadata_json.get("internal_media")
        or origin
        and origin.status != "succeeded"
    ):
        raise ValueError("Choose a complete take from a successful Run")
    return source


def fingerprint(body):
    return digest(body.model_dump(mode="json", exclude={"client_request_id", "reuse_from_run_id"}))


def snapshot_bindings(session, row, revision, body):
    plan = Storyboard.model_validate(revision.storyboard)
    explicit = {b.scene: str(b.artifact_id) for b in body.bindings}
    if len(explicit) != len(body.bindings):
        raise HTTPException(422, "Choose one take per shot")
    generated = {i: s for i, s in enumerate(plan.scenes) if s.visual_kind in {"image", "video"}}
    if explicit.keys() - generated.keys():
        raise HTTPException(422, "Choose takes only for generated shots in this storyboard")
    existing = production(row.id, revision.id, session)
    for i, shot in generated.items():
        if i not in explicit:
            candidates = [
                a
                for a in existing["artifacts"]
                if a["type"] == shot.visual_kind
                and any(
                    r["id"] == a["run_id"] and r["parameters"].get("studio_scene") == i
                    for r in existing["runs"]
                )
            ]
            if candidates:
                explicit[i] = candidates[0]["id"]
    return {
        str(i): complete_media(session, identity, generated[i].visual_kind)
        for i, identity in explicit.items()
    }


def create_production(session, material_id, body):
    row = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, row, body.revision_id)
    key = "studio-production:" + str(body.client_request_id)
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key, Run.parameters["studio_material_id"].as_string() == row.id
        )
    )
    if prior:
        if prior.parameters["request"] != body.model_dump(mode="json"):
            raise HTTPException(409, "This production receipt belongs to another request")
        return prior
    for current in session.scalars(
        select(Run).where(
            Run.executor_type == NAME,
            Run.parameters["studio_material_id"].as_string() == row.id,
            Run.parameters["studio_production_root_id"].as_string() == Run.id,
        )
    ):
        if any(r.status not in TERMINAL for r in all_runs(session, current)):
            raise HTTPException(409, "Material production is already active; inspect or stop it first")
    active_media = session.scalar(
        select(Run.id)
        .where(
            Run.parameters["studio_material_id"].as_string() == row.id,
            Run.parameters["studio_revision_id"].as_string() == revision.id,
            Run.status.not_in(TERMINAL),
            (
                Run.parameters["studio_scene"].as_integer().is_not(None)
                | Run.parameters["studio_audio_root_id"].as_string().is_not(None)
            ),
        )
        .limit(1)
    )
    if active_media:
        raise HTTPException(
            409, "Finish or stop the active shot or soundtrack before starting the whole film"
        )
    plan = Storyboard.model_validate(revision.storyboard)
    ready = studio_render.capabilities()
    if not ready.get("available"):
        raise HTTPException(409, ready.get("reason") or "Prepare local film export before production")
    bindings = snapshot_bindings(session, row, revision, body)
    state = {"revision_id": revision.id, "bindings": bindings, "soundtrack_id": None}
    previous = None
    if body.reuse_from_run_id:
        previous = root_run(session, body.reuse_from_run_id, row.id)
        if previous.parameters["request_sha256"] != fingerprint(body) or any(
            r.status not in TERMINAL for r in all_runs(session, previous)
        ):
            raise HTTPException(409, "Reuse a finished production of this exact saved version and settings")
        old = previous.metadata_json.get("production_state") or {}
        audio_previous = next(
            (
                item["run_id"]
                for item in previous.metadata_json["child_tasks"]
                if session.get(Run, item["run_id"]).executor_type == "studio_audio_step"
            ),
            None,
        )
        if audio_previous:
            state["audio_reuse_id"] = audio_previous
        # Complete results are inspected again; unavailable takes are generated anew.
        for i, source in old.get("bindings", {}).items():
            try:
                if complete_media(session, source["artifact_id"], source["kind"]) == source:
                    bindings.setdefault(i, source)
            except (ValueError, OSError):
                pass
        for child_task in children(session, previous):
            primary_id = next(
                item["run_id"]
                for item in previous.metadata_json["child_tasks"]
                if item["task_id"] == child_task.id
            )
            primary = session.get(Run, primary_id)
            scene = primary.parameters.get("studio_scene")
            if primary.status != "succeeded" or type(scene) is not int or scene >= len(plan.scenes):
                continue
            kind = plan.scenes[scene].visual_kind
            if kind not in {"image", "video"} or str(scene) in bindings:
                continue
            outputs = list(
                session.scalars(
                    select(Artifact).where(Artifact.run_id == primary.id, Artifact.artifact_type == kind)
                )
            )
            for item in outputs:
                try:
                    bindings[str(scene)] = complete_media(session, item.id, kind)
                    break
                except (ValueError, OSError):
                    pass
        if old.get("soundtrack_id"):
            try:
                audio_source(session, old["soundtrack_id"])
                measured = get_revision(session, row, old["revision_id"])
                if measured.source_run_id:
                    mix = session.get(Run, measured.source_run_id)
                    if (
                        mix
                        and mix.executor_type == "studio_soundtrack"
                        and mix.metadata_json.get("soundtrack_artifact_id") == old["soundtrack_id"]
                        and mix.status == "succeeded"
                    ):
                        state.update(revision_id=measured.id, soundtrack_id=old["soundtrack_id"])
            except (ValueError, OSError):
                pass
    if (
        revision.source_run_id
        and body.voice is None
        and body.music_model_id is None
        and not state["soundtrack_id"]
    ):
        mixed = session.get(Run, revision.source_run_id)
        if mixed and mixed.executor_type == "studio_soundtrack" and mixed.status == "succeeded":
            identity = mixed.metadata_json.get("soundtrack_artifact_id")
            if identity:
                audio_source(session, identity)
                state["soundtrack_id"] = identity
    state["soundtrack_source"] = (
        audio_source(session, state["soundtrack_id"]) if state["soundtrack_id"] else None
    )
    from app.image_models import defaults

    choices = defaults(session)["choices"]
    image_choices = {mode: body.image_model or choices[mode] for mode in ("t2i", "recompose")}
    if previous:
        image_choices = previous.parameters["image_choices"]
    video_profile = previous.parameters.get("video_profile") if previous else None
    if any(s.visual_kind == "video" and str(i) not in bindings for i, s in enumerate(plan.scenes)):
        from app.video_models import profile_for

        video_profile = profile_for(session, body.video_model_id)
        if not video_profile.get("available"):
            raise HTTPException(409, video_profile.get("reason") or "Prepare video before producing footage")
    task = create_task(
        session,
        title="Produce film · " + row.title,
        prompt=revision.brief,
        capability="studio.produce",
        intent=INTENT,
    )
    run = create_run(
        session,
        task,
        run_type="planning",
        capability="studio.produce",
        executor_type=NAME,
        execution_target="container",
        operation_key=key,
        permissions=list(PERMISSIONS),
        retry_class="safe",
        parameters={
            "studio_material_id": row.id,
            "studio_revision_id": revision.id,
            "request": body.model_dump(mode="json"),
            "request_sha256": fingerprint(body),
            "revision_sha256": digest(revision.storyboard),
            "image_choices": image_choices,
            "video_profile": video_profile,
            "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
        },
        metadata={"studio_enqueue_only": True, "production_state": state, "child_tasks": []},
    )
    run.parameters = {**run.parameters, "studio_production_root_id": run.id}
    task.metadata_json = {**task.metadata_json, "studio_production_root_id": run.id}
    return run


def attach(session, stage, root, primary):
    if primary.task_id == root.task_id or primary.owner_id != root.owner_id:
        raise ValueError("Material children require their own owned capability Task")
    primary.parent_run_id = stage.id
    primary.task.metadata_json = {**primary.task.metadata_json, "studio_production_root_id": root.id}
    root.metadata_json = {
        **root.metadata_json,
        "child_tasks": [
            *root.metadata_json["child_tasks"],
            {"task_id": primary.task_id, "run_id": primary.id},
        ],
    }
    for child in session.scalars(select(Run).where(Run.task_id == primary.task_id)):
        expiry = min(
            datetime.fromisoformat(
                child.parameters.get("execution_deadline_at", root.parameters["execution_deadline_at"])
            ),
            datetime.fromisoformat(root.parameters["execution_deadline_at"]),
        )
        child.parameters = {
            **child.parameters,
            "studio_production_root_id": root.id,
            "execution_deadline_at": expiry.isoformat(),
        }
    return primary


def follow(session, stage, root, pending):
    next_step = create_run(
        session,
        root.task,
        run_type="planning",
        capability="studio.produce",
        executor_type=NAME,
        execution_target="container",
        parent_run_id=stage.id,
        operation_key="studio-production-next:" + stage.id,
        permissions=list(PERMISSIONS),
        retry_class="safe",
        parameters={
            "studio_production_root_id": root.id,
            "studio_material_id": root.parameters["studio_material_id"],
            "studio_revision_id": root.parameters["studio_revision_id"],
            "pending": pending,
            "execution_deadline_at": root.parameters["execution_deadline_at"],
        },
        metadata={"studio_enqueue_only": True},
    )
    child = session.get(Run, pending["run_id"])
    waits = list(
        session.scalars(select(Run).where(Run.task_id == child.task_id, Run.status.not_in(TERMINAL)))
    )
    for dependency in waits:
        depend_on(session, next_step, dependency)
    return next_step


class StudioProductionExecutor:
    name = NAME

    def execute(self, session, run):
        for p in PERMISSIONS:
            require(run.effective_permissions, p)
        claim = run.worker_id, run.claimed_at
        lock_task(session, run.task)
        session.refresh(run)
        if (run.worker_id, run.claimed_at) != claim:
            return "done"
        if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        root = root_run(session, run.parameters["studio_production_root_id"])
        if root.task_id != run.task_id or root.owner_id != run.owner_id:
            raise ValueError(
                "Continue the original material production; its coordinator cannot move to another Task"
            )
        row = get_material(session, root.parameters["studio_material_id"], active=True)
        original = get_revision(session, row, root.parameters["studio_revision_id"])
        if digest(original.storyboard) != root.parameters["revision_sha256"]:
            raise ValueError("The frozen material storyboard changed")
        state = dict(root.metadata_json["production_state"])
        state["bindings"] = dict(state["bindings"])
        if run.id == root.id:
            for source in state["bindings"].values():
                if complete_media(session, source["artifact_id"], source["kind"], verify=True) != source:
                    raise ValueError("A selected take changed before production")
        body = Produce.model_validate(root.parameters["request"])
        pending = run.parameters.get("pending")
        if pending:
            owned = {t.id for t in children(session, root)}
            child = session.get(Run, pending["run_id"])
            if child is None or child.task_id not in owned:
                raise ValueError("Material prerequisite ownership changed")
            active = list(
                session.scalars(select(Run).where(Run.task_id == child.task_id, Run.status.not_in(TERMINAL)))
            )
            if active:
                follow(session, run, root, pending)
                session.flush()
                session.refresh(run)
                if (run.worker_id, run.claimed_at) != claim or run.status != "running":
                    session.rollback()
                    return "done"
                transition(session, run, RunStatus.SUCCEEDED, event_type="studio.production.waiting")
                session.commit()
                return "done"
            failed = session.scalar(
                select(Run.id).where(Run.task_id == child.task_id, Run.status != "succeeded").limit(1)
            )
            if failed:
                raise ValueError("A material prerequisite did not complete; earlier results are kept")
            if pending["kind"] == "audio":
                mix = session.scalar(
                    select(Run).where(
                        Run.task_id == child.task_id,
                        Run.executor_type == "studio_soundtrack",
                        Run.status == "succeeded",
                    )
                )
                if mix is None:
                    raise ValueError("The complete measured soundtrack is missing")
                audio_source(session, mix.metadata_json["soundtrack_artifact_id"], verify=True)
                state.update(
                    revision_id=mix.metadata_json["studio_revision_id"],
                    soundtrack_id=mix.metadata_json["soundtrack_artifact_id"],
                    soundtrack_source=audio_source(
                        session, mix.metadata_json["soundtrack_artifact_id"], verify=True
                    ),
                )
            elif pending["kind"] == "shot":
                scene = str(pending["scene"])
                shot = Storyboard.model_validate(
                    get_revision(session, row, state["revision_id"]).storyboard
                ).scenes[int(scene)]
                outputs = list(
                    session.scalars(
                        select(Artifact).where(
                            Artifact.run_id == child.id,
                            Artifact.artifact_type == shot.visual_kind,
                            Artifact.trashed_at.is_(None),
                            Artifact.purged_at.is_(None),
                            Artifact.purge_run_id.is_(None),
                        )
                    )
                )
                outputs = [
                    a
                    for a in outputs
                    if not a.metadata_json.get("partial") and not a.metadata_json.get("internal_media")
                ]
                if len(outputs) != 1:
                    raise ValueError("The generated shot needs exactly one complete result")
                state["bindings"][scene] = complete_media(
                    session, outputs[0].id, shot.visual_kind, verify=True
                )
            else:
                raise ValueError("Unknown material prerequisite")
        if (
            state["soundtrack_id"]
            and audio_source(session, state["soundtrack_id"], verify=True) != state["soundtrack_source"]
        ):
            raise ValueError("The completed soundtrack changed before film production")
        revision = get_revision(session, row, state["revision_id"])
        plan = Storyboard.model_validate(revision.storyboard)
        for scene, source in list(state["bindings"].items()):
            shot = plan.scenes[int(scene)]
            if shot.visual_kind != "video":
                continue
            item = session.get(Artifact, source["artifact_id"])
            if item is None:
                raise ValueError("A selected take is no longer available")
            metadata = item.metadata_json
            seconds = metadata.get("duration_seconds")
            if seconds is None and metadata.get("frames") and metadata.get("fps"):
                seconds = metadata["frames"] / metadata["fps"]
            if (
                isinstance(seconds, (int, float))
                and seconds + 1 / 120 < shot.duration_frames / 30 + shot.media_start_seconds
            ):
                if any(b.scene == int(scene) for b in body.bindings):
                    raise ValueError(
                        f"The selected take for shot {int(scene) + 1} is too short for the measured speech; choose a longer take or clear that selection"
                    )
                del state["bindings"][scene]
        root.metadata_json = {**root.metadata_json, "production_state": state}
        if plan.audio != "silent" and not state["soundtrack_id"]:
            child = create_audio_production(
                session,
                row.id,
                ProduceAudio(
                    client_request_id=uuid5(UUID(root.id), "audio"),
                    revision_id=revision.id,
                    reuse_from_run_id=state.get("audio_reuse_id"),
                    voice=body.voice,
                    music_model_id=body.music_model_id,
                ),
            )
            attach(session, run, root, child)
            follow(session, run, root, {"kind": "audio", "run_id": child.id})
        else:
            missing = next(
                (
                    i
                    for i, s in enumerate(plan.scenes)
                    if s.visual_kind in {"image", "video"} and str(i) not in state["bindings"]
                ),
                None,
            )
            if missing is not None:
                shot = plan.scenes[missing]
                child = enqueue_shot(
                    session,
                    row.id,
                    ShotRequest(
                        client_request_id=uuid5(UUID(root.id), "shot:" + str(missing)),
                        revision_id=revision.id,
                        scene=missing,
                        image_model=root.parameters["image_choices"][
                            "recompose" if shot.reference_artifact_ids else "t2i"
                        ]
                        if shot.visual_kind == "image"
                        else None,
                        video_model_id=body.video_model_id if shot.visual_kind == "video" else None,
                    ),
                    observed_video_profile=root.parameters.get("video_profile"),
                )
                attach(session, run, root, child)
                follow(session, run, root, {"kind": "shot", "run_id": child.id, "scene": missing})
            else:
                for source in state["bindings"].values():
                    if complete_media(session, source["artifact_id"], source["kind"], verify=True) != source:
                        raise ValueError("A frozen take changed before export")
                child = create_render(
                    session,
                    row.id,
                    RenderRequest(
                        client_request_id=uuid5(UUID(root.id), "export"),
                        revision_id=revision.id,
                        bindings=[
                            Binding(scene=int(i), artifact_id=s["artifact_id"])
                            for i, s in state["bindings"].items()
                        ],
                        soundtrack_artifact_id=state["soundtrack_id"],
                    ),
                )
                attach(session, run, root, child)
                root.metadata_json = {**root.metadata_json, "render_run_id": child.id}
        session.flush()
        session.refresh(run)
        if (run.worker_id, run.claimed_at) != claim or run.status != "running":
            session.rollback()
            return "done"
        transition(session, run, RunStatus.SUCCEEDED, event_type="studio.production.advanced")
        session.commit()
        return "done"


@router.post("/{material_id}/produce", status_code=202)
def produce(material_id: UUID, body: Produce, session: DB):
    try:
        run = create_production(session, material_id, body)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return run_dict(run)


@router.post("/{material_id}/productions/{run_id}/stop")
def stop(material_id: UUID, run_id: UUID, session: DB):
    get_material(session, material_id)
    root = root_run(session, run_id, material_id)
    result = cancel_task(session, root.task)
    session.commit()
    return result


@router.get("/{material_id}/productions")
def history(material_id: UUID, session: DB):
    row = get_material(session, material_id)
    roots = session.scalars(
        select(Run)
        .where(
            Run.executor_type == NAME,
            Run.parameters["studio_material_id"].as_string() == row.id,
            Run.parameters["studio_production_root_id"].as_string() == Run.id,
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(20)
    )
    values = []
    for root in roots:
        runs = all_runs(session, root)
        active = [r for r in runs if r.status not in TERMINAL]
        render = session.get(Run, root.metadata_json.get("render_run_id", ""))
        output = (
            session.scalar(
                select(Artifact).where(
                    Artifact.run_id == render.id,
                    Artifact.artifact_type == "video",
                    Artifact.mime_type == "video/mp4",
                    Artifact.trashed_at.is_(None),
                    Artifact.purged_at.is_(None),
                    Artifact.purge_run_id.is_(None),
                )
            )
            if render and render.status == "succeeded"
            else None
        )
        if output and (output.metadata_json.get("partial") or output.metadata_json.get("internal_media")):
            output = None
        failed = next((r for r in runs if r.status in {"failed", "interrupted", "canceled"}), None)
        stopped = root.task.metadata_json.get("stop_requested_at")
        status = (
            ("cancel_requested" if active else "canceled")
            if stopped
            else "succeeded"
            if output and not active
            else "failed"
            if failed
            else "running"
            if active
            else "interrupted"
        )
        values.append(
            {
                "root_run": run_dict(root),
                "status": status,
                "runs": [run_dict(r) for r in runs],
                "output": artifact_dict(output) if output else None,
                "measured_revision_id": root.metadata_json["production_state"]["revision_id"],
                "failed_run": run_dict(failed) if failed else None,
            }
        )
    return values
