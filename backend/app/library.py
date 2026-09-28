"""Versioned Library annotations and reversible trash without breaking lineage."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.events import append_event
from app.models import Artifact
from app.serialize import artifact_dict

router = APIRouter(prefix="/api/artifacts")
DB = Annotated[Session, Depends(session_scope)]


@router.get("")
def artifacts(
    session: DB,
    run_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    kind: str = Query("", max_length=40, pattern=r"^[a-z_]*$"),
    search: str = Query("", max_length=200),
    view: Literal["active", "trash"] = "active",
):
    statement = select(Artifact)
    if run_id:
        statement = statement.where(Artifact.run_id == str(run_id))
    else:
        statement = statement.where(
            Artifact.trashed_at.is_not(None) if view == "trash" else Artifact.trashed_at.is_(None)
        )
    if kind == "files":
        statement = statement.where(Artifact.artifact_type.not_in(["image", "audio", "video"]))
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


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime | None


class EditArtifact(Version):
    title: str = Field(max_length=200)
    notes: str = Field(default="", max_length=4000)


def mutate(session, artifact_id, expected, values, event):
    row = session.get(Artifact, str(artifact_id))
    if row is None:
        raise HTTPException(404, "Artifact not found")
    changed = session.execute(
        update(Artifact)
        .where(Artifact.id == row.id, Artifact.library_updated_at == expected)
        .values(**values, library_updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "This artifact changed. Reload it before saving.")
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
