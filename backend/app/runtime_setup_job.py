"""Worker lifecycle around the idempotent native runtime preparation journal."""

import json
import re
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.model_setup import fingerprint
from app.models import User
from app.permissions import require
from app.resources import RESOURCE_WAIT_KEY, release_run_locks, reserve_memory
from app.runner_client import RunnerClient, RunnerError
from app.runs import mark_failed, transition
from app.runtime_setup_api import INTENT, PERMISSIONS
from app.state import RunStatus
from app.task_control import lock_task


class LostClaim(Exception):
    pass


def validate_operation(run, *, executor_type="runtime_setup"):
    saved = run.task.metadata_json.get("runtime_preparation") or {}
    parameters = run.parameters
    if (
        run.executor_type != executor_type
        or run.task.owner_id != run.owner_id
        or run.task.intent != INTENT
        or saved.get("license_accepted") is not True
        or saved.get("recipe") != parameters.get("recipe")
        or fingerprint(parameters.get("recipe")) != parameters.get("manifest_sha256")
        or saved.get("manifest_sha256") != parameters.get("manifest_sha256")
        or parameters.get("profile") != parameters["recipe"].get("profile")
        or saved.get("run_id") != run.id
    ):
        raise ValueError("The reviewed runtime preparation identity changed")


def payload(run):
    return {
        "run_id": run.id,
        "profile": run.parameters["profile"],
        "manifest_sha256": run.parameters["manifest_sha256"],
        "deadline_at": run.parameters["execution_deadline_at"],
        "permissions": PERMISSIONS,
    }


def cancel_payload(run):
    return {"profile": run.parameters["profile"], "permissions": PERMISSIONS}


def confirmed_gone(result, run):
    return (
        isinstance(result, dict)
        and result.get("run_id") == run.id
        and result.get("alive") is False
        and result.get("status") in {"succeeded", "canceled", "failed", "interrupted"}
        and result.get("requires_inspection") is False
        and (
            result.get("manifest_sha256") == run.parameters["manifest_sha256"]
            or result.get("status") == "canceled"
            and result.get("manifest_sha256") is None
            and not result.get("process")
        )
    )


def authorized(session, run):
    if not run.owner_id:
        return True
    user = session.get(User, run.owner_id, populate_existing=True)
    return bool(user and user.enabled and user.is_admin and not user.bootstrap_pending)


