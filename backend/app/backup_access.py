"""Fixed administrator checks for full-station SQLite copies, never agent tools."""

from sqlalchemy import inspect, select

from app.models import Artifact, Run, User


def artifact_access(user_id):
    """A demoted owner must not keep access to other users through an old backup."""
    users = User.__table__.alias("backup_reader")
    runs = Run.__table__.alias("backup_source")
    administrator = (
        select(users.c.id)
        .where(
            users.c.id == user_id,
            users.c.enabled.is_(True),
            users.c.is_admin.is_(True),
            users.c.bootstrap_pending.is_(False),
        )
        .exists()
    )
    backup = Artifact.relative_path.startswith("backups/", autoescape=True) | Artifact.run_id.in_(
        select(runs.c.id).where(runs.c.executor_type == "sqlite_backup")
    )
    return ~backup | administrator


def require_administrator(session, run=None):
    from app.data_access import DataAccessError, ScopedSession

    if not isinstance(session, ScopedSession):
        return
    scope = session.scope
    if run is None:
        from app.accounts import Principal, _actor

        if not scope.administrator or not scope.session_id:
            raise DataAccessError("Station backups require an administrator")
        _actor(session, Principal(scope.user_id, scope.session_id, True), admin=True)
        return
    task = run.task
    if (
        not scope.execution
        or scope.read_only
        or inspect(run).session is not session
        or not inspect(run).persistent
        or run.owner_id != scope.user_id
        or run.executor_type != "sqlite_backup"
        or run.run_type != "maintenance"
        or run.capability != "station.backup"
        or run.execution_target != "container"
        or run.effective_permissions != ["manage_station"]
        or run.parameters
        or any((run.agent_id, run.project_id, run.conversation_id, run.parent_run_id))
        or task is None
        or task.owner_id != scope.user_id
        or any((task.agent_id, task.project_id, task.conversation_id))
    ):
        raise DataAccessError("Station backups require their standalone owned Run")
    user = session.get(User, scope.user_id, populate_existing=True)
    if user is None or not user.enabled or not user.is_admin or user.bootstrap_pending:
        raise DataAccessError("Station backups require an enabled administrator")
