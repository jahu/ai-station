"""Shared dispatch, logs, cancellation and recovery for owned native jobs."""

import time

from app.events import append_event
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError
from app.runs import mark_failed, transition
from app.state import RunStatus


class NativeJobExecutor:
    permissions: tuple[str, ...] = ()
    error_type = "NativeJobFailed"

    def prepare(self, session, run):
        return True

    def observe(self, session, run, runner, process):
        pass

    def rejected(self, session, run, runner, error):
        mark_failed(session, run, "RunnerRejected", str(error))

    def execute(self, session, run):
        for permission in self.permissions:
            require(run.effective_permissions, permission)
        session.refresh(run)
        if run.status in {"cancel_requested", "canceled"}:
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if not self.prepare(session, run):
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        payload = self.payload(run)
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        runner = RunnerClient()
        try:
            process = self.start(runner, payload)
        except RunnerError as exc:
            if exc.status_code < 500:
                self.rejected(session, run, runner, exc)
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
            self.observe(session, run, runner, process)
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
        if process.get("cleanup_confirmed") is False:
            run.metadata_json = {**run.metadata_json, "cleanup_requires_inspection": True}
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Owned container cleanup could not be confirmed; inspect before retrying"},
            )
            return "done"
        if run.status == "cancel_requested" or process["status"] == "canceled":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        if process["status"] == "interrupted" or process.get("exit_code") is None:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Exit status unavailable; inspect owned worktree and logs"},
            )
            return "done"
        if process["exit_code"] != 0:
            mark_failed(
                session,
                run,
                self.error_type,
                process.get("stderr_tail") or "Native job failed",
            )
            return "done"
        session.commit()
        report = self.report(runner, run.id)
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            return "done"
        return self.finish(session, run, report)
