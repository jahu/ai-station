"""Explicit removal of an owned worktree through a durable host Run."""

import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.models import Worktree
from app.native_job_executor import NativeJobExecutor
from app.runs import transition
from app.state import RunStatus


class WorktreeRemoveExecutor(NativeJobExecutor):
    name = "worktree_remove"
    permissions = ("filesystem_read", "workspace_write", "git_read", "git_write")
    error_type = "WorktreeRemovalFailed"

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "permissions": run.effective_permissions,
            "worktree_run_id": run.parameters["worktree_run_id"],
            "repo_path": run.parameters["repo_path"],
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/worktree-remove", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/worktree-remove/{run_id}/report")

    def finish(self, session, run, report):
        worktree = session.scalar(select(Worktree).where(Worktree.id == run.parameters["worktree_id"]))
        if (
            worktree is None
            or worktree.project_id != run.project_id
            or worktree.run_id != run.parameters["worktree_run_id"]
            or worktree.relative_path != report["relative_path"]
            or worktree.branch != report["branch"]
            or report["run_id"] != run.id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
            or report["project_id"] != run.project_id
            or report["repo_path"] != run.parameters["repo_path"]
        ):
            raise ValueError("Worktree removal result does not match the queued request")
        worktree.removed_at = utcnow()
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="worktree-removed.json",
                run_id=run.id,
                metadata={"project_id": run.project_id, "worktree_id": worktree.id},
            )
        append_event(session, run.id, "git.worktree.removed", report)
        run.metadata_json = {**run.metadata_json, "worktree": report}
        run.summary = f"Removed {worktree.branch}. Source checkout and GitHub remotes were not changed."
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return "done"
