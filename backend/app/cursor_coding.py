"""Explicit external Cursor tasks, fresh worktrees and ordinary follow-up Runs."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.coding_tasks import CodingTask, enqueue_coding_task
from app.db import session_scope
from app.runs import run_dict

router = APIRouter(prefix="/api/coding", tags=["coding"])


class CursorTask(CodingTask):
    external_ai: Literal[True]


@router.post("/cursor", status_code=202)
def create_cursor_task(body: CursorTask, session: Annotated[Session, Depends(session_scope)]):
    run = enqueue_cursor_task(session, body)
    session.commit()
    return run_dict(run)


def enqueue_cursor_task(session, body: CursorTask, *, task=None, parent_run_id=None):
    return enqueue_coding_task(session, body, task=task, parent_run_id=parent_run_id)
