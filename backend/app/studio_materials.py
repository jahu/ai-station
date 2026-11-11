"""Private materials and immutable editorial versions around ordinary Tasks/Runs."""

import hashlib
import json
from copy import deepcopy
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.creative_projects import Defaults, get_project, snapshot
from app.data_access import private_for_update
from app.db import session_scope, utcnow
from app.models import Artifact, Run, StudioMaterial, StudioRevision
from app.paths import safe_join
from app.studio_schema import Create, SaveRevision, Update

DB = Annotated[Session, Depends(session_scope, scope="function")]
router = APIRouter(prefix="/api/studio/materials", tags=["Studio materials"])


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def material_dict(row):
    return {
        key: deepcopy(getattr(row, key))
        for key in (
            "id",
            "creative_project_id",
            "title",
            "brief",
            "options",
            "version",
            "created_at",
            "updated_at",
            "archived_at",
        )
    }


def revision_dict(row):
    return {
        key: deepcopy(getattr(row, key))
        for key in (
            "id",
            "material_id",
            "parent_revision_id",
            "source_run_id",
            "position",
            "storyboard",
            "sources",
            "project_snapshot",
            "options",
            "brief",
            "created_at",
        )
    }


def get_material(session, identity, *, lock=False, active=False):
    row = (
        private_for_update(session, StudioMaterial, str(identity))
        if lock
        else session.get(StudioMaterial, str(identity))
    )
    if row is None:
        raise HTTPException(404, "Studio material not found")
    if active and row.archived_at:
        raise HTTPException(409, "Restore this material before creating a new version")
    return row


def get_revision(session, row, identity):
    if identity is None:
        return None
    saved = session.get(StudioRevision, str(identity))
    if saved is None or saved.material_id != row.id:
        raise HTTPException(404, "Choose a saved version of this material")
    return saved


def context(session, row):
    return {
        "brief": row.brief,
        "options": Defaults.model_validate(row.options).model_dump(),
        "project_snapshot": snapshot(session, row.creative_project_id) if row.creative_project_id else {},
    }


def source_snapshot(session, identity, *, verify=False):
    from app.config import get_settings
    from app.timelines import verify_bytes

    item = session.get(Artifact, str(identity), populate_existing=True)
    if item is None or item.trashed_at or item.purged_at or item.purge_run_id:
        raise ValueError("Choose available media from your Library")
    allowed = {"image": {"image/png", "image/jpeg", "image/webp"}, "video": {"video/mp4"}}
    if item.mime_type not in allowed.get(item.artifact_type, set()):
        raise ValueError("Storyboard references support inspected images and MP4 footage")
    root = get_settings().data_dir.resolve()
    path = safe_join(root, item.relative_path)
    if (
        not item.relative_path.startswith("artifacts/")
        or path != root / item.relative_path
        or not 1 <= item.size_bytes <= 2 * 1024**3
        or path.stat().st_size != item.size_bytes
    ):
        raise ValueError("The selected media changed")
    value = {
        "artifact_id": item.id,
        "kind": item.artifact_type,
        "relative_path": item.relative_path,
        "sha256": item.sha256,
        "size_bytes": item.size_bytes,
    }
    if verify:
        verify_bytes(value)
    return value


def storyboard_sources(session, storyboard, *, verify=False):
    ids = {
        str(i)
        for shot in storyboard.scenes
        for i in [shot.source_artifact_id, *shot.reference_artifact_ids]
        if i
    }
    result = {i: source_snapshot(session, i, verify=verify) for i in sorted(ids)}
    if sum(v["size_bytes"] for v in result.values()) > 2 * 1024**3:
        raise ValueError("Keep one material within two GiB of source media")
    for shot in storyboard.scenes:
        if any(result[str(i)]["kind"] != "image" for i in shot.reference_artifact_ids):
            raise ValueError("Generated shot references must be images")
    return result


def publish_revision(
    session, row, storyboard, *, client_request_id, request_sha256, frozen, parent=None, source_run_id=None
):
    sources = storyboard_sources(session, storyboard)
    if storyboard.audio != frozen["options"]["audio"]:
        raise ValueError("The storyboard must preserve the selected audio policy")
    position = (
        session.scalar(select(func.max(StudioRevision.position)).where(StudioRevision.material_id == row.id))
        or 0
    ) + 1
    saved = StudioRevision(
        material_id=row.id,
        parent_revision_id=parent.id if parent else None,
        source_run_id=source_run_id,
        client_request_id=str(client_request_id),
        request_sha256=request_sha256,
        position=position,
        storyboard=storyboard.model_dump(mode="json"),
        sources=sources,
        **frozen,
    )
    session.add(saved)
    row.version += 1
    row.updated_at = utcnow()
    session.flush()
    return saved


