"""Resource-admitted offline preview execution and immutable frame adoption."""

import hashlib
import os
import stat
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.models import Artifact, ResourceLock, Run
from app.native_job_executor import NativeJobExecutor
from app.permissions import require
from app.python_execution import read_owned_file
from app.resources import RESOURCE_WAIT_KEY, release_run_locks, reserve_memory
from app.runner_client import RunnerClient
from app.runs import mark_failed, request_cancel, transition
from app.site_preview import MAX_FRAME, PERMISSIONS, Interact, capability, get_preview, source_snapshot
from app.state import TERMINAL, RunStatus
from app.task_control import lock_task


def adopt_frame(session, preview, frame):
    source = preview.parameters["source"]
    request = preview.parameters["request"]
    revision = frame.get("revision")
    aid = frame.get("action_id")
    if (
        type(revision) is not int
        or not 0 <= revision <= 128
        or frame.get("width") != request["width"]
        or frame.get("height") != request["height"]
    ):
        raise ValueError("Preview frame viewport or revision changed")
    if revision == 0:
        if aid is not None:
            raise ValueError("Initial preview frame cannot belong to an interaction")
    else:
        action = session.get(Run, str(aid)) if isinstance(aid, str) else None
        if (
            action is None
            or action.executor_type != "site_preview_action"
            or action.task_id != preview.task_id
            or action.parent_run_id != preview.id
            or action.parameters.get("preview_run_id") != preview.id
            or action.parameters["request"]["expected_revision"] + 1 != revision
        ):
            raise ValueError("Preview frame does not belong to this interaction")
    relative = f"runtime/site-previews/{preview.id}/frames/{revision}.png"
    if frame.get("relative_path") != relative:
        raise ValueError("Preview frame cannot select a host path")
    path = read_owned_file(relative, frame.get("size_bytes"), frame.get("sha256"), limit=MAX_FRAME)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != frame["size_bytes"]:
            raise ValueError("Preview frame changed before adoption")
        data = handle.read(MAX_FRAME + 1)
    if len(data) != frame["size_bytes"] or hashlib.sha256(data).hexdigest() != frame["sha256"]:
        raise ValueError("Preview frame changed before adoption")
    artifact_id = str(uuid5(NAMESPACE_URL, f"ai-station:site-preview:{preview.id}:{revision}"))
    lock_task(session, preview.task)
    session.refresh(preview)
    if preview.status in {"cancel_requested", "canceled", "failed", "interrupted"}:
        raise InterruptedError("Preview closed before frame adoption")
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
            temporary.write(data)
            temporary.flush()
            artifact = register_file(
                session,
                source=Path(temporary.name),
                artifact_id=artifact_id,
                artifact_type="image",
                mime_type="image/png",
                original_filename=f"preview-frame-{revision}.png",
                run_id=preview.id,
                parent_artifact_ids=[source["artifact_id"]],
                metadata={
                    "role": "site_preview_frame",
                    "preview_run_id": preview.id,
                    "action_run_id": aid,
                    "revision": revision,
                    "source_validation_run_id": source["validation_run_id"],
                    "source_task_id": source["source_task_id"],
                },
            )
        if (
            artifact.metadata_json["width"] != request["width"]
            or artifact.metadata_json["height"] != request["height"]
        ):
            raise ValueError("Preview PNG dimensions do not match its viewport")
    if (
        artifact.sha256 != frame["sha256"]
        or artifact.run_id != preview.id
        or artifact.parent_artifact_ids != [source["artifact_id"]]
    ):
        raise ValueError("Preview revision already belongs to another frame")
    current = preview.metadata_json.get("frame")
    if not current or current["revision"] < revision:
        value = {
            key: frame.get(key)
            for key in ("revision", "width", "height", "path", "title", "blocked_requests", "action_id")
        }
        value["artifact_id"] = artifact.id
        preview.metadata_json = {**preview.metadata_json, "frame": value}
        append_event(
            session,
            preview.id,
            "preview.frame.updated",
            {"artifact_id": artifact.id, "revision": revision, "action_run_id": aid},
        )
    return artifact


