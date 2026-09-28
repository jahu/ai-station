"""Persist reviewed native commits as normal events and artifacts."""

import json
import tempfile
from pathlib import Path

from app.artifacts import register_file
from app.events import append_event
from app.models import Run
from app.native_job_executor import NativeJobExecutor
from app.runs import transition
from app.state import RunStatus


class ReviewedCommitExecutor(NativeJobExecutor):
    name = "reviewed_commit"
    permissions = ("filesystem_read", "git_read", "git_write")

    def payload(self, run):
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "permissions": run.effective_permissions,
            **{
                key: run.parameters[key]
                for key in ("source_run_id", "review_digest", "message", "protected_branches")
            },
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/reviewed-commit", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/reviewed-commit/{run_id}/report")

    def finish(self, session, run, report):
        if (
            report["run_id"] != run.id
            or report["source_run_id"] != run.parameters["source_run_id"]
            or report["project_id"] != run.project_id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
        ):
            raise ValueError("Commit report ownership changed")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="reviewed-commit.json",
                run_id=run.id,
                metadata={"commit": report["commit"], "branch": report["branch"]},
            )
        append_event(session, run.id, "git.commit.created", report)
        run.metadata_json = {**run.metadata_json, "git_commit": report}
        run.summary = f"Committed reviewed changes as {report['commit'][:12]} on {report['branch']}"
        source = session.get(Run, run.parameters["source_run_id"])
        source.metadata_json = {**source.metadata_json, "review_status": "committed", "git_commit": report}
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"
