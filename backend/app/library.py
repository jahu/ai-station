"""Versioned Library annotations and reversible trash without breaking lineage."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.events import append_event
from app.models import Artifact
from app.serialize import artifact_dict

router = APIRouter(prefix="/api/artifacts")
DB = Annotated[Session, Depends(session_scope)]
DERIVED_LIMIT = 50


def _artifacts_in_order(session: Session, ids: list[str]) -> list[Artifact]:
    ordered = [item for item in dict.fromkeys(ids) if item]
    if not ordered:
        return []
    rows = {row.id: row for row in session.scalars(select(Artifact).where(Artifact.id.in_(ordered)))}
    return [rows[item] for item in ordered if item in rows]


def derived_artifact_ids(session: Session, artifact_id: str, limit: int = DERIVED_LIMIT) -> list[str]:
    parents = func.json_each(Artifact.parent_artifact_ids).table_valued("value")
    # Keep the Artifact mapper in the statement so owner restrictions apply
    # before ordering/limiting. Raw text would bypass the scoped ORM policy.
    rows = session.scalars(
        select(Artifact.id, Artifact.created_at)
        .join(parents, true())
        .where(parents.c.value == artifact_id, Artifact.id != artifact_id)
        .distinct()
        .order_by(Artifact.created_at.desc(), Artifact.id)
        .limit(limit)
    )
    return list(rows)


def lineage_dict(session: Session, artifact: Artifact) -> dict:
    sources = _artifacts_in_order(
        session, [item for item in artifact.parent_artifact_ids if item != artifact.id]
    )
    derived = _artifacts_in_order(session, derived_artifact_ids(session, artifact.id))
    return {
        "id": artifact.id,
        "sources": [artifact_dict(row) for row in sources],
        "derived": [artifact_dict(row) for row in derived],
    }


@router.get("")
def artifacts(
    session: DB,
    run_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    kind: str = Query("", max_length=40, pattern=r"^[a-z_]*$"),
    search: str = Query("", max_length=200),
    view: Literal["active", "trash"] = "active",
    include_internal: bool = False,
):
    statement = select(Artifact)
    if run_id:
        statement = statement.where(Artifact.run_id == str(run_id))
    else:
        statement = statement.where(
            Artifact.trashed_at.is_not(None) if view == "trash" else Artifact.trashed_at.is_(None)
        )
        statement = statement.where(Artifact.purged_at.is_(None))
    if not run_id and not include_internal:
        statement = statement.where(Artifact.metadata_json["internal_media"].as_boolean().is_not(True))
        statement = statement.where(Artifact.metadata_json["internal_data_output"].as_boolean().is_not(True))
    if kind == "files":
        statement = statement.where(Artifact.artifact_type.not_in(["image", "audio", "video"]))
    elif kind == "references":
        statement = statement.where(
            Artifact.mime_type.in_(["application/pdf", "text/plain", "text/markdown"])
        )
    elif kind:
        statement = statement.where(Artifact.artifact_type == kind)
    if search.strip():
        term = search.strip()
        statement = statement.where(
            or_(
                *(
                    column.icontains(term, autoescape=True)
                    for column in (Artifact.title, Artifact.original_filename, Artifact.notes)
                )
            )
        )
    statement = statement.order_by(Artifact.created_at.desc(), Artifact.id).offset(offset).limit(limit)
    return [artifact_dict(row) for row in session.scalars(statement)]


@router.get("/{artifact_id}/lineage")
def lineage(artifact_id: UUID, session: DB):
    row = session.get(Artifact, str(artifact_id))
    if row is None:
        raise HTTPException(404, "Artifact not found")
    return lineage_dict(session, row)


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime | None


class EditArtifact(Version):
    title: str = Field(max_length=200)
    notes: str = Field(default="", max_length=4000)


def mutate(session, artifact_id, expected, values, event):
    from app.data_access import private_for_update

    row = private_for_update(session, Artifact, str(artifact_id))
    if row is None:
        raise HTTPException(404, "Artifact not found")
    if row.purged_at or row.purge_run_id:
        raise HTTPException(409, "This artifact is permanently deleted or deletion has already started")
    if row.library_updated_at != expected:
        raise HTTPException(409, "This artifact changed. Reload it before saving.")
    for key, value in values.items():
        setattr(row, key, value)
    row.library_updated_at = utcnow()
    if row.run_id:
        append_event(session, row.run_id, event, {"artifact_id": row.id})
    session.commit()
    session.refresh(row)
    return artifact_dict(row)


@router.patch("/{artifact_id}")
def edit(artifact_id: UUID, body: EditArtifact, session: DB):
    return mutate(
        session,
        artifact_id,
        body.expected_updated_at,
        {"title": body.title.strip(), "notes": body.notes.strip()},
        "artifact.library_updated",
    )


@router.delete("/{artifact_id}")
def trash(artifact_id: UUID, body: Version, session: DB):
    return mutate(
        session, artifact_id, body.expected_updated_at, {"trashed_at": utcnow()}, "artifact.trashed"
    )


@router.post("/{artifact_id}/restore")
def restore(artifact_id: UUID, body: Version, session: DB):
    return mutate(session, artifact_id, body.expected_updated_at, {"trashed_at": None}, "artifact.restored")