class PreviewExecutor(NativeJobExecutor):
    name = "site_preview"
    permissions = PERMISSIONS
    error_type = "SitePreviewFailed"

    def execute(self, session, run):
        try:
            return super().execute(session, run)
        finally:
            if (
                run.status in TERMINAL
                and run.metadata_json.get("process_confirmed_gone")
                and not run.metadata_json.get("cleanup_requires_inspection")
            ):
                release_run_locks(session, run.id)

    def prepare(self, session, run):
        source = source_snapshot(
            session, run.parameters["source"]["validation_run_id"], run.parameters["source"]["artifact_id"]
        )
        if source != run.parameters["source"]:
            raise ValueError("Preview source changed after enqueue")
        if (
            run.project_id != source["project_id"]
            or run.task.project_id != run.project_id
            or run.agent_id is not None
            or run.requested_gpu != "none"
        ):
            raise ValueError("Preview must preserve its operator, project and CPU execution scope")
        caps = capability()
        if not caps["available"] or caps.get("runner_id") != run.parameters["runner_id"]:
            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
            mark_failed(session, run, "PreviewUnavailable", caps.get("reason") or "Preview target changed")
            return False
        session.commit()
        hardware = RunnerClient().hardware()
        lock_task(session, run.task)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return False
        key = run.requested_resources["exclusive"]
        if key != "site-preview:" + run.parameters["runner_id"]:
            raise ValueError("Invalid preview resource identity")
        held = (
            session.query(ResourceLock)
            .filter(ResourceLock.resource_key == key, ResourceLock.released_at.is_(None))
            .first()
        )
        available = held is None or held.run_id == run.id
        ready = available and reserve_memory(
            session, run, (hardware.get("memory") or {}).get("available_mib"), 1536
        )
        if not ready:
            release_run_locks(session, run.id)
            run.task.metadata_json = {
                **run.task.metadata_json,
                RESOURCE_WAIT_KEY: (utcnow() + timedelta(seconds=5)).isoformat(),
            }
            run.metadata_json = {
                **run.metadata_json,
                "resource_wait_reason": "Waiting for available host RAM or preview slot",
            }
            transition(session, run, RunStatus.INTERRUPTED, event_type="run.resource_wait")
            transition(session, run, RunStatus.QUEUED, event_type="run.requeued")
            run.finished_at = None
            run.worker_id = None
            run.lease_expires_at = None
            return False
        if held is None:
            session.add(ResourceLock(resource_key=key, run_id=run.id))
        run.task.metadata_json = {
            key: value for key, value in run.task.metadata_json.items() if key != RESOURCE_WAIT_KEY
        }
        run.allocated_resources = {
            **run.allocated_resources,
            "gpu": "none",
            "exclusive": key,
            "ram_mib": 1536,
        }
        return True

    def payload(self, run):
        body = run.parameters["request"]
        source = run.parameters["source"]
        return {
            "run_id": run.id,
            "archive": {key: source[key] for key in ("artifact_id", "sha256", "size_bytes")},
            "width": body["width"],
            "height": body["height"],
            "maximum_runtime": body["maximum_runtime"],
            "permissions": list(run.effective_permissions),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/site-preview", payload)

    def rejected(self, session, run, runner, error):
        cleanup = runner.request("POST", f"/v1/runs/site-preview/{run.id}/close", {})
        if cleanup.get("cleanup_confirmed") is True:
            run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
            mark_failed(session, run, "RunnerRejected", str(error))
        else:
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Preview dispatch cleanup requires inspection"},
            )

    def observe(self, session, run, runner, process):
        value = runner.request("GET", f"/v1/runs/site-preview/{run.id}/state")
        lock_task(session, run.task)
        session.refresh(run)
        if value.get("cancel_requested") and run.status not in TERMINAL and run.status != "cancel_requested":
            request_cancel(session, run)
        run.metadata_json = {**run.metadata_json, "expires_at": value.get("expires_at")}
        if value.get("frame") and run.status not in {"cancel_requested", "canceled"}:
            adopt_frame(session, run, value["frame"])

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/site-preview/{run_id}/report")

    def finish(self, session, run, report):
        run.summary = (
            "Preview session expired" if report.get("reason") == "expired" else "Preview session ended"
        )
        run.metadata_json = {**run.metadata_json, "completion_reason": report.get("reason")}
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class PreviewActionExecutor(NativeJobExecutor):
    name = "site_preview_action"
    permissions = PERMISSIONS
    error_type = "PreviewInteractionFailed"

    def payload(self, run):
        from sqlalchemy.orm import object_session

        parent = get_preview(object_session(run), run.parameters["preview_run_id"])
        if (
            run.task_id != parent.task_id
            or run.parent_run_id != parent.id
            or run.project_id != parent.project_id
        ):
            raise ValueError("Interaction does not belong to this preview Task")
        body = Interact.model_validate(run.parameters["request"]).model_dump(mode="json")
        return {
            "run_id": run.id,
            "preview_run_id": parent.id,
            "expected_revision": body["expected_revision"],
            "action": body["action"],
            "permissions": list(run.effective_permissions),
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/site-preview-action", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/site-preview-action/{run_id}/report")

    def finish(self, session, run, report):
        parent = session.get(Run, run.parameters["preview_run_id"])
        if parent is not None:
            lock_task(session, parent.task)
            session.refresh(parent)
            session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        if report.get("state") != "frame":
            mark_failed(
                session,
                run,
                "PreviewInteractionRejected",
                report.get("reason") or "Preview interaction rejected",
            )
            return "done"
        if parent is None or parent.status not in {"running", "succeeded"}:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Preview closed before interaction adoption"},
            )
            return "done"
        artifact = adopt_frame(session, parent, report["frame"])
        run.metadata_json = {
            **run.metadata_json,
            "frame_artifact_id": artifact.id,
            "revision": report["frame"]["revision"],
        }
        run.summary = "Preview interaction completed"
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class PreviewCloseExecutor:
    name = "site_preview_close"

    def execute(self, session, run):
        for permission in PERMISSIONS:
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status in {"cancel_requested", "canceled"}:
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        parent = get_preview(session, run.parameters["preview_run_id"])
        if run.project_id != parent.project_id:
            raise ValueError("Close must retain the preview project scope")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        result = RunnerClient().request(
            "POST", f"/v1/runs/site-preview/{run.parameters['preview_run_id']}/close", {}
        )
        parent = session.get(Run, run.parameters["preview_run_id"])
        if result.get("cleanup_confirmed") is not True:
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Preview cleanup still requires inspection"},
            )
            return "done"
        lock_task(session, parent.task)
        session.refresh(parent)
        parent.metadata_json = {
            **parent.metadata_json,
            "process_confirmed_gone": True,
            "cleanup_requires_inspection": False,
            "closed_at": utcnow().isoformat(),
        }
        release_run_locks(session, parent.id)
        run.summary = "Owned preview closed; resources released"
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
