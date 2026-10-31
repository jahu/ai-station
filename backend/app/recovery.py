"""Stale-lease recovery. Never blindly re-executes external side effects."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.models import Run
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import transition
from app.serialize import iso
from app.state import RunStatus

INSPECT_STATUSES = {
    RunStatus.CLAIMED.value,
    RunStatus.PREPARING.value,
    RunStatus.RUNNING.value,
    RunStatus.CANCEL_REQUESTED.value,
}


def lease_health(session: Session, *, limit: int = 20) -> dict:
    """Inspect held leases. Never recovers, requeues, or restores."""
    now = utcnow()
    held = select(func.count()).where(
        Run.status.in_(INSPECT_STATUSES),
        Run.lease_expires_at.is_not(None),
    )
    stale = held.where(Run.lease_expires_at < now)
    rows = session.scalars(
        select(Run)
        .where(Run.status.in_(INSPECT_STATUSES), Run.lease_expires_at.is_not(None))
        .order_by(Run.lease_expires_at.asc())
        .limit(limit)
    )
    return {
        "lease_seconds": get_settings().lease_seconds,
        "held_lease_count": int(session.scalar(held) or 0),
        "stale_lease_count": int(session.scalar(stale) or 0),
        "leases": [
            {
                "id": run.id,
                "status": run.status,
                "worker_id": run.worker_id,
                "executor_type": run.executor_type,
                "retry_class": run.retry_class,
                "lease_expires_at": iso(run.lease_expires_at),
                "stale": bool(run.lease_expires_at and run.lease_expires_at < now),
                "replay": False,
            }
            for run in rows
        ],
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
        session.refresh(run)
        if run.status not in INSPECT_STATUSES or run.lease_expires_at is None or run.lease_expires_at >= now:
            continue
        from app.heartbeat import cancel_expired_run

        cancel_expired_run(session, run.id)
        session.commit()
        if run.executor_type in {
            "llama_load",
            "llama_stop",
            "llama_wait",
            "private_access",
            "artifact_purge",
            "runtime_setup",
            "speech_setup",
            "image_setup",
            "music_setup",
            "video_setup",
            "avatar_setup",
        }:
            # A readiness waiter only reads shared infrastructure observations;
            # it can resume without inspecting or dispatching any host process.
            # Purges resume only their approved artifact snapshot and committed
            # per-item intent. Unlinked bytes and tombstones are idempotent.
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
                payload={"reason": "Resume owned lifecycle inspection"},
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
        if (
            run.parameters.get("managed_image_runtime")
            and run.metadata_json.get("dispatch_attempted")
            and info.get("known") is False
            and info.get("reachable") is True
        ):
            # 404 is not proof that a delayed start cannot still arrive. The
            # typed Stop persists a native tombstone before resources are freed.
            from app.managed_image_client import fence_missing_dispatch

            try:
                info = {**fence_missing_dispatch(runner, run), "reachable": True}
            except (RunnerError, RunnerUnavailable, ValueError):
                info = {"reachable": False}
            session.refresh(run)
        if info.get("reachable") is False and (
            run.execution_target == "host"
            or run.executor_type == "python"
            or run.parameters.get("managed_image_runtime")
        ):
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
        if (
            run.executor_type == "site_preview"
            and run.metadata_json.get("dispatch_attempted")
            and info.get("cleanup_confirmed") is not True
        ):
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            _interrupt(session, run, "Preview dispatch cleanup requires explicit confirmation")
            touched.append(run.id)
            continue
        if info.get("cleanup_confirmed") is False:
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            _interrupt(session, run, "Owned container cleanup could not be confirmed")
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
    if run.executor_type != "site_preview" or not run.metadata_json.get("cleanup_requires_inspection"):
        release_run_locks(session, run.id)
