"""Renew leases independently of slow providers or host requests."""

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import control_session_factory, utcnow
from app.models import Run, WorkerRow
from app.state import TERMINAL


def cancel_expired_run(session, run_id):
    run = session.get(Run, run_id)
    if run is None or run.status in TERMINAL:
        return
    raw = run.parameters.get("execution_deadline_at") or run.parameters.get("agent_coding_deadline")
    if raw and datetime.fromisoformat(raw) <= utcnow():
        from app.events import append_event
        from app.runs import request_cancel

        if run.status != "cancel_requested":
            append_event(session, run.id, "agent.runtime_limit", {})
            request_cancel(session, run)


def cancel_expired_waiting(session):
    """Budgets include dependency/resource waits, which have no worker heartbeat."""
    deadline = func.coalesce(
        func.nullif(Run.parameters["execution_deadline_at"].as_string(), ""),
        Run.parameters["agent_coding_deadline"].as_string(),
    )
    ids = list(
        session.scalars(
            select(Run.id)
            .where(
                Run.status.in_({"queued", "waiting_for_tool"}),
                deadline <= utcnow().isoformat(),
            )
            .order_by(Run.created_at)
            .limit(100)
        )
    )
    from app.task_control import lock_task

    for run_id in ids:
        run = session.get(Run, run_id)
        if run is None:
            continue
        lock_task(session, run.task)
        session.refresh(run)
        if run.status in {"queued", "waiting_for_tool"}:
            cancel_expired_run(session, run_id)


# Existing coding/check integrations use this name; both contracts now share
# the same cancellation path without changing their stored deadline fields.
cancel_expired_coding = cancel_expired_run


@contextmanager
def keep_lease(run_id: str, worker_id: str):
    stop = threading.Event()
    settings = get_settings()
    factory = control_session_factory()

    def renew():
        while not stop.wait(settings.heartbeat_seconds):
            try:
                with factory() as session:
                    now = utcnow()
                    session.execute(
                        update(WorkerRow).where(WorkerRow.id == worker_id).values(last_heartbeat=now)
                    )
                    session.execute(
                        update(Run)
                        .where(Run.id == run_id, Run.worker_id == worker_id, Run.status.not_in(TERMINAL))
                        .values(lease_expires_at=now + timedelta(seconds=settings.lease_seconds))
                    )
                    cancel_expired_run(session, run_id)
                    session.commit()
            except Exception:
                logging.exception("Could not renew worker lease")

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=6)
