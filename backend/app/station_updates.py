"""Administrator-owned, metadata-only checks of the fixed desktop release channel."""

import asyncio
import time
from typing import Annotated

from ai_station_runner.station_release_metadata import update_request
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect, select

from app import __version__
from app.data_access import DataAccessError, ScopedSession
from app.db import session_scope, utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.host_media_executor import HostMediaExecutor
from app.models import Run, User
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict, transition
from app.state import ACTIVE, RunStatus

NAME = "station_update_check"
CAPABILITY = "station.updates.check"
PERMISSIONS = ["manage_station", "network_read"]
router = APIRouter(prefix="/api/maintenance/updates", tags=["updates"])
DB = Annotated[object, Depends(session_scope, scope="function")]


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_administrator(session, run=None):
    install = run is not None and run.executor_type == "station_update"
    if install:
        update_request(run.parameters)
    if run is not None and (
        inspect(run).session is not session
        or not inspect(run).persistent
        or run.executor_type not in {NAME, "station_update"}
        or run.run_type != "maintenance"
        or run.capability != ("station.updates.install" if install else CAPABILITY)
        or run.execution_target != ("host" if install else "container")
        or not install
        and run.parameters
        or run.effective_permissions != PERMISSIONS
        or any((run.agent_id, run.project_id, run.conversation_id, run.parent_run_id))
        or run.task is None
        or any((run.task.agent_id, run.task.project_id, run.task.conversation_id))
    ):
        raise DataAccessError("Update checks require their standalone administrator Run")
    if not isinstance(session, ScopedSession):
        return  # Existing trusted local operator profile.
    scope = session.scope
    if run is None:
        from app.accounts import Principal, _actor

        if not scope.administrator or not scope.session_id or scope.read_only:
            raise DataAccessError("Update checks require an administrator")
        _actor(session, Principal(scope.user_id, scope.session_id, True), admin=True)
    else:
        if (
            not scope.execution
            or scope.read_only
            or run.owner_id != scope.user_id
            or run.task.owner_id != scope.user_id
        ):
            raise DataAccessError("Update checks require their standalone owned Run")
        user = session.get(User, scope.user_id, populate_existing=True)
        if user is None or not user.enabled or not user.is_admin or user.bootstrap_pending:
            raise DataAccessError("Update checks require an enabled administrator")


def latest_check(session):
    return session.scalar(
        select(Run).where(Run.executor_type == NAME).order_by(Run.created_at.desc(), Run.id).limit(1)
    )


@router.get("")
def status(session: DB):
    require_administrator(session)
    latest = latest_check(session)
    successful = session.scalar(
        select(Run)
        .where(Run.executor_type == NAME, Run.status == "succeeded")
        .order_by(Run.finished_at.desc(), Run.id)
        .limit(1)
    )
    updating = session.scalar(
        select(Run)
        .where(Run.executor_type == "station_update")
        .order_by(Run.created_at.desc(), Run.id)
        .limit(1)
    )
    # Read-only native status; no package transfer or install in this handler.
    session.commit()
    try:
        installation = RunnerClient(timeout=2).station_update_capabilities()
    except (RunnerError, RunnerUnavailable):
        installation = {"installed": False, "apply_available": False}
    apply_available = (
        installation.get("installed") is True
        and installation.get("apply_available") is True
        and installation.get("version") == __version__
    )
    return {
        "current_version": __version__,
        "channel": "stable",
        "publisher": "jahu/ai-station",
        "latest_check": run_dict(latest) if latest else None,
        "release_check_run_id": successful.id if successful else None,
        "update_run": run_dict(updating) if updating else None,
        "release": successful.metadata_json.get("release") if successful else None,
        "checked_at": successful.finished_at.isoformat() if successful else None,
        # Native apply is admitted separately; checking never grants install authority.
        "apply_available": apply_available,
        "installation": installation,
    }


@router.post("/checks", status_code=202)
def enqueue_check(_body: EmptyBody, session: DB):
    require_administrator(session)
    latest = latest_check(session)
    if latest is not None and (
        latest.status in ACTIVE or (utcnow() - latest.created_at).total_seconds() < 60
    ):
        return run_dict(latest)
    task = create_task(
        session,
        title="Check AI Station updates",
        prompt="Read the official stable desktop release metadata",
        capability=CAPABILITY,
    )
    run = create_run(
        session,
        task,
        run_type="maintenance",
        capability=CAPABILITY,
        executor_type=NAME,
        execution_target="container",
        permissions=PERMISSIONS,
        retry_class="safe",
    )
    session.commit()
    return run_dict(run)


class CheckCanceled(Exception):
    pass


class ClaimLost(Exception):
    pass


class StationUpdateCheckExecutor(HostMediaExecutor):
    name = NAME
    requires_gpu = False

    def execute(self, session, run):
        from app.station_release_source import release_metadata

        require_administrator(session, run)
        claim = (run.worker_id, run.claimed_at)
        if self._cancel_before_dispatch(session, run):
            session.commit()
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="run.started")
        session.commit()  # No transaction spans DNS, HTTP or transfer waits.
        last = 0.0

        def check(force=False):
            nonlocal last
            if not force and time.monotonic() - last < 0.5:
                return
            canceled = False

            def observe():
                nonlocal canceled
                require_administrator(session, run)
                cancel_expired_run(session, run.id)
                canceled = run.status == "cancel_requested"

            if not self._database_step(session, run, claim, observe):
                raise ClaimLost
            if canceled:
                raise CheckCanceled
            last = time.monotonic()

        try:
            check(True)
            snapshot = asyncio.run(release_metadata(check))
            check(True)
        except ClaimLost:
            return "done"
        except CheckCanceled:
            self._database_step(
                session,
                run,
                claim,
                lambda: transition(session, run, RunStatus.CANCELED, event_type="run.canceled"),
            )
            return "done"

        def publish():
            require_administrator(session, run)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return
            run.metadata_json = {**run.metadata_json, "release": snapshot}
            append_event(session, run.id, "station.update.checked", {"version": snapshot["version"]})
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")

        self._database_step(session, run, claim, publish)
        return "done"
