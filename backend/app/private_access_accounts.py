"""Fixed private-access coordination inside an owner transaction.

This grants no general machine SQL access. Only an authenticated administrator
or its exact standalone private-access Run can mutate the one policy record.
"""

import hashlib

from fastapi import HTTPException
from sqlalchemy import inspect

from app.data_access import DataAccessError, ScopedSession
from app.models import User

OPERATIONS = {"install", "start", "login", "enable", "disable"}


def check_run(session, run):
    if inspect(run).session is not session or not inspect(run).persistent:
        raise ValueError("Private access requires its owned standalone operation")
    validate_owned_operation(run, session.scope.user_id)


def validate_owned_operation(run, owner_id):
    """Validate the frozen native identity; this grants no execution authority."""
    task = run.task
    if (
        not owner_id
        or run.owner_id != owner_id
        or run.run_type != "system"
        or run.executor_type != "private_access"
        or run.capability != "system.private_access"
        or run.execution_target != "host"
        or run.effective_permissions != ["manage_private_access"]
        or run.agent_id
        or run.project_id
        or run.conversation_id
        or run.parent_run_id
        or task is None
        or task.owner_id != owner_id
        or task.intent != "operator.private_access"
        or task.agent_id
        or task.project_id
        or task.conversation_id
        or not isinstance(run.parameters, dict)
        or run.parameters.get("operation") not in OPERATIONS
    ):
        raise ValueError("Private access requires its owned standalone operation")


def authority(session, *, run=None, mutation=False):
    """Recheck live role/credentials; logout alone does not cancel durable work."""
    if not isinstance(session, ScopedSession):
        return None
    scope = session.scope
    if mutation and scope.read_only:
        raise DataAccessError("Administrative inspection is read-only")
    if run is not None:
        check_run(session, run)
    if scope.execution:
        if run is None:
            raise DataAccessError("Private access execution requires its owned operation")
        user = session.get(User, scope.user_id, populate_existing=True, with_for_update=True)
    else:
        if not scope.administrator or not scope.session_id:
            raise HTTPException(403, "Administrator access required")
        from app.accounts import Principal, _actor

        user = _actor(session, Principal(scope.user_id, scope.session_id, True), admin=True, lock=True)
    from app.account_credentials import password_record_valid

    if (
        user is None
        or not user.enabled
        or not user.is_admin
        or user.bootstrap_pending
        or not password_record_valid(user.password_record)
    ):
        raise HTTPException(403, "An enabled configured administrator is required")
    # Credentials themselves never enter Run metadata. Password/MFA changes
    # invalidate an approved action; role/disable changes also cancel owned work.
    stamp = "|".join([user.id, str(user.password_changed_at), str(user.totp_enabled_at)])
    return "account:" + hashlib.sha256(stamp.encode()).hexdigest()