def create_material(session, body: Create):
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id"}))
    prior = session.get(StudioMaterial, str(body.client_request_id))
    if prior:
        if prior.request_sha256 != fingerprint:
            raise HTTPException(409, "This creation receipt belongs to another material")
        return prior
    project = (
        get_project(session, body.creative_project_id, active=True) if body.creative_project_id else None
    )
    options = body.options or Defaults.model_validate(project.defaults if project else {})
    row = StudioMaterial(
        id=str(body.client_request_id),
        creative_project_id=project.id if project else None,
        title=body.title,
        brief=body.brief,
        options=options.model_dump(),
        request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return row


@router.post("", status_code=201)
def create(body: Create, session: DB):
    try:
        row = create_material(session, body)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "The material creation receipt is already in use") from exc
    return material_dict(row)


@router.get("")
def listing(
    session: DB,
    creative_project_id: UUID | None = None,
    archived: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(StudioMaterial).where(
        StudioMaterial.archived_at.is_not(None) if archived else StudioMaterial.archived_at.is_(None)
    )
    if creative_project_id:
        get_project(session, creative_project_id)
        query = query.where(StudioMaterial.creative_project_id == str(creative_project_id))
    return [
        material_dict(row)
        for row in session.scalars(
            query.order_by(StudioMaterial.updated_at.desc(), StudioMaterial.id).limit(limit).offset(offset)
        )
    ]


@router.get("/{material_id}")
def detail(material_id: UUID, session: DB):
    return material_dict(get_material(session, material_id))


@router.patch("/{material_id}")
def update(material_id: UUID, body: Update, session: DB):
    row = get_material(session, material_id, lock=True)
    if row.version != body.expected_version:
        raise HTTPException(409, "This material changed. Reload before saving.")
    for key in ("title", "brief"):
        if getattr(body, key) is not None:
            setattr(row, key, getattr(body, key))
    if body.options is not None:
        row.options = body.options.model_dump()
    if body.archived is not None:
        row.archived_at = (row.archived_at or utcnow()) if body.archived else None
    row.version += 1
    row.updated_at = utcnow()
    session.commit()
    return material_dict(row)


@router.get("/{material_id}/revisions")
def revisions(
    material_id: UUID, session: DB, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)
):
    row = get_material(session, material_id)
    return [
        revision_dict(r)
        for r in session.scalars(
            select(StudioRevision)
            .where(StudioRevision.material_id == row.id)
            .order_by(StudioRevision.position.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


@router.get("/{material_id}/revisions/{revision_id}")
def revision(material_id: UUID, revision_id: UUID, session: DB):
    return revision_dict(get_revision(session, get_material(session, material_id), revision_id))


@router.post("/{material_id}/revisions", status_code=201)
def save(material_id: UUID, body: SaveRevision, session: DB):
    row = get_material(session, material_id, lock=True, active=True)
    fingerprint = digest(body.model_dump(mode="json", exclude={"client_request_id", "expected_version"}))
    prior = session.scalar(
        select(StudioRevision).where(
            StudioRevision.material_id == row.id,
            StudioRevision.client_request_id == str(body.client_request_id),
        )
    )
    if prior:
        if prior.request_sha256 != fingerprint:
            raise HTTPException(409, "This save receipt belongs to another edit")
        return revision_dict(prior)
    if row.version != body.expected_version:
        raise HTTPException(409, "This material changed. Reload before saving.")
    parent = get_revision(session, row, body.parent_revision_id)
    try:
        saved = publish_revision(
            session,
            row,
            body.storyboard,
            client_request_id=body.client_request_id,
            request_sha256=fingerprint,
            frozen=context(session, row),
            parent=parent,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return revision_dict(saved)


@router.get("/{material_id}/activity")
def activity(material_id: UUID, session: DB, limit: int = Query(30, ge=1, le=100)):
    from app.runs import run_dict

    row = get_material(session, material_id)
    return [
        run_dict(r)
        for r in session.scalars(
            select(Run)
            .where(Run.parameters["studio_material_id"].as_string() == row.id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit)
        )
    ]
