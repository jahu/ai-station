"""One approved release, an independent native owner, and inspect-only recovery."""

import re
import time
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from ai_station_runner.station_release_metadata import update_package, update_request
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.data_access import ScopedSession
from app.db import session_scope, utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.host_media_executor import HostMediaExecutor
from app.models import Run, Setting, Task
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, mark_failed, run_dict, transition
from app.state import RunStatus
from app.station_update_gate import KEY, release, take
from app.station_updates import PERMISSIONS, require_administrator

router = APIRouter(prefix="/api/maintenance/updates")
DB = Annotated[object, Depends(session_scope, scope="function")]
PHASES = {
    "queued",
    "downloading",
    "preparing",
    "ready",
    "apply_requested",
    "applying",
    "applied",
    "succeeded",
    "failed",
    "canceled",
    "inspection_required",
}


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_run_id: UUID
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_request_id: UUID


@router.post("/install", status_code=202)
def enqueue(body: InstallRequest, session: DB):
    require_administrator(session)
    if not isinstance(session, ScopedSession):
        raise HTTPException(409, "Use the installed desktop app and its administrator account to update")
    observation = session.get(Run, str(body.check_run_id))
    snapshot = observation.metadata_json.get("release") if observation else None
    if (
        observation is None
        or observation.executor_type != "station_update_check"
        or observation.status != "succeeded"
        or not isinstance(snapshot, dict)
        or snapshot.get("fingerprint") != body.fingerprint
    ):
        raise HTTPException(422, "Choose your completed official update check")
    identity = str(
        uuid5(NAMESPACE_URL, f"ai-station/update/{session.scope.user_id}/{body.client_request_id}")
    )
    old = session.get(Task, identity)
    if old is not None:
        rows = [r for r in old.runs if r.executor_type == "station_update"]
        if len(rows) != 1 or rows[0].parameters.get("fingerprint") != body.fingerprint:
            raise HTTPException(409, "This update request was already used for different input")
        return run_dict(rows[0])
    # Release the database transaction before the read-only native capability query.
    session.commit()
    try:
        native = RunnerClient(timeout=5).station_update_capabilities()
    except (RunnerError, RunnerUnavailable) as exc:
        raise HTTPException(503, "The installed desktop updater is unavailable") from exc
    if native.get("apply_available") is not True or native.get("version") != __version__:
        raise HTTPException(409, "This installation does not yet support automatic updates")
    try:
        update_package(snapshot, __version__, native.get("platform"))
        parameters = update_request(
            {
                "release_id": snapshot["release_id"],
                "fingerprint": body.fingerprint,
                "current_version": __version__,
                "platform": native["platform"],
            }
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    require_administrator(session)
    task = Task(
        id=identity,
        title=f"Update AI Station to {snapshot['version']}",
        prompt="Install the approved official desktop release and preserve saved work",
        capability="station.updates.install",
        intent="station_update",
        metadata_json={},
    )
    session.add(task)
    try:
        session.flush()
        run = create_run(
            session,
            task,
            run_type="maintenance",
            capability="station.updates.install",
            executor_type="station_update",
            execution_target="host",
            operation_key="install",
            parameters=parameters,
            permissions=PERMISSIONS,
            retry_class="inspect",
            metadata={"release": snapshot, "target_version": snapshot["version"]},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        if session.get(Task, identity) is None:
            raise HTTPException(409, "The update request could not be saved; try again") from None
        return enqueue(body, session)
    return run_dict(run)


def checked_reply(run, value):
    if (
        not isinstance(value, dict)
        or value.get("run_id") != run.id
        or value.get("request") != run.parameters
        or not isinstance(value.get("phase"), str)
        or value["phase"] not in PHASES
    ):
        raise ValueError("The native update reply does not match this approved operation")
    if value["phase"] in {"ready", "apply_requested", "applying", "applied", "succeeded"}:
        target = value.get("target")
        if (
            not isinstance(target, dict)
            or set(target) != {"version", "bundle_id", "image_id", "source_epoch"}
            or target.get("version") != run.metadata_json.get("target_version")
            or not isinstance(target.get("bundle_id"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", target["bundle_id"])
            or not isinstance(target.get("image_id"), str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", target["image_id"])
            or type(target.get("source_epoch")) is not int
            or not 0 <= target["source_epoch"] < 2**63
        ):
            raise ValueError("The native update has no exact verified target package")
        expected = run.metadata_json.get("native_update", {}).get("target")
        if expected is not None and expected != target:
            raise ValueError("The native update target changed after preparation")
    if value["phase"] == "succeeded" and (
        not isinstance(value.get("target"), dict)
        or value["target"].get("version") != run.metadata_json.get("target_version")
        or value["target"].get("version") != __version__
    ):
        raise ValueError("The running app does not confirm the approved update version")
    return value


def message(run, action):
    return {
        "action": action,
        "run_id": run.id,
        "permissions": PERMISSIONS,
        **({"request": run.parameters} if action == "prepare" else {}),
    }


def finish(session, run, value):
    """The caller owns a trusted coordination or claim-fenced private transaction."""
    phase = value["phase"]
    run.metadata_json = {**run.metadata_json, "native_update": value}
    if phase == "succeeded" and run.status != "cancel_requested":
        transition(session, run, RunStatus.SUCCEEDED, event_type="station.update.completed")
    elif phase == "canceled" or phase == "failed" and run.status == "cancel_requested":
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
    elif phase == "failed":
        mark_failed(
            session,
            run,
            "DesktopUpdateFailed",
            value.get("error") or "The native update could not be prepared",
        )
    else:
        transition(session, run, RunStatus.INTERRUPTED, event_type="station.update.inspection_required")


def recover(session, run, runner, *, worker_id=None):
    """No executor/installer replay: adopt only the original native operation's proof."""
    if run.executor_type != "station_update":
        return False
    if not run.metadata_json.get("dispatch_attempted"):
        if run.status != "interrupted":
            transition(session, run, RunStatus.INTERRUPTED, event_type="station.update.inspection_required")
        return True
    now = utcnow().timestamp()
    next_check = run.metadata_json.get("native_update_inspect_after")
    if type(next_check) in (int, float) and now < next_check <= now + 30:
        return True
    original_claim = run.worker_id, run.claimed_at
    run.metadata_json = {**run.metadata_json, "native_update_inspect_after": now + 10}
    session.commit()  # No writer or read transaction spans native IPC waits.
    try:
        reply = runner.station_update(message(run, "inspect"))
        # Inspection can outlive a coordinator tick. Reacquire the short writer
        # and current identity before publishing a result from the native owner.
        session.refresh(run)
        if (
            run.status in {"succeeded", "failed", "canceled"}
            or (
                run.worker_id,
                run.claimed_at,
            )
            != original_claim
        ):
            return True
        value = checked_reply(run, reply)
    except (RunnerUnavailable, RunnerError, ValueError):
        append_event(session, run.id, "station.update.inspection_unavailable", {})
        return True
    if value["phase"] not in {"succeeded", "failed", "canceled", "inspection_required"}:
        # The independent owner may still be applying/restarting. It is never
        # launched a second time and the dispatch gate remains closed.
        return True
    if run.status == "interrupted":
        if value["phase"] == "inspection_required":
            return True
        if not worker_id:
            raise ValueError("Native result reconciliation requires its current coordinator identity")
        # These transitions are one transaction under the still-closed gate.
        # Queued/claimed states never become visible and no executor is called.
        original = {
            "worker_id": run.worker_id,
            "claimed_at": run.claimed_at.isoformat() if run.claimed_at else None,
        }
        run.metadata_json = {**run.metadata_json, "native_result_original_claim": original}
        transition(session, run, RunStatus.QUEUED, event_type="station.update.result_reconciliation")
        run.worker_id = worker_id
        transition(session, run, RunStatus.CLAIMED, event_type="station.update.result_claimed")
        transition(session, run, RunStatus.PREPARING, event_type="station.update.result_preparing")
        transition(session, run, RunStatus.RUNNING, event_type="station.update.result_verified")
        if value["phase"] == "canceled":
            transition(
                session, run, RunStatus.CANCEL_REQUESTED, event_type="station.update.cancellation_verified"
            )
    finish(session, run, value)
    gate = session.get(Setting, KEY)
    if (
        value["phase"] in {"succeeded", "failed", "canceled"}
        and gate is not None
        and gate.value.get("run_id") == run.id
    ):
        if gate.value.get("owner_id") != run.owner_id:
            raise ValueError("The native update completion does not own the dispatch gate")
        session.delete(gate)  # Same commit as terminal history; no crash gap.
    return True


def recover_gate(session, runner, worker_id):
    """Reconcile an interrupted update after the operator finished native recovery."""
    gate = session.get(Setting, KEY)
    if gate is None or not isinstance(gate.value, dict):
        return
    run = session.get(Run, gate.value.get("run_id"))
    if (
        run is None
        or run.executor_type != "station_update"
        or run.status != "interrupted"
        or run.owner_id != gate.value.get("owner_id")
    ):
        return  # Unknown gates remain closed for inspection.
    session.commit()
    recover(session, run, runner, worker_id=worker_id)
    session.commit()


class StationUpdateExecutor(HostMediaExecutor):
    name = "station_update"
    requires_gpu = False

    def execute(self, session, run):
        require_administrator(session, run)
        claim = run.worker_id, run.claimed_at
        if self._cancel_before_dispatch(session, run):
            session.commit()
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="run.started")
        session.commit()
        runner = RunnerClient(timeout=10)
        gate = None
        action = "inspect" if run.metadata_json.get("dispatch_attempted") else "prepare"
        if action == "prepare":

            def attempted():
                run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}

            if not self._database_step(session, run, claim, attempted):
                return "done"
        value = checked_reply(run, runner.station_update(message(run, action)))
        while True:
            canceled = False

            def observe():
                nonlocal canceled
                require_administrator(session, run)
                cancel_expired_run(session, run.id)
                canceled = run.status == "cancel_requested"
                old = run.metadata_json.get("native_update", {}).get("phase")
                run.metadata_json = {**run.metadata_json, "native_update": value}
                if old != value["phase"]:
                    append_event(session, run.id, "station.update.progress", {"phase": value["phase"]})

            if not self._database_step(session, run, claim, observe):
                return "done"
            phase = value["phase"]
            if phase in {"succeeded", "failed", "canceled", "inspection_required"}:
                if gate and phase != "inspection_required":
                    release(run.id, gate)
                self._database_step(session, run, claim, lambda: finish(session, run, value))
                return "done"
            if canceled and phase in {"queued", "downloading", "preparing", "ready"}:
                value = checked_reply(run, runner.station_update(message(run, "cancel")))
                continue
            if phase == "ready":
                gate = take(run.id, claim)
                if gate is not None:

                    def applying():
                        require_administrator(session, run)
                        if run.status == "cancel_requested":
                            return
                        run.metadata_json = {
                            **run.metadata_json,
                            "update_apply_requested": True,
                            "update_gate": gate,
                        }

                    if not self._database_step(session, run, claim, applying):
                        return "done"
                    if run.status != "cancel_requested":
                        value = checked_reply(run, runner.station_update(message(run, "apply")))
                        continue
            time.sleep(0.5)
            value = checked_reply(run, runner.station_update(message(run, "inspect")))
