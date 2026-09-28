"""Shared owned-process media lifecycle, GPU scheduling, cancellation and artifacts."""

import time

from sqlalchemy.orm import Session

from app.artifacts import adopt_existing
from app.db import utcnow
from app.events import append_event
from app.models import Run
from app.permissions import require
from app.resources import release_run_locks, reserve_gpu
from app.runner_client import RunnerClient, RunnerError
from app.runs import mark_failed, transition
from app.state import RunStatus


class HostMediaExecutor:
    name = "host_media"
    suffix = ".bin"
    artifact_type = "document"
    mime_type = "application/octet-stream"

    def execute(self, session: Session, run: Run) -> str:
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        session.refresh(run)
        if self._cancel_before_dispatch(session, run):
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing", payload={})
        session.commit()
        runner = RunnerClient()
        indexes = [int(gpu["index"]) for gpu in runner.hardware().get("gpus", [])]
        session.refresh(run)
        if self._cancel_before_dispatch(session, run):
            return "done"
        allocated = reserve_gpu(session, run, indexes)
        if allocated is None:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "GPU busy"},
            )
            transition(session, run, RunStatus.QUEUED, event_type="run.requeued", payload={})
            run.queued_at = utcnow()
            run.finished_at = None
            run.worker_id = None
            run.lease_expires_at = None
            if run.requested_gpu != "none":
                from app.llama import evict_idle_models

                evict_idle_models(session, run, indexes)
            return "requeued"
        output = f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}{self.suffix}"
        # Durable before sending: even a lost response may hide a live process.
        run.metadata_json = {**run.metadata_json, "dispatch_attempted": True}
        session.commit()
        try:
            started = self._start(runner, run, allocated, output)
        except RunnerError as exc:
            if exc.status_code < 500:
                session.refresh(run)
                release_run_locks(session, run.id)
                mark_failed(session, run, "RunnerRejected", str(exc))
                return "done"
            raise
        session.refresh(run)
        run.pid = started.get("pid")
        run.process_group_id = started.get("process_group_id")
        run.runner_id = started.get("runner_id")
        run.stdout_log = started.get("stdout_log", "")
        run.stderr_log = started.get("stderr_log", "")
        if run.status != "cancel_requested":
            transition(
                session, run, RunStatus.RUNNING, event_type="executor.started", payload={"pid": run.pid}
            )
        session.commit()
        self._poll(session, run, runner, output)
        return "done"

    def _start(self, runner, run, allocated, output):
        raise NotImplementedError

    def output_metadata(self, output):
        return {}

    @staticmethod
    def _cancel_before_dispatch(session, run):
        if run.status in {"canceled", "cancel_requested"}:
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
            release_run_locks(session, run.id)
            return True
        return False

    def _poll(self, session, run, runner, output):
        offsets = {"stdout_offset": 0, "stderr_offset": 0}
        while True:
            session.refresh(run)
            cancel = run.status == "cancel_requested"
            session.commit()
            if cancel:
                runner.cancel_process(run.id)
            info = runner.inspect_process(run.id, **offsets)
            for stream in ("stdout", "stderr"):
                text = info.get(stream, "")
                if text:
                    append_event(session, run.id, stream, {"text": text})
                offsets[f"{stream}_offset"] = info[f"{stream}_offset"]
            session.commit()
            if (
                not info["alive"]
                and not info.get("completion_pending")
                and not info["stdout_more"]
                and not info["stderr_more"]
            ):
                break
            if not info["stdout_more"] and not info["stderr_more"]:
                time.sleep(0.4)
        session.refresh(run)
        # Inspection proved there is no live owned group; release is now safe.
        release_run_locks(session, run.id)
        run.metadata_json = {**run.metadata_json, "process_confirmed_gone": True}
        session.commit()
        session.refresh(run)
        if run.status == "cancel_requested" or info["status"] == "canceled":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled", payload={})
        elif info["status"] == "interrupted" or info.get("exit_code") is None:
            transition(
                session,
                run,
                RunStatus.INTERRUPTED,
                event_type="run.interrupted",
                payload={"reason": "Exit status unavailable; inspect output before retrying"},
            )
        elif info["exit_code"] != 0:
            mark_failed(session, run, "ExitCode", info.get("stderr_tail") or f"Exit {info['exit_code']}")
        else:
            adopt_existing(
                session,
                relative_path=output,
                artifact_type=self.artifact_type,
                mime_type=self.mime_type,
                original_filename=f"{run.id}{self.suffix}",
                run_id=run.id,
                metadata={"capability": run.capability, **run.parameters, **self.output_metadata(output)},
                parent_artifact_ids=run.parameters.get("parent_artifact_ids", []),
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