def publish_image_receipt(session, run, result):
    image = result.get("image") or {}
    if (
        image.get("reference") != run.parameters["recipe"]["image_reference"]
        or image.get("platform") != "linux/amd64"
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(image.get("id", "")))
    ):
        raise ValueError("Prepared runtime image does not match its reviewed source")
    receipt = {
        "profile": run.parameters["profile"],
        "manifest_sha256": run.parameters["manifest_sha256"],
        "image": image,
        "inference_tested": False,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as file:
        json.dump(receipt, file)
        file.flush()
        register_file(
            session,
            source=Path(file.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="runtime-preparation.json",
            run_id=run.id,
            metadata={"runtime_preparation": True},
        )
    run.metadata_json = {
        **run.metadata_json,
        "runtime_preparation": {
            "phase": "image_verified",
            "received_bytes": run.parameters["recipe"]["download_bytes"],
            "expected_bytes": run.parameters["recipe"]["download_bytes"],
            "image_id": image["id"],
        },
    }
    run.summary = "Runtime image verified. Local model loading and first inference are checked separately."
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    return "done"


class RuntimeSetupExecutor:
    name = "runtime_setup"
    ram_mib = 1024
    required_permissions = PERMISSIONS

    def validate(self, run):
        validate_operation(run, executor_type=self.name)

    def runner(self):
        return RunnerClient(timeout=30)

    def payload(self, run):
        return payload(run)

    def before_native(self, session, run, check):
        return False

    def progress(self, run, value):
        if not isinstance(value, dict) or value.get("type") not in {
            "runtime.prepare.progress",
            "runtime.prepare.started",
            "runtime.prepare.verifying",
        }:
            return None
        expected = run.parameters["recipe"]["download_bytes"]
        received = value.get(
            "received_bytes", (run.metadata_json.get("runtime_preparation") or {}).get("received_bytes", 0)
        )
        if type(received) is not int or not 0 <= received <= expected:
            return None
        return {
            "phase": "verifying"
            if value["type"] == "runtime.prepare.verifying"
            else value.get("stage", "preparing"),
            "received_bytes": received,
            "expected_bytes": expected,
        }

    def complete(self, session, run, result, runner):
        return publish_image_receipt(session, run, result)

    def execute(self, session, run):
        for permission in self.required_permissions:
            require(run.effective_permissions, permission)
        self.validate(run)
        owner, claim = run.worker_id, run.claimed_at
        runner = self.runner()
        release = False

        def check(*, commit=True):
            session.refresh(run)
            if run.worker_id != owner or run.claimed_at != claim:
                raise LostClaim()
            session.refresh(run.task, ["metadata_json"])
            cancel_expired_run(session, run.id)
            stopped = (
                run.status in {"cancel_requested", "canceled"}
                or run.cancellation_requested_at is not None
                or bool(run.metadata_json.get("cancel_on_resume"))
                or bool(run.task.metadata_json.get("stop_requested_at"))
                or not authorized(session, run)
            )
            if commit:
                session.commit()
            return stopped

        try:
            stopped = check()
            if not stopped and not run.metadata_json.get("dispatch_attempted"):
                hardware = runner.hardware()
                stopped = check() or stopped
                if not stopped and not reserve_memory(
                    session, run, (hardware.get("memory") or {}).get("available_mib"), self.ram_mib
                ):
                    run.task.metadata_json = {
                        **run.task.metadata_json,
                        RESOURCE_WAIT_KEY: (utcnow() + timedelta(seconds=5)).isoformat(),
                    }
                    transition(session, run, RunStatus.INTERRUPTED, event_type="resource.waiting")
                    transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
                    run.finished_at = run.worker_id = run.lease_expires_at = None
                    release = True
                    return "requeued"
                session.commit()
            if run.status == "claimed":
                transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            session.commit()
            if not stopped and not run.metadata_json.get("dispatch_attempted"):
                prepared = self.before_native(session, run, check)
                if prepared == "requeued":
                    release = True
                    return "requeued"
                stopped = bool(prepared) or check() or stopped
            # This flag precedes the native request. A lost response reattaches
            # to the same immutable Run; a late Stop can fence an unsent request.
            run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
            session.commit()
            try:
                result = (
                    runner.cancel_runtime_preparation(run.id, cancel_payload(run))
                    if stopped
                    else runner.prepare_runtime(self.payload(run))
                )
            except RunnerError as exc:
                if 400 <= exc.status_code < 500:
                    try:
                        runner.inspect_runtime_preparation(run.id)
                    except RunnerError as observed:
                        if observed.status_code == 404:
                            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
                            release = True
                            mark_failed(
                                session,
                                run,
                                "RuntimePreparationRejected",
                                "Runtime preparation was rejected before dispatch; inspect prerequisites and resume",
                            )
                            return "done"
                raise
            stopped = check() or stopped
            cursor = run.metadata_json.get("runtime_log_cursor") or {}
            offsets = {key: cursor.get(key, 0) for key in ("stdout_offset", "stderr_offset")}
            if any(type(value) is not int or value < 0 for value in offsets.values()):
                raise ValueError("Saved runtime log offsets are invalid")
            pending = cursor.get("pending", "")
            if not isinstance(pending, str) or len(pending) > 128 * 1024:
                raise ValueError("Saved runtime progress exceeded its bound")
            if not stopped and run.status == "preparing":
                transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            while True:
                stopped = check() or stopped
                if stopped:
                    result = runner.cancel_runtime_preparation(run.id, cancel_payload(run))
                else:
                    result = runner.inspect_runtime_preparation(run.id, **offsets)
                stopped = check() or stopped
                if result.get("run_id") != run.id or result.get("manifest_sha256") not in (
                    None,
                    run.parameters["manifest_sha256"],
                ):
                    raise ValueError("Native runtime preparation identity changed")
                process = result.get("process") or {}
                run.runner_id = result.get("runner_id", run.runner_id)
                if process:
                    run.pid, run.process_group_id = process.get("pid"), process.get("process_group_id")
                    run.stdout_log, run.stderr_log = process.get("stdout_log"), process.get("stderr_log")
                for stream in ("stdout", "stderr"):
                    text = process.get(stream) or ""
                    if text:
                        append_event(session, run.id, stream, {"text": text})
                    offsets[stream + "_offset"] = process.get(stream + "_offset", offsets[stream + "_offset"])
                    if stream == "stdout":
                        pending += text
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    progress = self.progress(run, value)
                    if progress is None:
                        continue
                    run.metadata_json = {**run.metadata_json, "runtime_preparation": progress}
                    append_event(session, run.id, "runtime.prepare.progress", progress)
                if len(pending) > 128 * 1024:
                    raise ValueError("Runtime progress exceeded its bound")
                run.metadata_json = {
                    **run.metadata_json,
                    "runtime_log_cursor": {**offsets, "pending": pending},
                }
                session.commit()
                if result.get("requires_inspection"):
                    run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
                    transition(session, run, RunStatus.INTERRUPTED, event_type="recovery.inspection_required")
                    return "done"
                if (
                    not result.get("alive")
                    and not process.get("stdout_more")
                    and not process.get("stderr_more")
                ):
                    break
                time.sleep(0.2)
            if not confirmed_gone(result, run):
                raise ValueError("Native runtime preparation completion is unconfirmed")
            release = True
            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
            session.commit()
            lock_task(session, run.task)
            stopped = check(commit=False) or stopped
            if run.owner_id:
                user = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
                stopped = stopped or not bool(
                    user and user.enabled and user.is_admin and not user.bootstrap_pending
                )
            run.metadata_json = {
                **run.metadata_json,
                "process_confirmed_gone": True,
                "cleanup_requires_inspection": False,
            }
            if stopped or result["status"] == "canceled":
                if run.status not in {"canceled", "cancel_requested"}:
                    transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
                if run.status != "canceled":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return "done"
            if result["status"] == "failed":
                mark_failed(
                    session,
                    run,
                    "RuntimePreparationFailed",
                    "Runtime preparation failed; inspect its log and resume explicitly",
                )
                return "done"
            if result["status"] != "succeeded":
                transition(session, run, RunStatus.INTERRUPTED, event_type="run.interrupted")
                run.error_type, run.error_message = (
                    "RuntimePreparationIncomplete",
                    "Inspect runtime preparation and resume explicitly",
                )
                return "done"
            return self.complete(session, run, result, runner)
        except LostClaim:
            release = False
            session.rollback()
            return "done"
        finally:
            if release:
                release_run_locks(session, run.id)
