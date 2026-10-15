"""Isolated worktree preparation through the durable host process boundary."""

import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.events import append_event
from app.models import Worktree
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError
from app.runs import mark_failed, transition
from app.state import RunStatus


class WorktreeExecutor:
    name = "worktree_prepare"

    def execute(self, session, run):
        for permission in ("filesystem_read", "workspace_write", "git_read", "git_write"):
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status in {"cancel_requested", "canceled"}:
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        payload = {
            "run_id": run.id,
            "project_id": run.project_id,
            "repo_path": run.parameters["repo_path"],
            "base_branch": run.parameters["base_branch"],
            "permissions": run.effective_permissions,
        }
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        runner = RunnerClient()
        try:
            process = runner.prepare_worktree(payload)
        except RunnerError as exc:
            if exc.status_code < 500:
                mark_failed(session, run, "RunnerRejected", str(exc))
                return "done"
            raise
        session.refresh(run)
        run.pid = process["pid"]
        run.process_group_id = process["process_group_id"]
        run.runner_id = process.get("runner_id")
        run.stdout_log, run.stderr_log = process["stdout_log"], process["stderr_log"]
        if run.status != "cancel_requested":
            transition(
                session, run, RunStatus.RUNNING, event_type="executor.started", payload={"pid": run.pid}
            )
        session.commit()
        offsets = {"stdout_offset": 0, "stderr_offset": 0}
        while True:
            session.refresh(run)
            canceled = run.status == "cancel_requested"
            session.commit()
            if canceled:
                runner.cancel_process(run.id)
            process = runner.inspect_process(run.id, **offsets)
            for stream in ("stdout", "stderr"):
                if process.get(stream):
                    append_event(session, run.id, stream, {"text": process[stream]})
                offsets[f"{stream}_offset"] = process[f"{stream}_offset"]
            session.commit()
            if (
                not process["alive"]
                and not process.get("completion_pending")
                and not process["stdout_more"]
                and not process["stderr_more"]
            ):
                break
            if not process["stdout_more"] and not process["stderr_more"]:
                time.sleep(0.2)
        session.refresh(run)
        run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
        if run.status == "cancel_requested" or process["status"] == "canceled":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if process["status"] == "interrupted" or process.get("exit_code") is None:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Exit status unavailable; inspect worktree reservation"},
            )
            return "done"
        if process["exit_code"] != 0:
            mark_failed(
                session,
                run,
                "WorktreePreparationFailed",
                process.get("stderr_tail") or "Git preparation failed",
            )
            return "done"
        session.commit()
        manifest = runner.inspect_worktree(run.id)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == run.id))
        if (
            worktree is None
            or manifest["state"] != "ready"
            or manifest["run_id"] != run.id
            or manifest["project_id"] != run.project_id
            or manifest["branch"] != worktree.branch
            or manifest["relative_path"] != worktree.relative_path
        ):
            raise ValueError("Worktree result does not match the queued reservation")
        worktree.owned = True
        from app.worktree_expiry import schedule_expiry

        schedule_expiry(worktree)
        report = {
            key: manifest[key]
            for key in ("run_id", "project_id", "branch", "base_branch", "base_commit", "relative_path")
        }
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="worktree.json",
                run_id=run.id,
                metadata={"project_id": run.project_id},
            )
        append_event(session, run.id, "git.worktree.created", report)
        run.metadata_json = {**run.metadata_json, "worktree": report}
        run.summary = f"Prepared {worktree.branch}; no coding agent or validation command was launched."
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        if "agent_data" in run.parameters:
            from app.data_agents import queue_generation

            queue_generation(session, run, worktree)
        else:
            from app.coding_tasks import queue_proposal

            queue_proposal(session, run, worktree)
        return "done"
