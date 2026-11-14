"""Saved-shot production reuses ordinary image/segmented-video Tasks and receipts."""

import math
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, StrictInt
from sqlalchemy import select

from app.db import utcnow
from app.models import Artifact, Run
from app.runs import create_task, run_dict
from app.serialize import artifact_dict
from app.state import TERMINAL
from app.studio_materials import DB, digest, get_material, get_revision, source_snapshot
from app.studio_render import router
from app.studio_schema import Fields, Storyboard
from app.studio_storyboard import source_end_seconds
from app.studio_visual_direction import visual_color_words
from app.video_schema import MAX_VIDEO_SECONDS


class ShotRequest(Fields):
    client_request_id: UUID
    revision_id: UUID
    scene: StrictInt = Field(ge=0, le=59)
    image_model: str | None = Field(default=None, min_length=1, max_length=100)
    video_model_id: UUID | None = None


def shot_prompt(revision, shot):
    """Keep direction visual, generic and frozen; no narration or caption leakage."""
    identity = revision.project_snapshot.get("identity") or {}
    parts = [shot.visual_brief]
    if shot.framing:
        parts.append("Camera and framing: " + shot.framing)
    if identity.get("visual_direction"):
        parts.append("Shared visual direction: " + identity["visual_direction"])
    parts.append(
        "Keep visible subjects, lighting and materials coherent. Keep every generated visual surface unlettered; use nonverbal shapes and material detail. No writing, captions, labels, lettering or pseudo-text, even tiny or blurred. Typography is added separately by the renderer."
    )
    parts.append(
        "Apply color directions only to actual objects, materials, backgrounds and lighting. No palette charts, color sample bars, swatches or visible color codes."
    )
    return visual_color_words("\n\n".join(parts))


