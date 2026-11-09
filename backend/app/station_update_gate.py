"""Fixed machine coordination for an administrator's desktop-update idle point."""

from ai_station_runner.station_release_metadata import update_request
from sqlalchemy import exists, select, update

from app.db import control_session_factory, utcnow
from app.models import Run, Setting, User

KEY = "station_update_dispatch_gate"
EXECUTOR = "station_update"
BUSY = {"claimed", "preparing", "running", "cancel_requested", "waiting_for_tool"}


def dispatch_allowed():
    # This predicate participates in the atomic claim UPDATE as well as selection.
    # A worker that selected just before maintenance cannot slip through later.
    table = Setting.__table__
    return ~exists(select(table.c.key).where(table.c.key == KEY))


def take(run_id, claim):
    """Return None while work is active. Never stop or cancel another workload."""
    with control_session_factory()() as session:
        # Acquire SQLite's writer before observing both the gate and other claims.
        # PostgreSQL later obtains a row lock through this same fixed update.
        matched = session.execute(
            update(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == claim[0],
                Run.claimed_at == claim[1],
                Run.status == "running",
                Run.executor_type == EXECUTOR,
            )
            .values(lease_expires_at=Run.lease_expires_at)
        )
        if matched.rowcount != 1:
            raise ValueError("The desktop update no longer owns its execution claim")
        run = session.get(Run, run_id)
        update_request(run.parameters)
        actor = session.get(User, run.owner_id) if run.owner_id else None
        if (
            actor is None
            or not actor.enabled
            or not actor.is_admin
            or actor.bootstrap_pending
            or run.lease_expires_at is None
            or run.lease_expires_at <= utcnow()
            or run.run_type != "maintenance"
            or run.capability != "station.updates.install"
            or run.execution_target != "host"
            or run.effective_permissions != ["manage_station", "network_read"]
            or any((run.agent_id, run.project_id, run.conversation_id, run.parent_run_id))
            or run.task is None
            or run.task.owner_id != run.owner_id
            or any((run.task.agent_id, run.task.project_id, run.task.conversation_id))
        ):
            raise ValueError("Desktop updates require their standalone administrator execution")
        expected = {
            "schema": 1,
            "run_id": run_id,
            "owner_id": run.owner_id,
            "worker_id": claim[0],
            "claimed_at": claim[1].isoformat(),
        }
        gate = session.get(Setting, KEY)
        if gate is not None:
            if gate.value != expected:
                raise ValueError("Another desktop update needs inspection before continuing")
            session.commit()
            return expected
        if session.scalar(select(Run.id).where(Run.id != run_id, Run.status.in_(BUSY)).limit(1)):
            session.rollback()
            return None
        session.add(Setting(key=KEY, value=expected))
        session.commit()
        return expected


def release(run_id, expected):
    """Only the matching update may release its own coordination gate."""
    if not isinstance(expected, dict) or expected.get("run_id") != run_id:
        raise ValueError("The desktop update gate identity does not match")
    with control_session_factory()() as session:
        gate = session.get(Setting, KEY)
        if gate is None:
            return
        if gate.value != expected:
            raise ValueError("The desktop update gate changed; inspect it before continuing")
        session.delete(gate)
        session.commit()
