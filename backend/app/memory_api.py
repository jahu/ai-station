"""Inspectable user memory with immutable scope and source provenance."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.memory import delete_memory, search_memory, upsert_memory
from app.models import Agent, Conversation, MemoryEntry, Message, Project, Run
from app.serialize import memory_dict

router = APIRouter(prefix="/api/memory", tags=["memory"])
DB = Annotated[Session, Depends(session_scope)]
Scope = Literal["global", "conversation", "project", "agent"]
Kind = Literal["fact", "decision", "preference", "project_context", "summary", "observation", "procedure"]


class MemoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=16000)
    memory_type: Kind = "fact"
    tags: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=20
    )
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    pinned: StrictBool = False


class MemoryCreate(MemoryBody):
    scope: Scope = "global"
    scope_id: UUID | None = None
    source_run_id: UUID | None = None
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None

    @model_validator(mode="after")
    def scope_target(self):
        if (self.scope == "global") != (self.scope_id is None):
            raise ValueError("Global memories have no target; other scopes require a target UUID")
        return self


class MemoryUpdate(MemoryBody):
    expected_updated_at: datetime
    enabled: StrictBool = True


class MemoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime


def entry_or_error(session, entry_id):
    entry = session.get(MemoryEntry, str(entry_id))
    if entry is None:
        raise HTTPException(404, "Memory entry not found")
    return entry


@router.get("")
def memories(
    session: DB,
    q: str = Query("", max_length=500),
    scope: Scope | None = None,
    scope_id: UUID | None = None,
    tag: str | None = Query(None, max_length=60),
    include_disabled: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return [
        memory_dict(row)
        for row in search_memory(
            session,
            q,
            scope=scope,
            scope_id=str(scope_id) if scope_id else None,
            tag=tag,
            include_disabled=include_disabled,
            limit=limit,
            offset=offset,
        )
    ]


@router.post("", status_code=201)
def create_memory(body: MemoryCreate, session: DB):
    if body.scope != "global":
        model = {"conversation": Conversation, "project": Project, "agent": Agent}[body.scope]
        if session.get(model, str(body.scope_id)) is None:
            raise HTTPException(422, "Memory scope target does not exist")
    source_run = session.get(Run, str(body.source_run_id)) if body.source_run_id else None
    source_message = session.get(Message, str(body.source_message_id)) if body.source_message_id else None
    if body.source_run_id and source_run is None or body.source_message_id and source_message is None:
        raise HTTPException(422, "Memory source does not exist")
    conversation_id = str(body.source_conversation_id) if body.source_conversation_id else None
    if source_message:
        if conversation_id and conversation_id != source_message.conversation_id:
            raise HTTPException(422, "Message and conversation provenance disagree")
        conversation_id = source_message.conversation_id
        if source_run and source_message.run_id != source_run.id:
            raise HTTPException(422, "Message and Run provenance disagree")
        if source_message.run_id and not source_run:
            source_run = session.get(Run, source_message.run_id)
    if source_run and source_run.conversation_id:
        if conversation_id and conversation_id != source_run.conversation_id:
            raise HTTPException(422, "Run and conversation provenance disagree")
        conversation_id = source_run.conversation_id
    if conversation_id and session.get(Conversation, conversation_id) is None:
        raise HTTPException(422, "Source conversation does not exist")
    if body.scope == "conversation" and conversation_id and str(body.scope_id) != conversation_id:
        raise HTTPException(422, "Conversation memory must reference its own conversation")
    if body.scope in {"project", "agent"} and source_run:
        if getattr(source_run, f"{body.scope}_id") != str(body.scope_id):
            raise HTTPException(422, "Source Run belongs to a different scope")
    entry = upsert_memory(
        session,
        **body.model_dump(
            exclude={"scope_id", "source_run_id", "source_message_id", "source_conversation_id"}
        ),
        scope_id=str(body.scope_id) if body.scope_id else "",
        source_run_id=source_run.id if source_run else None,
        source_conversation_id=conversation_id,
        source_message_id=source_message.id if source_message else None,
    )
    session.commit()
    return memory_dict(entry)


@router.get("/{entry_id}")
def memory_detail(entry_id: UUID, session: DB):
    return memory_dict(entry_or_error(session, entry_id))


@router.put("/{entry_id}")
def update_memory(entry_id: UUID, body: MemoryUpdate, session: DB):
    entry = entry_or_error(session, entry_id)
    if entry.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Memory changed. Reload before saving.")
    upsert_memory(
        session,
        scope=entry.scope,
        entry_id=entry.id,
        **body.model_dump(exclude={"enabled", "expected_updated_at"}),
    )
    entry.enabled = body.enabled
    entry.updated_at = utcnow()
    session.commit()
    return memory_dict(entry)


@router.delete("/{entry_id}", status_code=204)
def remove_memory(entry_id: UUID, body: MemoryDelete, session: DB):
    entry = entry_or_error(session, entry_id)
    if entry.updated_at != body.expected_updated_at:
        raise HTTPException(409, "Memory changed. Reload before deleting.")
    delete_memory(session, entry.id)
    session.commit()
