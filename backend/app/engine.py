"""One worker tick. HTTP handlers do not call this."""

from __future__ import annotations

import socket

from sqlalchemy import select
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


def cleanup_owned_cancellation(session, run, worker_id):
    from app.model_cancellation import cleanup_revoked_load, cleanup_revoked_stop
    from app.revoked_private_access import cleanup_revoked_private_access
    from app.revoked_runtime_setup import cleanup_revoked_runtime_setup

    return (
        cleanup_revoked_load(session, run, worker_id)
        or cleanup_revoked_stop(session, run, worker_id)
        or cleanup_revoked_private_access(session, run, worker_id)
        or cleanup_revoked_runtime_setup(session, run, worker_id)
    )


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
    from app.account_profile import accounts_enabled, waiting_for_first_admin

    if waiting_for_first_admin(session):
        session.commit()
        return None
    recover_stale(session, runner)
    session.commit()
    run = claim_next(session, worker_id)
    if run is None:
        session.commit()
        return None
    session.commit()
    if run.owner_id is not None:
        if cleanup_owned_cancellation(session, run, worker_id):
            return run.id
        # The role projection may open a coordination transaction. Release it
        # before the separate owner factory rechecks its own account/Run rows.
        session.commit()
        from app.data_access import DataAccessError, data_session_for_run
        from app.data_context import bind_data_scope

        try:
            with data_session_for_run(run.id, run.owner_id) as owned:
                with bind_data_scope(owned.scope):
                    _execute_claimed(owned, owned.get(type(run), run.id), worker_id, executors)
        except DataAccessError as exc:
            session.rollback()
            # Account authority may change between the first projection and
            # opening/checking the owner session. Never fail past owned cleanup.
            if cleanup_owned_cancellation(session, run, worker_id):
                return run.id
            session.commit()
            if run.metadata_json.get("dispatch_attempted") and not run.metadata_json.get(
                "process_confirmed_gone"
            ):
                from app.runs import transition
                from app.state import RunStatus

                run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
                transition(
                    session,
                    run,
                    RunStatus.INTERRUPTED,
                    event_type="recovery.inspection_required",
                    payload={"reason": "Account authority changed before cleanup was confirmed"},
                )
            else:
                mark_failed(session, run, "AccountUnavailable", str(exc))
                release_run_locks(session, run.id)
            session.commit()
        finally:
            session.expire_all()
        return run.id
    if accounts_enabled():
        from app.models import ResourceLock

        reserved = session.scalar(
            select(ResourceLock.resource_key)
            .where(ResourceLock.run_id == run.id, ResourceLock.released_at.is_(None))
            .limit(1)
        )
        if (
            reserved
            or run.metadata_json.get("dispatch_attempted")
            or run.started_at
            or run.pid
            or run.process_group_id
        ):
            from app.runs import transition
            from app.state import RunStatus

            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="recovery.inspection_required",
                payload={"reason": "The Run has no verified execution owner"},
            )
        else:
            mark_failed(session, run, "OwnerUnavailable", "The Run has no verified execution owner")
            release_run_locks(session, run.id)
        session.commit()
        return run.id
    # Explicit legacy operator profile; account-mode workers never enter it.
    return _execute_claimed(session, run, worker_id, executors)


def _execute_claimed(session, run, worker_id, executors):
    claim = run.claimed_at
    if run.owner_id is not None:
        from app.models import User

        user = session.get(User, run.owner_id)
        host_account_executors = {
            "model_download",
            "model_bundle_download",
            "runtime_setup",
            "speech_setup",
            "image_setup",
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
            if run.metadata_json.get("dispatch_attempted") and not run.metadata_json.get(
                "process_confirmed_gone"
            ):
                from app.data_access import DataAccessError

                raise DataAccessError("The execution account authority changed before cleanup")
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
        # An executor may commit before losing its claim. A rollback without
        # an active transaction does not expire that stale ORM instance.
        failed = session.get(type(run), run.id, populate_existing=True)
        if (
            failed is not None
            and failed.worker_id == worker_id
            and failed.claimed_at == claim
            and failed.status not in {"succeeded", "failed", "canceled", "interrupted"}
        ):
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
