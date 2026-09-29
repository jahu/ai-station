"""Provider-independent coding review artifacts and configured validation."""

import json
import tempfile
from pathlib import Path

from app.artifacts import register_file
from app.events import append_event
from app.native_job_executor import NativeJobExecutor
from app.runs import transition
from app.state import RunStatus


class CodingProposalExecutor(NativeJobExecutor):
    def finish(self, session, run, report):
        if (
            report["run_id"] != run.id
            or report["project_id"] != run.project_id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
        ):
            raise ValueError("Coding report does not match the requested worktree")
        for content, kind, mime, filename in (
            (json.dumps(report, indent=2), "json", "application/json", "coding-review.json"),
            ("".join(item["diff"] for item in report["files"]), "git_diff", "text/x-diff", "changes.diff"),
        ):
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt") as handle:
                handle.write(content)
                handle.flush()
                register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type=kind,
                    mime_type=mime,
                    original_filename=filename,
                    run_id=run.id,
                    metadata={
                        "project_id": run.project_id,
                        "worktree_run_id": run.parameters["worktree_run_id"],
                    },
                )
        append_event(
            session,
            run.id,
            "coding.proposal.applied",
            {
                "summary": report["summary"],
                "files": [
                    {key: value for key, value in item.items() if key != "diff"} for item in report["files"]
                ],
                "provider": report["provider"],
            },
        )
        run.metadata_json = {**run.metadata_json, "coding_review": report, "review_status": "needs_review"}
        run.summary = report["summary"]
        transition(
            session,
            run,
            RunStatus.SUCCEEDED,
            event_type="run.completed",
            payload={"meaning": "Proposal applied; human review and validation still required"},
        )
        from app.coding_tasks import queue_validation

        queue_validation(session, run)
        return "done"
