"""Owner-scoped creative identities, without host paths or execution authority."""

from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, field_validator
from sqlalchemy import select

from app.creative_sessions import DB, Fields
from app.data_access import private_for_update
from app.db import utcnow
from app.models import Artifact, CreativeProject

router = APIRouter(prefix="/api/creative/projects", tags=["creative projects"])
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class Identity(Fields):
    colors: list[Color] = Field(
        default_factory=lambda: ["#A8CC74", "#101311", "#F7F8F4"], min_length=1, max_length=8
    )
    typography: Literal["sans", "humanist", "editorial", "mono"] = "sans"
    visual_direction: str = Field(default="", max_length=4000)
    tone: str = Field(default="", max_length=2000)
    audience: str = Field(default="", max_length=2000)
    language: str = Field(default="", max_length=80)
    editorial_rules: str = Field(default="", max_length=4000)
    audio_direction: str = Field(default="", max_length=2000)


class Defaults(Fields):
    format: Literal["reel", "presentation", "film"] = "reel"
    aspect: Literal["portrait", "landscape", "square"] = "portrait"
    duration_seconds: int = Field(default=30, ge=5, le=600, strict=True)
    audio: Literal["voice_music", "voice", "music", "silent"] = "voice_music"


class Definition(Fields):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    aliases: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    identity: Identity = Field(default_factory=Identity)
    defaults: Defaults = Field(default_factory=Defaults)
    logo_artifact_id: UUID | None = None

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, values):
        result, seen = [], set()
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("Project names and domains must not be blank")
            if value.casefold() not in seen:
                seen.add(value.casefold())
                result.append(value)
        return result


class Update(Definition):
    expected_version: int = Field(ge=1, strict=True)


class Archive(Fields):
    expected_version: int = Field(ge=1, strict=True)
    archived: bool


def project_dict(row):
    return {
        key: deepcopy(getattr(row, key))
        for key in (
            "id",
            "name",
            "description",
            "aliases",
            "identity",
            "defaults",
            "logo_artifact_id",
            "version",
            "created_at",
            "updated_at",
            "archived_at",
        )
    }


def get_project(session, identity, *, lock=False, active=False):
    row = (
        private_for_update(session, CreativeProject, str(identity))
        if lock
        else session.get(CreativeProject, str(identity))
    )
    if row is None:
        raise HTTPException(404, "Creative project not found")
    if active and row.archived_at:
        raise HTTPException(409, "Restore this creative project before creating new material")
    return row


def snapshot(session, identity):
    """Frozen planning context. Project selection grants no tools/permissions."""
    row = get_project(session, identity, active=True)
    return {
        key: value
        for key, value in project_dict(row).items()
        if key not in {"created_at", "updated_at", "archived_at"}
    }


def validate_logo(session, body):
    if not body.logo_artifact_id:
        return
    logo = session.get(Artifact, str(body.logo_artifact_id))
    if (
        logo is None
        or logo.trashed_at
        or logo.purged_at
        or logo.purge_run_id
        or logo.artifact_type != "image"
    ):
        raise HTTPException(404, "Choose an available image from your Library")


def apply(row, body):
    for key, value in body.model_dump(mode="json", exclude={"expected_version"}).items():
        setattr(row, key, value)


@router.post("", status_code=201)
def create(body: Definition, session: DB):
    validate_logo(session, body)
    row = CreativeProject()
    apply(row, body)
    session.add(row)
    session.commit()
    return project_dict(row)


@router.get("")
def listing(
    session: DB, archived: bool = False, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    query = select(CreativeProject).where(
        CreativeProject.archived_at.is_not(None) if archived else CreativeProject.archived_at.is_(None)
    )
    return [
        project_dict(row)
        for row in session.scalars(
            query.order_by(CreativeProject.updated_at.desc(), CreativeProject.id).limit(limit).offset(offset)
        )
    ]


@router.get("/{project_id}")
def detail(project_id: UUID, session: DB):
    return project_dict(get_project(session, project_id))


@router.put("/{project_id}")
def update(project_id: UUID, body: Update, session: DB):
    row = get_project(session, project_id, lock=True)
    if row.version != body.expected_version:
        raise HTTPException(409, "This creative project changed. Reload before saving.")
    validate_logo(session, body)
    apply(row, body)
    row.version += 1
    row.updated_at = utcnow()
    session.commit()
    return project_dict(row)


@router.patch("/{project_id}/archive")
def archive(project_id: UUID, body: Archive, session: DB):
    row = get_project(session, project_id, lock=True)
    if row.version != body.expected_version:
        raise HTTPException(409, "This creative project changed. Reload before saving.")
    row.archived_at = (row.archived_at or utcnow()) if body.archived else None
    row.version += 1
    row.updated_at = utcnow()
    session.commit()
    return project_dict(row)
