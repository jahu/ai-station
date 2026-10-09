"""Bounded, read-only activity projections from persisted control-plane state."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.maintenance import interrupted_runs
from app.models import Agent, Artifact, Conversation, Notice, Run, RuntimeInstance, Task
from app.notices import notice_dict
from app.serialize import iso
from app.state import ACTIVE

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
DB = Annotated[Session, Depends(session_scope)]


def agent_summary(row):
    return {
        "id": row.id,
        "name": row.name,
        "model": row.model,
        "trigger": row.trigger,
        "next_run_at": iso(row.next_run_at),
        "last_status": row.last_status,
    }


@router.get("")
def overview(session: DB):
    now = utcnow()
    # Separate bounded queries prevent a busy run queue from hiding schedules or outputs.
    active = session.execute(
        select(Run, Task.title)
        .join(Task, Run.task_id == Task.id)
        .where(Run.status.in_(ACTIVE))
        .order_by(case((Run.status == "queued", 1), else_=0), Run.created_at, Run.id)
        .limit(8)
    ).all()
    enabled = select(Agent).where(Agent.enabled.is_(True))
    upcoming = session.scalars(
        enabled.where(Agent.trigger != "manual", Agent.next_run_at.is_not(None))
        .order_by(Agent.next_run_at, Agent.id)
        .limit(6)
    ).all()
    agents = session.scalars(enabled.order_by(Agent.updated_at.desc(), Agent.id).limit(6)).all()
    conversations = session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id).limit(5)
    ).all()
    artifacts = session.scalars(
        select(Artifact)
        .where(Artifact.run_id.is_not(None), Artifact.trashed_at.is_(None))
        .order_by(Artifact.created_at.desc(), Artifact.id)
        .limit(6)
    ).all()
    runtimes = session.scalars(
        select(RuntimeInstance).order_by(RuntimeInstance.updated_at.desc(), RuntimeInstance.id).limit(6)
    ).all()
    return {
        "sampled_at": iso(now),
        "active_run_count": session.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))
        ),
        "enabled_agent_count": session.scalar(
            select(func.count()).select_from(Agent).where(Agent.enabled.is_(True))
        ),
        "active_runs": [
            {
                "id": row.id,
                "title": title,
                "status": row.status,
                "executor_type": row.executor_type,
                "execution_target": row.execution_target,
                "created_at": iso(row.created_at),
            }
            for row, title in active
        ],
        "upcoming": [{**agent_summary(row), "overdue": row.next_run_at <= now} for row in upcoming],
        "agents": [agent_summary(row) for row in agents],
        "conversations": [
            {"id": row.id, "title": row.title, "model": row.model, "updated_at": iso(row.updated_at)}
            for row in conversations
        ],
        "artifacts": [
            {
                "id": row.id,
                "type": row.artifact_type,
                "name": row.original_filename or row.artifact_type,
                "created_at": iso(row.created_at),
                "has_thumbnail": bool(row.thumbnail_relative_path),
            }
            for row in artifacts
        ],
        "runtimes": [
            {
                "id": row.id,
                "name": row.name,
                "ownership": row.ownership,
                "status": row.status,
                "source": row.metadata_json.get("source", "unknown"),
                "updated_at": iso(row.updated_at),
                "stale": row.updated_at < now - timedelta(minutes=5),
            }
            for row in runtimes
        ],
        "unread_notice_count": session.scalar(
            select(func.count()).select_from(Notice).where(Notice.read_at.is_(None))
        ),
        "notices": [
            notice_dict(row)
            for row in session.scalars(
                select(Notice).where(Notice.read_at.is_(None)).order_by(Notice.created_at.desc()).limit(8)
            )
        ],
        "interrupted_runs": interrupted_runs(session),
    }
