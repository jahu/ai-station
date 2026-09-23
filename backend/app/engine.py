"""One worker tick. HTTP handlers do not call this."""

from __future__ import annotations

import socket

from sqlalchemy.orm import Session

from app.db import utcnow
from app.executor import Executor
from app.executors import EXECUTORS
from app.heartbeat import keep_lease
from app.models import WorkerRow
from app.recovery import recover_stale
from app.resources import release_run_locks
from app.runner_client import RunnerClient
from app.runs import claim_next, mark_failed


def ensure_worker(session: Session, worker_id: str) -> None:
    row = session.get(WorkerRow, worker_id)
    now = utcnow()
    if row is None:
        session.add(
            WorkerRow(id=worker_id, hostname=socket.gethostname(), started_at=now, last_heartbeat=now)
        )
    else:
        row.last_heartbeat = now
    session.flush()


def tick(
    session: Session, worker_id: str, *, executors=None, runner: RunnerClient | None = None
) -> str | None:
    executors: dict[str, Executor] = EXECUTORS if executors is None else executors
    ensure_worker(session, worker_id)
    recover_stale(session, runner)
    session.commit()
    run = claim_next(session, worker_id)
    if run is None:
        session.commit()
        return None
    session.commit()
    executor = executors.get(run.executor_type)
    if executor is None:
        mark_failed(session, run, "ExecutorMissing", f"No executor named {run.executor_type}")
        release_run_locks(session, run.id)
        session.commit()
        return run.id
    try:
        with keep_lease(run.id, worker_id):
            executor.execute(session, run)
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = session.get(type(run), run.id)
        if failed is not None and failed.status not in {"succeeded", "failed", "canceled", "interrupted"}:
            mark_failed(session, failed, type(exc).__name__, str(exc))
            release_run_locks(session, failed.id)
            session.commit()
    return run.id
