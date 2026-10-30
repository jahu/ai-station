"""One worker tick. HTTP handlers do not call this."""

from __future__ import annotations

import socket

from sqlalchemy.orm import Session

from app.db import utcnow
from app.dependencies import failed_prerequisites
from app.events import append_event
from app.executor import Executor
from app.executors import EXECUTORS
from app.heartbeat import cancel_expired_run, keep_lease
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
    if run.owner_id is not None:
        from app.data_access import DataAccessError, data_session_for_run
        from app.data_context import bind_data_scope

        try:
            with data_session_for_run(run.id, run.owner_id) as owned:
                with bind_data_scope(owned.scope):
                    _execute_claimed(owned, owned.get(type(run), run.id), worker_id, executors)
        except DataAccessError as exc:
            session.rollback()
            mark_failed(session, run, "AccountUnavailable", str(exc))
            release_run_locks(session, run.id)
            session.commit()
        finally:
            session.expire_all()
        return run.id
    # Transitional legacy service path. The final account cutover must reject
    # ownerless Runs; no additional-account API is enabled in the live app yet.
    return _execute_claimed(session, run, worker_id, executors)


def _execute_claimed(session, run, worker_id, executors):
    if run.owner_id is not None:
        from app.models import User

        user = session.get(User, run.owner_id)
        host_account_executors = {
            "cursor_proposal",
            "codex_proposal",
            "github_publication",
            "publication_reconcile",
            "github_read",
            "sqlite_backup",
            "private_access",
            "runtime_observation",
            "station_snapshot",
        }
        if (
            user is None
            or not user.enabled
            or run.executor_type in host_account_executors
            and not user.is_admin
            or run.executor_type == "memory_embed"
            and run.capability == "memory.embed.prepare"
            and not user.is_admin
        ):
            mark_failed(
                session,
                run,
                "AccountPermissionDenied",
                "This operation requires an enabled authorized account",
            )
            session.commit()
            return run.id
    failures = failed_prerequisites(session, run)
    if failures:
        mark_failed(
            session, run, "PrerequisiteFailed", "Required Runs did not succeed: " + ", ".join(failures)
        )
        session.commit()
        return run.id
    cancel_expired_run(session, run.id)
    session.commit()
    session.refresh(run)
    executor = executors.get(run.executor_type)
    if executor is None:
        mark_failed(session, run, "ExecutorMissing", f"No executor named {run.executor_type}")
        release_run_locks(session, run.id)
        session.commit()
        return run.id
    try:
        with keep_lease(run.id, worker_id):
            # Release the write transaction before joining the heartbeat thread.
            # Otherwise a renewal waiting on SQLite blocks our own final commit.
            try:
                executor.execute(session, run)
                session.commit()
            except Exception:
                session.rollback()
                raise
    except Exception as exc:
        session.rollback()
        failed = session.get(type(run), run.id)
        if failed is not None and failed.status not in {"succeeded", "failed", "canceled", "interrupted"}:
            if failed.metadata_json.get("dispatch_attempted") and not failed.metadata_json.get(
                "process_confirmed_gone"
            ):
                append_event(session, failed.id, "recovery.inspection_required", {"error": str(exc)})
                failed.lease_expires_at = utcnow()
            else:
                mark_failed(session, failed, type(exc).__name__, str(exc))
                release_run_locks(session, failed.id)
            session.commit()
    return run.id
