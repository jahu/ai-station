"""Saved agent notification policies emit inspectable in-app notices, never email."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_schema import NotificationPolicy, RetryPolicy
from app.db import session_scope, utcnow
from app.events import append_event
from app.models import Agent, Notice, Run, Task
from app.serialize import iso

router = APIRouter(prefix="/api/notices", tags=["notices"])
DB = Annotated[Session, Depends(session_scope)]

KIND_POLICY = {
    "succeeded": "on_success",
    "failed": "on_failure",
    "interrupted": "on_failure",
    "waiting_for_approval": "on_approval",
}


def retry_policy(raw) -> RetryPolicy:
    return RetryPolicy.model_validate(raw or {})


def notification_policy(raw) -> NotificationPolicy:
    return NotificationPolicy.model_validate(raw or {})


def notice_dict(row: Notice, session: Session | None = None) -> dict:
    payload = {
        "id": row.id,
        "agent_id": row.agent_id,
        "run_id": row.run_id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "created_at": iso(row.created_at),
        "read_at": iso(row.read_at),
        "retry": {"allowed": False, "run_id": None},
        "project_id": None,
    }
    if session is None:
        return payload
    agent = session.get(Agent, row.agent_id)
    payload["project_id"] = agent.project_id if agent else None
    run = session.get(Run, row.run_id)
    if run is None:
        return payload
    from app.schedule import retry_view, workflow_source

    source = workflow_source(session, run)
    retry = retry_view(session, source)
    payload["retry"] = {
        "allowed": retry["allowed"],
        "run_id": source.id if source.executor_type == "agent_workflow" else None,
    }
    return payload


def emit_agent_notice(session: Session, run: Run, status: str) -> Notice | None:
    task = session.get(Task, run.task_id) if run.agent_id else None
    coding = task.metadata_json.get("agent_coding_definition") if task else None
    data_agent = coding and "python_data" in coding.get("tools", [])
    if data_agent and (
        status == "succeeded"
        and (run.executor_type != "agent_data_result" or run.metadata_json.get("repair_run_id"))
        or run.executor_type == "python"
        and run.error_type == "PythonProgramFailed"
    ):
        return None
    if coding and run.executor_type != "agent_workflow":
        if status not in {"failed", "interrupted", "succeeded"}:
            return None
        if status == "succeeded" and (
            run.executor_type not in {"local_proposal", "project_validation", "agent_data_result"}
            or run.executor_type == "local_proposal"
            and run.parameters.get("commands")
        ):
            return None
    if run.executor_type == "agent_tool":
        return None
    if run.executor_type == "agent_workflow" and status == "succeeded":
        return None
    if (not coding and run.executor_type not in {"agent", "agent_workflow"}) or not run.agent_id:
        return None
    field = KIND_POLICY.get(status)
    if field is None:
        return None
    policy = notification_policy(
        (coding or run.parameters.get("definition") or {}).get("notification_policy")
    )
    if not getattr(policy, field):
        return None
    existing = session.scalar(
        select(Notice.id).where(Notice.run_id == run.id, Notice.kind == status).limit(1)
    )
    if existing:
        return None
    titles = {
        "succeeded": "Agent report succeeded",
        "failed": "Agent workflow failed",
        "interrupted": "Agent workflow interrupted",
        "waiting_for_approval": "Agent workflow needs approval",
    }
    if coding:
        titles["succeeded"] = "Coding agent result ready for review"
        titles["failed"] = "Coding agent workflow failed"
        titles["interrupted"] = "Coding agent workflow interrupted"
    if data_agent:
        titles["succeeded"] = "Data agent results ready"
        titles["failed"] = "Data agent workflow failed"
        titles["interrupted"] = "Data agent needs inspection"
    notice = Notice(
        agent_id=run.agent_id,
        run_id=run.id,
        kind=status,
        title=titles[status],
        body=run.summary or run.error_message or titles[status],
    )
    session.add(notice)
    session.flush()
    append_event(session, run.id, "notice.created", {"notice_id": notice.id, "kind": status})
    return notice


@router.get("")
def list_notices(
    session: DB,
    unread: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    statement = select(Notice).order_by(Notice.created_at.desc(), Notice.id)
    if unread:
        statement = statement.where(Notice.read_at.is_(None))
    return [notice_dict(row, session) for row in session.scalars(statement.limit(limit).offset(offset))]


class ReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: StrictBool = True


@router.post("/{notice_id}/read")
def mark_read(notice_id: UUID, body: ReadBody, session: DB):
    row = session.get(Notice, str(notice_id))
    if row is None:
        raise HTTPException(404, "Notice not found")
    row.read_at = utcnow() if body.read else None
    session.commit()
    return notice_dict(row, session)
