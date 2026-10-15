"""Saved project validation through managed native sandbox execution."""

import json
import tempfile
import time
from pathlib import Path

from app.artifacts import register_file
from app.build_artifacts import register_build
from app.events import append_event
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError
from app.runs import mark_failed, transition
from app.state import RunStatus


class ProjectValidationExecutor:
    name = "project_validation"

    def execute(self, session, run):
        for permission in ("filesystem_read", "workspace_write", "git_read", "shell_project_commands"):
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
            "worktree_run_id": run.parameters["worktree_run_id"],
            "commands": run.parameters["commands"],
            "permissions": run.effective_permissions,
            **(
                {"manifest_snapshot": run.parameters["manifest_snapshot"]}
                if "manifest_snapshot" in run.parameters
                else {}
            ),
        }
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        runner = RunnerClient()
        try:
            process = runner.start_validation(payload)
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
                payload={"reason": "Exit status unavailable; inspect validation logs"},
            )
            return "done"
        if process["exit_code"] != 0:
            mark_failed(
                session,
                run,
                "ValidationExecutionFailed",
                process.get("stderr_tail") or "Validation process failed",
            )
            return "done"
        session.commit()
        report = runner.validation_report(run.id)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if (
            report["run_id"] != run.id
            or report["project_id"] != run.project_id
            or report["worktree_run_id"] != run.parameters["worktree_run_id"]
            or [{"kind": item["kind"], "argv": item["argv"]} for item in report["commands"]]
            != run.parameters["commands"]
        ):
            raise ValueError("Validation report does not match its request")
        succeeded = all(item["exit_code"] == 0 for item in report["commands"])
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="validation.json",
                run_id=run.id,
                metadata={"project_id": run.project_id},
            )
        register_build(session, run, report)
        for index, result in enumerate(report["commands"]):
            append_event(session, run.id, "validation.completed", {"index": index, **result})
        run.metadata_json = {**run.metadata_json, "validation": report}
        run.summary = f"{sum(item['exit_code'] == 0 for item in report['commands'])}/{len(report['commands'])} project commands passed."
        if succeeded:
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        else:
            mark_failed(
                session,
                run,
                "ValidationFailed",
                "One or more project commands failed; inspect the validation report",
            )
            from app.local_coding import queue_automatic_repair

            queue_automatic_repair(session, run)
        return "done"
