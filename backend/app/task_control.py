"""Task-wide Stop serialized with child publication in the existing database."""

from fastapi import HTTPException
from sqlalchemy import select, update

from app.db import utcnow
from app.events import append_event
from app.models import Run, Task
from app.state import TERMINAL


def lock_task(session, task):
    session.execute(update(Task).where(Task.id == task.id).values(updated_at=Task.updated_at))
    session.refresh(task, ["metadata_json"])


def cancel_task(session, task):
    from app.runs import request_cancel

    lock_task(session, task)
    active = list(
        session.scalars(select(Run).where(Run.task_id == task.id, Run.status.not_in(TERMINAL)).limit(1025))
    )
    if len(active) > 1024:
        raise HTTPException(409, "Task graph exceeds the cancellation bound; inspect its Runs")
    task.metadata_json = {**task.metadata_json, "stop_requested_at": utcnow().isoformat()}
    canceled = []
    for run in active:
        if run.status != "cancel_requested":
            request_cancel(session, run)
        append_event(session, run.id, "task.stop_requested", {"task_id": task.id})
        canceled.append(run.id)
    session.flush()
    return {"task_id": task.id, "stop_requested": True, "run_ids": canceled}


def stopped_task(session, task):
    lock_task(session, task)
    return bool(task.metadata_json.get("stop_requested_at"))
