"""Durable creative workspaces reuse existing typed generation builders and Runs."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data_access import private_for_update
from app.db import session_scope, utcnow
from app.models import Artifact, CreativeSession, CreativeTurn, Run
from app.runs import run_dict
from app.serialize import artifact_dict

Capability = Literal["images", "video", "music", "speech", "avatars"]
DB = Annotated[Session, Depends(session_scope)]
router = APIRouter(prefix="/api/creative/sessions", tags=["creative workspaces"])


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def bounded(value):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 65536:
        raise ValueError("Keep the saved creative draft within 64 KiB")
    return value


class Create(Fields):
    capability: Capability
    title: str = Field(default="New creation", min_length=1, max_length=160)


class Update(Fields):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    draft: dict[str, JsonValue] | None = None
    archived: bool | None = None

    @field_validator("draft")
    @classmethod
    def limit_draft(cls, value):
        return bounded(value)


class Generate(Fields):
    client_request_id: UUID
    parameters: dict[str, JsonValue]
    parent_turn_id: UUID | None = None
    feedback: str = Field(default="", max_length=4000)

    @field_validator("parameters")
    @classmethod
    def limit_parameters(cls, value):
        return bounded(value)


def session_dict(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "capability",
            "title",
            "draft",
            "version",
            "created_at",
            "updated_at",
            "archived_at",
        )
    }


def get_session(session, identity, *, lock=False):
    row = (
        private_for_update(session, CreativeSession, str(identity))
        if lock
        else session.get(CreativeSession, str(identity))
    )
    if row is None:
        raise HTTPException(404, "Creative workspace not found")
    return row


@router.post("", status_code=201)
def create(body: Create, session: DB):
    row = CreativeSession(capability=body.capability, title=body.title)
    session.add(row)
    session.commit()
    return session_dict(row)


@router.get("")
def list_sessions(
    session: DB,
    capability: Capability | None = None,
    archived: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(CreativeSession).where(
        CreativeSession.archived_at.is_not(None) if archived else CreativeSession.archived_at.is_(None)
    )
    if capability:
        query = query.where(CreativeSession.capability == capability)
    return [
        session_dict(row)
        for row in session.scalars(
            query.order_by(CreativeSession.updated_at.desc(), CreativeSession.id).limit(limit).offset(offset)
        )
    ]


@router.patch("/{session_id}")
def update(session_id: UUID, body: Update, session: DB):
    row = get_session(session, session_id, lock=True)
    if row.version != body.expected_version:
        raise HTTPException(409, "This workspace changed. Reload before saving.")
    if body.title is not None:
        row.title = body.title
    if body.draft is not None:
        row.draft = body.draft
    if body.archived is not None:
        row.archived_at = (row.archived_at or utcnow()) if body.archived else None
    row.version += 1
    row.updated_at = utcnow()
    session.commit()
    return session_dict(row)


def turn_dict(session, turn):
    run = session.get(Run, turn.run_id)
    artifacts = session.scalars(
        select(Artifact)
        .join(Run, Artifact.run_id == Run.id)
        .where(Run.task_id == turn.task_id, Artifact.artifact_type.in_(["image", "video", "audio"]))
        .order_by(Artifact.created_at, Artifact.id)
    )
    return {
        "id": turn.id,
        "position": turn.position,
        "parent_turn_id": turn.parent_turn_id,
        "task_id": turn.task_id,
        "run_id": turn.run_id,
        "feedback": turn.feedback,
        "parameters": turn.request_parameters,
        "created_at": turn.created_at,
        "run": run_dict(run) if run else None,
        "artifacts": [artifact_dict(row) for row in artifacts],
    }


@router.get("/{session_id}")
def detail(
    session_id: UUID,
    session: DB,
    before: int | None = Query(None, ge=1),
    limit: int = Query(30, ge=1, le=100),
):
    row = get_session(session, session_id)
    query = select(CreativeTurn).where(CreativeTurn.session_id == row.id)
    if before is not None:
        query = query.where(CreativeTurn.position < before)
    turns = list(session.scalars(query.order_by(CreativeTurn.position.desc()).limit(limit + 1)))
    has_more = len(turns) > limit
    turns = turns[:limit]
    return {
        **session_dict(row),
        "turns": [turn_dict(session, turn) for turn in reversed(turns)],
        "next_before": turns[-1].position if has_more else None,
    }


def builder(capability):
    # Fixed dispatch only: no executor names, tool lists, paths or commands from
    # a workspace record. Each existing request model enforces its own inputs.
    from app.audio import SpeechRequest, create_audio_run
    from app.avatars import AvatarRequest, create_avatar_run
    from app.images import ImageRequest, create_image_run
    from app.music import MusicRequest, create_music_run
    from app.video import VideoRequest, create_video_run

    return {
        "images": (ImageRequest, create_image_run),
        "video": (VideoRequest, create_video_run),
        "music": (MusicRequest, create_music_run),
        "speech": (SpeechRequest, create_audio_run),
        "avatars": (AvatarRequest, create_avatar_run),
    }[capability]


@router.post("/{session_id}/generate", status_code=202)
def generate(session_id: UUID, body: Generate, session: DB):
    row = get_session(session, session_id, lock=True)
    if row.archived_at:
        raise HTTPException(409, "Restore this workspace before generating")
    digest = hashlib.sha256(
        json.dumps(
            body.model_dump(mode="json", exclude={"client_request_id"}), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    prior = session.scalar(
        select(CreativeTurn).where(
            CreativeTurn.session_id == row.id, CreativeTurn.client_request_id == str(body.client_request_id)
        )
    )
    if prior:
        if prior.request_sha256 != digest:
            raise HTTPException(409, "This submission ID already belongs to a different generation")
        return turn_dict(session, prior)
    if body.parent_turn_id:
        parent = session.get(CreativeTurn, str(body.parent_turn_id))
        if parent is None or parent.session_id != row.id:
            raise HTTPException(404, "Choose a previous version in this workspace")
    request_model, create_run = builder(row.capability)
    parameters = dict(body.parameters)
    if "client_request_id" in request_model.model_fields:
        parameters["client_request_id"] = str(body.client_request_id)
    try:
        request = request_model.model_validate(parameters)
    except ValidationError as exc:
        raise HTTPException(422, "Check generation settings: " + str(exc)) from exc
    if row.capability == "images" and request.video_prompt:
        from app.video import capabilities

        if not capabilities()["available"]:
            raise HTTPException(409, "Local video needs setup before queuing an animated result")
    try:
        run = create_run(session, request)
    except IntegrityError as exc:
        session.rollback()
        # Some existing generators use the receipt as their Task UUID. A
        # collision must reveal neither foreign content nor a database error.
        raise HTTPException(409, "This submission ID is already in use. Start a new generation.") from exc
    if session.scalar(select(CreativeTurn.id).where(CreativeTurn.run_id == run.id)):
        raise HTTPException(409, "This generation already belongs to a creative workspace")
    position = (
        session.scalar(select(func.max(CreativeTurn.position)).where(CreativeTurn.session_id == row.id)) or 0
    ) + 1
    turn = CreativeTurn(
        session_id=row.id,
        task_id=run.task_id,
        run_id=run.id,
        parent_turn_id=str(body.parent_turn_id) if body.parent_turn_id else None,
        client_request_id=str(body.client_request_id),
        request_sha256=digest,
        position=position,
        feedback=body.feedback,
        request_parameters=request.model_dump(mode="json"),
    )
    session.add(turn)
    session.flush()
    from app.events import append_event

    append_event(
        session,
        run.id,
        "creative.turn.created",
        {"session_id": row.id, "turn_id": turn.id, "parent_turn_id": turn.parent_turn_id},
    )
    row.draft = turn.request_parameters
    row.version += 1
    row.updated_at = utcnow()
    session.commit()
    return turn_dict(session, turn)
