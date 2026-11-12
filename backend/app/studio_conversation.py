"""Bounded, local-only source materials from verified same-conversation films.

This is descriptive context, never model-selected row/Run/path authority.
The revision execution path must opt in before exposing this catalog.
"""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Run
from app.studio_materials import digest, get_material, get_revision

MAX_MATERIALS = 6
MAX_WRAPPERS = 24


def prior_visuals(session, revision, render):
    """Actual completed story sources, not the edited MP4 used as new B-roll."""
    from app.studio_materials import source_snapshot
    from app.studio_schema import Storyboard
    from app.studio_storyboard import visual_origin

    plan = Storyboard.model_validate(revision.storyboard)
    selected = {item["scene"]: item["artifact_id"] for item in render.parameters["bindings"]}
    result = []
    for index in range(len(plan.scenes)):
        origin = visual_origin(plan, index)
        shot = plan.scenes[origin]
        identity = selected.get(origin) or (
            str(shot.source_artifact_id) if shot.visual_kind == "library" else None
        )
        if identity:
            source = source_snapshot(session, identity, complete=True)
            if source != render.parameters["sources"].get(identity):
                raise ValueError("The original visual source changed")
            result.append({"scene": index, "artifact_id": identity, "source": source})
    return result


def revision_fingerprint(revision):
    return digest(
        {
            "storyboard": revision.storyboard,
            "options": revision.options,
            "project_snapshot": revision.project_snapshot,
            "brief": revision.brief,
            "sources": revision.sources,
        }
    )


def material_catalog(session, *, owner_id, conversation_id, location):
    if location != "local":
        return {}
    from app.studio_assistant import final_output

    candidates = session.scalars(
        select(Run)
        .where(
            Run.owner_id == owner_id,
            Run.conversation_id == conversation_id,
            Run.executor_type == "assistant_studio",
            Run.status == "succeeded",
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(MAX_WRAPPERS)
    )
    result = {}
    for wrapper in candidates:
        try:
            output = final_output(session, wrapper)
            if output is None:
                continue
            render = session.get(Run, output.run_id)
            material = get_material(session, render.parameters["studio_material_id"], active=True)
            if material.owner_id != owner_id:
                continue
            alias = "material:" + material.id
            if alias in result:
                continue
            revision = get_revision(session, material, render.parameters["studio_revision_id"])
            if revision is None:
                continue
            result[alias] = {
                "wrapper_id": wrapper.id,
                "material_id": material.id,
                "material_version": material.version,
                "revision_id": revision.id,
                "revision_sha256": digest(revision.storyboard),
                "context_sha256": revision_fingerprint(revision),
                "export_artifact_id": output.id,
                "export_sha256": output.sha256,
                "export_run_id": render.id,
                "public": {
                    "title": material.title,
                    "revision": revision.position,
                    "project": revision.project_snapshot.get("name"),
                    "options": deepcopy(revision.options),
                },
            }
        except (HTTPException, ValueError, KeyError, TypeError, OSError):
            # Unavailable old results remain historical data, not authority for
            # another task. A damaged old receipt cannot enable a target alias.
            continue
        if len(result) >= MAX_MATERIALS:
            break
    return result


def public_materials(catalog):
    return {alias: deepcopy(entry["public"]) for alias, entry in catalog.items()}


def source_material(session, captured, *, owner_id, conversation_id, check_version=True):
    """Revalidate the frozen parent before any revision-side queue publication."""
    from app.studio_assistant import final_output

    wrapper = session.get(Run, captured["wrapper_id"])
    if not (
        wrapper
        and wrapper.owner_id == owner_id
        and wrapper.conversation_id == conversation_id
        and wrapper.executor_type == "assistant_studio"
        and wrapper.status == "succeeded"
    ):
        raise ValueError("Choose a completed Studio material from this conversation")
    material = get_material(session, captured["material_id"], lock=True, active=True)
    if material.owner_id != owner_id:
        raise ValueError("The source material owner changed")
    if check_version and material.version != captured["material_version"]:
        raise ValueError("The source material changed. Reload before revising it")
    revision = get_revision(session, material, captured["revision_id"])
    if (
        revision is None
        or digest(revision.storyboard) != captured["revision_sha256"]
        or revision_fingerprint(revision) != captured["context_sha256"]
    ):
        raise ValueError("The source storyboard changed")
    output = final_output(session, wrapper)
    if not (
        output
        and output.id == captured["export_artifact_id"]
        and output.sha256 == captured["export_sha256"]
        and output.run_id == captured["export_run_id"]
    ):
        raise ValueError("The completed source film changed or is unavailable")
    render = session.get(Run, output.run_id)
    if (
        render.parameters.get("studio_material_id") != material.id
        or render.parameters.get("studio_revision_id") != revision.id
    ):
        raise ValueError("The source film no longer matches its saved storyboard")
    return material, revision, render
