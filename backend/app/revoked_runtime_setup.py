"""Worker-only cancellation of a revoked account's existing runtime preparation.

No execution session, identity impersonation or machine-policy grant is issued.
Only the exact immutable owned native action can be canceled; uncertain cleanup
retains its lease/reservations and never dispatches another action.
"""

from app.data_access import DataAccessError, ScopedSession
from app.events import append_event
from app.models import Run, User
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import touch_lease, transition
from app.runtime_setup_job import cancel_payload, confirmed_gone, validate_operation
from app.state import RunStatus


def cleanup_revoked_runtime_setup(session, run, worker_id):
    if isinstance(session, ScopedSession):
        raise DataAccessError("Revoked operation cleanup requires trusted worker coordination")
    if run.executor_type != "runtime_setup" or run.owner_id is None:
        return False
    user = session.get(User, run.owner_id, populate_existing=True)
    if user is not None and user.enabled and user.is_admin and not user.bootstrap_pending:
        return False
    if not run.metadata_json.get("dispatch_attempted"):
        return False
    identity, owner_id = run.id, run.owner_id
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner_id
        or run.worker_id != worker_id
        or run.status
        not in {RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}
    ):
        session.commit()
        return True
    try:
        validate_operation(run)
    except ValueError:
        run.metadata_json = {
            **run.metadata_json,
            "cleanup_requires_inspection": True,
            "cancel_on_resume": True,
        }
        run.error_type = "RevokedOperationNeedsInspection"
        run.error_message = "The owned runtime preparation identity requires inspection"
        transition(session, run, RunStatus.INTERRUPTED, event_type="run.interrupted")
        session.commit()
        return True
    if run.status != RunStatus.CANCEL_REQUESTED:
        transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
    run.metadata_json = {**run.metadata_json, "cancel_on_resume": True, "cleanup_requires_inspection": True}
    touch_lease(session, run)
    payload = cancel_payload(run)
    confirmed = run.metadata_json.get("process_confirmed_gone") is True
    session.commit()  # Native I/O must not hold the database transaction.
    if not confirmed:
        try:
            result = RunnerClient(timeout=10).cancel_runtime_preparation(identity, payload)
            confirmed = confirmed_gone(result, run)
        except (RunnerError, RunnerUnavailable, ValueError):
            confirmed = False  # Never persist a native daemon/configuration details or raw error.
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner_id
        or run.worker_id != worker_id
        or run.status != RunStatus.CANCEL_REQUESTED
    ):
        session.commit()
        return True
    if confirmed:
        run.metadata_json = {
            **run.metadata_json,
            "process_confirmed_gone": True,
            "cleanup_requires_inspection": False,
        }
        transition(
            session, run, RunStatus.CANCELED, event_type="run.canceled", payload={"authority_revoked": True}
        )
        release_run_locks(session, identity)
    else:
        touch_lease(session, run)
        append_event(session, identity, "recovery.cleanup_pending", {"authority_revoked": True})
    session.commit()
    return True
