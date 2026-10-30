"""Explicit administrator inspection, never an impersonated execution session.

Stored data only: no discovery, endpoint probes, secret resolution or workload
dispatch. The target owner is fixed before counts, paging or identity lookups.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select

from app import models as m
from app import serialize as s
from app.accounts import _actor, public_user
from app.accounts_api import DB, Actor
from app.data_access import ScopedSession, data_session_for
from app.events import event_dict
from app.personal_settings import KEYS
from app.redact import redact_obj
from app.runs import run_dict

router = APIRouter(prefix="/api/admin/users/{user_id}/workspace", tags=["account inspection"])
Category = Literal[
    "conversations",
    "artifacts",
    "runs",
    "tasks",
    "memory",
    "agents",
    "projects",
    "approvals",
    "providers",
    "connectors",
]
# Models, search columns and serializers are code-owned, not caller-supplied.
COLLECTIONS = {
    "conversations": (m.Conversation, (m.Conversation.title,), s.conversation_dict),
    "artifacts": (m.Artifact, (m.Artifact.title, m.Artifact.original_filename), s.artifact_dict),
    "runs": (m.Run, (m.Run.capability, m.Run.executor_type, m.Run.status), run_dict),
    "tasks": (m.Task, (m.Task.title, m.Task.prompt), s.task_dict),
    "memory": (m.MemoryEntry, (m.MemoryEntry.content,), s.memory_dict),
    "agents": (m.Agent, (m.Agent.name, m.Agent.goal), s.agent_dict),
    "projects": (m.Project, (m.Project.name,), s.project_dict),
    "approvals": (m.Approval, (m.Approval.action, m.Approval.reason), s.approval_dict),
    "providers": (m.ChatProvider, (m.ChatProvider.name,), None),
    "connectors": (m.Connector, (m.Connector.name,), None),
}


def inspection(user_id: UUID, actor: Actor, auth: DB):
    # The actual actor and device are revalidated for every request, including
    # range requests. Disabled subjects remain inspectable; disabled actors do not.
    # Release the dependency's coordination transaction before opening the
    # separate scoped reader (SQLite uses BEGIN IMMEDIATE for all transactions).
    auth.commit()
    with data_session_for(actor, inspect_all=True, inspection_owner_id=str(user_id)) as session:
        yield session


Data = Annotated[ScopedSession, Depends(inspection)]


def record_dict(category, row):
    serializer = COLLECTIONS[category][2]
    if serializer:
        return redact_obj(serializer(row))
    # Deliberately do not call provider_dict/connector_dict: those may inspect
    # credential availability. Stored credentials and their paths stay excluded.
    record = {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "enabled": row.enabled,
        "created_at": s.iso(row.created_at),
        "updated_at": s.iso(row.updated_at),
        "credential_configured": bool(row.secret_ref),
    }
    if category == "providers":
        record.update(endpoint=row.endpoint, location=row.location, default_model=row.default_model)
    else:
        config = row.config_json or {}
        visible = {key: config[key] for key in ("url", "repository", "provider", "symbols") if key in config}
        smtp = config.get("smtp")
        if isinstance(smtp, dict):
            visible["smtp"] = {
                key: smtp[key] for key in ("host", "port", "username", "sender", "security") if key in smtp
            }
        record.update(
            config=visible,
            capabilities=row.capabilities,
            status=row.status,
            health=row.health,
            last_run_id=row.last_run_id,
        )
    return redact_obj(record)


def _row(session, category, identity):
    row = session.get(COLLECTIONS[category][0], str(identity))
    if row is None:
        raise HTTPException(404, "Record is unavailable in this workspace")
    return row


@router.get("")
def overview(user_id: UUID, actor: Actor, auth: DB, data: Data, response: Response):
    _actor(auth, actor, admin=True)
    user = auth.get(m.User, str(user_id))
    if user is None:
        raise HTTPException(404, "Account is unavailable")
    response.headers["Cache-Control"] = "private, no-store"
    preferences = list(
        auth.scalars(
            select(m.UserSetting).where(m.UserSetting.user_id == str(user_id), m.UserSetting.key.in_(KEYS))
        )
    )
    subject = public_user(user)
    values = redact_obj({row.key: row.value for row in preferences})
    auth.commit()
    return {
        "user": subject,
        "read_only": True,
        "counts": {
            name: data.scalar(select(func.count()).select_from(model))
            for name, (model, _, _) in COLLECTIONS.items()
        },
        "preferences": values,
    }


@router.get("/{category}")
def collection(
    category: Category,
    data: Data,
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200),
):
    model, columns, _ = COLLECTIONS[category]
    filters = (
        [or_(*(column.icontains(search.strip(), autoescape=True) for column in columns))]
        if search.strip()
        else []
    )
    timestamp = model.requested_at if category == "approvals" else model.created_at
    rows = data.scalars(
        select(model).where(*filters).order_by(timestamp.desc(), model.id).offset(offset).limit(limit)
    )
    items = []
    for row in rows:
        title = next(
            (
                getattr(row, key, None)
                for key in ("title", "name", "original_filename", "action", "capability", "content")
                if getattr(row, key, None)
            ),
            row.id,
        )
        status = getattr(row, "status", None) or getattr(row, "resolution", None)
        if category == "artifacts":
            status = (
                "Deleted"
                if row.purged_at
                else "Deleting"
                if row.purge_run_id
                else "Trash"
                if row.trashed_at
                else row.artifact_type
            )
        if category == "memory":
            status = "Pinned" if row.pinned else "Enabled" if row.enabled else "Disabled"
        items.append(
            {
                "id": row.id,
                "title": redact_obj(str(title)[:200]),
                "status": status,
                "created_at": s.iso(getattr(row, timestamp.key)),
            }
        )
    return {
        "items": items,
        "total": data.scalar(select(func.count()).select_from(model).where(*filters)),
        "offset": offset,
        "limit": limit,
    }


@router.get("/artifacts/{record_id}/file")
def artifact_file(record_id: UUID, data: Data, thumbnail: bool = False):
    from app.images import artifact_response

    response = artifact_response(_row(data, "artifacts", record_id), thumbnail=thumbnail)
    response.headers["Cache-Control"] = "private, no-store"
    data.rollback()  # Preserve range streaming without holding a SQLite snapshot.
    return response


@router.get("/{category}/{record_id}")
def detail(category: Category, record_id: UUID, data: Data):
    return record_dict(category, _row(data, category, record_id))


@router.get("/{category}/{record_id}/entries")
def entries(
    category: Literal["conversations", "runs"],
    record_id: UUID,
    data: Data,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    _row(data, category, record_id)
    if category == "conversations":
        model, parent, order, serializer = (
            m.Message,
            m.Message.conversation_id,
            (m.Message.created_at, m.Message.id),
            s.message_dict,
        )
    else:
        model, parent, order, serializer = m.RunEvent, m.RunEvent.run_id, (m.RunEvent.sequence,), event_dict
    condition = parent == str(record_id)
    rows = data.scalars(select(model).where(condition).order_by(*order).offset(offset).limit(limit))
    return {
        "items": [redact_obj(serializer(row)) for row in rows],
        "total": data.scalar(select(func.count()).select_from(model).where(condition)),
        "offset": offset,
        "limit": limit,
    }
