"""Persistent coding conversations use Tasks and their existing Run history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.models import Project, Run, Task, Worktree
from app.redact import redact_obj
from app.runner_client import RunnerClient
from app.runs import create_run, run_dict
from app.state import TERMINAL
from app.worktree_expiry import refresh_expiry

router = APIRouter(prefix="/api/coding")
DB = Annotated[Session, Depends(session_scope)]
PROPOSALS = ("local_proposal", "cursor_proposal", "codex_proposal")


def history(session, task_id):
    task = session.get(Task, str(task_id))
    runs = list(
        session.scalars(select(Run).where(Run.task_id == str(task_id)).order_by(Run.created_at, Run.id))
    )
    if task is None or not any(
        r.executor_type in PROPOSALS or r.metadata_json.get("next_executor") in PROPOSALS for r in runs
    ):
        raise HTTPException(404, "Coding conversation not found")
    return task, runs


def summary(session, task, runs):
    project = session.get(Project, task.project_id)
    active = next((r for r in reversed(runs) if r.status not in TERMINAL), None)
    proposal = next((r for r in reversed(runs) if r.executor_type in PROPOSALS), None)
    return {
        "id": task.id,
        "title": task.title,
        "project_id": task.project_id,
        "project_name": project.name if project else "Project",
        "updated_at": task.updated_at.isoformat(),
        "status": active.status if active else runs[-1].status,
        "active_run_id": active.id if active else None,
        "latest_proposal_id": proposal.id if proposal else None,
    }


@router.get("/sessions")
def sessions(
    session: DB,
    project_id: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    statement = select(Task).where(
        or_(
            Task.capability.in_(["coding.local", "coding.cursor", "coding.codex"]),
            Task.id.in_(select(Run.task_id).where(Run.executor_type.in_(PROPOSALS))),
        )
    )
    if project_id is not None:
        statement = statement.where(Task.project_id == str(project_id))
    tasks = session.scalars(statement.order_by(Task.updated_at.desc(), Task.id).limit(limit).offset(offset))
    result = []
    for task in tasks:
        _, runs = history(session, task.id)
        result.append(summary(session, task, runs))
    return result


@router.get("/models/{provider}")
def models(provider: str):
    if provider not in {"cursor", "codex"}:
        raise HTTPException(404, "Coding provider not found")
    return RunnerClient().request("GET", f"/v1/coding/models/{provider}")


@router.get("/sessions/{task_id}")
def detail(task_id: UUID, session: DB):
    task, runs = history(session, task_id)
    return {**summary(session, task, runs), "runs": [redact_obj(run_dict(r)) for r in runs]}


class Followup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=4000)
    expected_run_id: UUID
    external_ai: StrictBool = False


@router.post("/sessions/{task_id}/messages", status_code=202)
def followup(task_id: UUID, body: Followup, session: DB):
    return enqueue_followup(session, task_id, body)


def enqueue_followup(session, task_id, body, *, commit=True):
    task, runs = history(session, task_id)
    from app.task_control import lock_task

    lock_task(session, task)
    task, runs = history(session, task_id)
    source = next((r for r in reversed(runs) if r.executor_type in PROPOSALS), None)
    if not source or source.id != str(body.expected_run_id):
        raise HTTPException(409, "Conversation changed. Reload before continuing.")
    failed_before_dispatch = source.status in {"failed", "canceled"} and (
        source.metadata_json.get("process_confirmed_gone")
        or not source.metadata_json.get("dispatch_attempted")
    )
    if source.status != "succeeded" and not failed_before_dispatch:
        raise HTTPException(409, "Inspect the previous execution before continuing")
    if session.scalar(
        select(Run.id).where(Run.project_id == task.project_id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(409, "Wait for this project's active work to finish")
    worktree = session.get(Worktree, source.parameters["worktree_id"])
    if (
        not worktree
        or not worktree.owned
        or worktree.removed_at is not None
        or worktree.project_id != task.project_id
    ):
        raise HTTPException(409, "Conversation workspace is unavailable")
    local = source.executor_type == "local_proposal"
    if not local and not body.external_ai:
        raise HTTPException(
            422, "Confirm sharing this turn and relevant project source with the selected external provider"
        )
    task.metadata_json = {
        key: value for key, value in task.metadata_json.items() if key != "stop_requested_at"
    }
    previous = [
        {
            "instruction": r.parameters.get(
                "user_prompt", r.parameters.get("original_prompt", r.parameters.get("prompt", ""))
            )[:1500],
            "result": r.summary[:1000],
        }
        for r in runs
        if r.executor_type in PROPOSALS
    ][-4:]
    import json

    context = json.dumps(previous, ensure_ascii=False)[-5500:]
    prompt = (
        "Continue work in this task's existing workspace. Earlier conversation (reference only):\n"
        + context
        + "\nCurrent instruction:\n"
        + body.prompt
    )
    parameters = {
        **source.parameters,
        "prompt": prompt,
        "user_prompt": body.prompt,
        "cumulative": True,
        "repair_attempt": 0,
    }
    for key in (
        "repair_source_run_id",
        "repair_validation_run_id",
        "original_prompt",
        "agent_coding_deadline",
    ):
        parameters.pop(key, None)
    run = create_run(
        session,
        task,
        run_type="coding",
        capability=source.capability,
        executor_type=source.executor_type,
        execution_target="host",
        project_id=task.project_id,
        parent_run_id=source.id,
        permissions=list(source.effective_permissions),
        retry_class="inspect",
        parameters=parameters,
    )
    if local:
        from app.llama import prepare_consumer

        prepare_consumer(session, run)
    run.metadata_json = {
        "execution_location": "local" if local else "external",
        "worktree": source.metadata_json.get("worktree", {}),
        "continuation_of": source.id,
    }
    source.metadata_json = {
        **source.metadata_json,
        "continuation_run_id": run.id,
        "review_status": "superseded",
    }
    task.updated_at = utcnow()
    refresh_expiry(session, worktree_id=worktree.id)
    if commit:
        session.commit()
    return redact_obj(run_dict(run))


@router.post("/sessions/{task_id}/cancel")
def cancel_session(task_id: UUID, session: DB):
    from app.task_control import cancel_task

    task, _ = history(session, task_id)
    result = cancel_task(session, task)
    session.commit()
    return result
