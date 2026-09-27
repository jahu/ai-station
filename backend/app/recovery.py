"""Stale-lease recovery. Never blindly re-executes external side effects."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.events import append_event
from app.models import Run
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import transition
from app.state import RunStatus

INSPECT_STATUSES = {
    RunStatus.CLAIMED.value,
    RunStatus.PREPARING.value,
    RunStatus.RUNNING.value,
    RunStatus.CANCEL_REQUESTED.value,
}


def recover_stale(session: Session, runner: RunnerClient | None = None) -> list[str]:
    runner = runner or RunnerClient()
    now = utcnow()
    stale = list(
        session.scalars(
            select(Run).where(
                Run.status.in_(INSPECT_STATUSES),
                Run.lease_expires_at.is_not(None),
                Run.lease_expires_at < now,
            )
        )
    )
    touched: list[str] = []
    for run in stale:
        session.commit()
        if run.executor_type in {"llama_load", "llama_stop"}:
            # The native create/start/stop journal is keyed by immutable runtime
            # identity. Resuming it cannot create another container or restart an
            # exited model. Keep all reservations until confirmed stop/readiness.
            session.refresh(run)
            if (
                run.status not in INSPECT_STATUSES
                or run.lease_expires_at is None
                or run.lease_expires_at >= now
            ):
                continue
            canceled = run.status == RunStatus.CANCEL_REQUESTED.value
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Resume owned llama.cpp lifecycle inspection"},
            )
            run.metadata_json = {**run.metadata_json, "cancel_on_resume": canceled}
            run.finished_at = None
            run.worker_id = None
            run.lease_expires_at = None
            transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"recovery": True})
            touched.append(run.id)
            continue
        info = _inspect(runner, run.id)
        session.refresh(run)
        if run.status not in INSPECT_STATUSES or run.lease_expires_at is None or run.lease_expires_at >= now:
            continue  # A live worker renewed its lease while inspection ran.
        if info.get("reachable") is False and run.execution_target == "host":
            # A dispatch can succeed before its response/pid is persisted. Keep
            # reservations and retry inspection; never repeat an uncertain send.
            from app.runs import touch_lease

            touch_lease(session, run)
            append_event(session, run.id, "recovery.runner_unavailable", {})
            touched.append(run.id)
            continue
        if info.get("alive") or info.get("completion_pending"):
            from app.runs import touch_lease

            touch_lease(session, run)
            append_event(
                session,
                run.id,
                "recovery.completion_pending" if info.get("completion_pending") else "recovery.process_alive",
                {"pid": info.get("pid"), "completion_pending": info.get("completion_pending", False)},
            )
            if run.status == RunStatus.CANCEL_REQUESTED:
                session.commit()
                try:
                    runner.cancel_process(run.id)
                except (RunnerError, RunnerUnavailable):
                    pass  # Remains pending until inspection confirms termination.
            touched.append(run.id)
            continue
        if run.status == RunStatus.CANCEL_REQUESTED.value:
            transition(
                session, run, RunStatus.CANCELED, event_type="run.canceled", payload={"recovery": True}
            )
            release_run_locks(session, run.id)
            touched.append(run.id)
            continue
        if run.status == RunStatus.CLAIMED.value and not run.pid and run.retry_class == "safe":
            _interrupt(session, run, "Worker disappeared before execution")
            run.finished_at = None
            run.worker_id = None
            run.lease_expires_at = None
            run.error_message = ""
            run.error_type = ""
            transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={"recovery": True})
            touched.append(run.id)
            continue
        _interrupt(session, run, "Lease expired and the owned process is not running")
        touched.append(run.id)
    return touched


def _inspect(runner: RunnerClient, run_id: str) -> dict:
    try:
        info = runner.inspect_process(run_id)
        info["reachable"] = True
        return info
    except RunnerError as exc:
        if exc.status_code == 404:
            return {"alive": False, "known": False, "reachable": True}
        return {"alive": False, "reachable": False}
    except RunnerUnavailable:
        return {"alive": False, "reachable": False}


def _interrupt(session: Session, run: Run, reason: str) -> None:
    if run.status == RunStatus.INTERRUPTED.value:
        return
    run.error_type = "Interrupted"
    run.error_message = reason
    transition(session, run, RunStatus.INTERRUPTED, event_type="run.interrupted", payload={"reason": reason})
    release_run_locks(session, run.id)