def enqueue_shot(session, material_id, body, *, observed_video_profile=None):
    row = get_material(session, material_id, lock=True, active=True)
    revision = get_revision(session, row, body.revision_id)
    plan = Storyboard.model_validate(revision.storyboard)
    if body.scene >= len(plan.scenes):
        raise HTTPException(422, "Choose a shot in this saved storyboard")
    shot = plan.scenes[body.scene]
    if shot.visual_kind not in {"image", "video"}:
        raise HTTPException(
            422,
            "Generate the original source scene; shared, Library and editorial scenes do not need a new take",
        )
    if (shot.visual_kind == "image" and body.video_model_id) or (
        shot.visual_kind == "video" and body.image_model
    ):
        raise HTTPException(422, "Choose the model for this shot's medium")
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id"}))
    key = "studio-shot:" + str(body.client_request_id)
    prior = session.scalar(
        select(Run).where(
            Run.operation_key == key, Run.parameters["studio_material_id"].as_string() == row.id
        )
    )
    if prior:
        if prior.parameters.get("studio_shot_request_sha256") != fingerprint:
            raise HTTPException(409, "This generation receipt belongs to another shot or model")
        return prior
    active = session.scalar(
        select(Run.id)
        .where(
            Run.parameters["studio_material_id"].as_string() == row.id,
            Run.parameters["studio_revision_id"].as_string() == revision.id,
            Run.parameters["studio_scene"].as_integer() == body.scene,
            Run.status.not_in(TERMINAL),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(409, "This shot is already being generated. Its existing Run remains available.")
    references = [source_snapshot(session, i) for i in shot.reference_artifact_ids]
    if any(source["kind"] != "image" for source in references):
        raise HTTPException(422, "Generated shot references must be images")
    prompt = shot_prompt(revision, shot)
    deadline = (utcnow() + timedelta(hours=24 if shot.visual_kind == "video" else 4)).isoformat()
    task = create_task(
        session, title=f"Shot {body.scene + 1} · {row.title}", prompt=prompt, capability="studio.shot"
    )
    if shot.visual_kind == "image":
        from app.image_models import choice, defaults
        from app.image_schema import ImageRequest
        from app.images import create_image_run

        mode = "recompose" if references else "t2i"
        selected = choice(session, body.image_model or defaults(session)["choices"][mode])
        selection = {"backend": selected["backend"]}
        if selected["definition_id"]:
            selection["model_id"] = selected["definition_id"]
        if selected["backend"] in {"krea2", "juggernaut"}:
            selection["seed"] = body.client_request_id.int % 2**31
        width, height = {"portrait": (864, 1536), "landscape": (1536, 864), "square": (1024, 1024)}[
            revision.options["aspect"]
        ]
        request = ImageRequest.model_validate(
            {
                "mode": mode,
                "prompt": prompt,
                "prompt_style": "instruction" if references else "prompt",
                "input_artifact_ids": shot.reference_artifact_ids,
                "width": width,
                "height": height,
                **selection,
            }
        )
        main = create_image_run(session, request, task=task)
    else:
        from app.media_jobs import LongVideoRequest, publish_video
        from app.video_models import profile_for

        if len(prompt) > 2000:
            raise HTTPException(422, "Keep this shot's combined visual direction within 2000 characters")
        seconds = math.ceil(source_end_seconds(plan, body.scene))
        if seconds > MAX_VIDEO_SECONDS:
            raise HTTPException(
                422,
                "Keep one generated source within five minutes; shorten the trim window or use separate source shots",
            )
        profile = profile_for(
            session,
            body.video_model_id,
            observed_video_profile,
            requested_geometry=(480, 832) if revision.options["aspect"] == "portrait" else None,
        )
        if not profile.get("available"):
            raise HTTPException(409, profile.get("reason", "Prepare local video before generating footage"))
        if len(references) > 1:
            raise HTTPException(422, "A video shot accepts one first-frame reference; save its exact choice")
        recipe = profile.get("operation_recipe") or {}
        if recipe.get("image_required") and not references:
            raise HTTPException(422, "This video model needs one first-frame image; choose a shot reference")
        if recipe and revision.options["aspect"] == "portrait" and recipe["width"] > recipe["height"]:
            raise HTTPException(
                422,
                "This video model supports landscape footage; choose a portrait-capable model for this shot",
            )
        request = LongVideoRequest(
            client_request_id=body.client_request_id,
            prompt=prompt,
            width=recipe.get("width", 704 if revision.options["aspect"] == "portrait" else 1280),
            height=recipe.get("height", 1280 if revision.options["aspect"] == "portrait" else 704),
            steps=recipe.get("steps", 20),
            cfg=recipe.get("cfg", 5),
            duration_seconds=max(1, seconds),
            composition_mode="continuous",
            seed=body.client_request_id.int % 2**31,
            model_id=body.video_model_id,
            image_artifact_id=shot.reference_artifact_ids[0] if references else None,
            memory_profile=profile.get("recommended_memory_profile", "default"),
        )
        publish_video(session, request, task=task, observed_profile=profile, execution_deadline_at=deadline)
        main = session.get(Run, task.metadata_json["media_plan"]["compose_run_id"])
    main.operation_key = key
    shared = {
        "studio_material_id": row.id,
        "studio_revision_id": revision.id,
        "studio_scene": body.scene,
        "studio_primary_run_id": main.id,
        "studio_shot_request_sha256": fingerprint,
        "studio_storyboard_sha256": digest(revision.storyboard),
        "project_snapshot": revision.project_snapshot,
        "studio_shot": shot.model_dump(mode="json"),
        "studio_source_observations": references,
        "execution_deadline_at": deadline,
    }
    for child in session.scalars(select(Run).where(Run.task_id == task.id)):
        child.parameters = {**child.parameters, **shared}
    return main


@router.post("/{material_id}/shots", status_code=202)
def generate_shot(material_id: UUID, body: ShotRequest, session: DB):
    try:
        run = enqueue_shot(session, material_id, body)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return run_dict(run)


def visual_versions(session, row, revision):
    """Measured-audio edits retain their actual takes; a rewritten shot does not."""
    ids = {revision.id}
    current = revision
    for _ in range(10):
        origin = session.get(Run, current.source_run_id) if current.source_run_id else None
        if (
            not origin
            or origin.executor_type != "studio_soundtrack"
            or not current.parent_revision_id
            or origin.metadata_json.get("studio_revision_id") != current.id
            or origin.parameters.get("studio_revision_id") != current.parent_revision_id
        ):
            break
        parent = get_revision(session, row, current.parent_revision_id)
        left = Storyboard.model_validate(current.storyboard).model_dump(mode="json")
        right = Storyboard.model_validate(parent.storyboard).model_dump(mode="json")
        for plan in (left, right):
            for shot in plan["scenes"]:
                shot.pop("duration_frames")
        if (
            left != right
            or current.project_snapshot != parent.project_snapshot
            or current.options != parent.options
            or parent.id in ids
        ):
            break
        ids.add(parent.id)
        current = parent
    return ids


@router.get("/{material_id}/revisions/{revision_id}/production")
def production(material_id: UUID, revision_id: UUID, session: DB):
    row = get_material(session, material_id)
    revision = get_revision(session, row, revision_id)
    runs = list(
        session.scalars(
            select(Run)
            .where(
                Run.parameters["studio_material_id"].as_string() == row.id,
                Run.parameters["studio_revision_id"].as_string().in_(visual_versions(session, row, revision)),
                Run.parameters["studio_scene"].as_integer().is_not(None),
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1000)
        )
    )
    outputs = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.run_id.in_([r.id for r in runs]),
                Artifact.trashed_at.is_(None),
                Artifact.purged_at.is_(None),
                Artifact.purge_run_id.is_(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    )
    successful = {r.id for r in runs if r.status == "succeeded"}
    return {
        "runs": [run_dict(r) for r in runs],
        "artifacts": [
            artifact_dict(a)
            for a in outputs
            if a.run_id in successful
            and a.artifact_type in {"image", "video"}
            and not a.metadata_json.get("partial")
            and not a.metadata_json.get("internal_media")
        ],
    }


def verify_shot_sources(session, run):
    if "studio_shot" not in run.parameters:
        return
    row = get_material(session, run.parameters["studio_material_id"])
    revision = get_revision(session, row, run.parameters["studio_revision_id"])
    if digest(revision.storyboard) != run.parameters["studio_storyboard_sha256"]:
        raise ValueError("The saved shot changed")
    for frozen in run.parameters["studio_source_observations"]:
        if source_snapshot(session, frozen["artifact_id"], verify=True) != frozen:
            raise ValueError("A Studio shot reference changed")


@router.post("/{material_id}/shots/{run_id}/stop")
def stop_shot(material_id: UUID, run_id: UUID, session: DB):
    from app.task_control import cancel_task

    row = get_material(session, material_id)
    run = session.get(Run, str(run_id))
    if (
        run is None
        or run.parameters.get("studio_material_id") != row.id
        or "studio_shot" not in run.parameters
    ):
        raise HTTPException(404, "Studio shot Run not found")
    result = cancel_task(session, run.task)
    session.commit()
    return result
