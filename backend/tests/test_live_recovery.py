from datetime import timedelta

import pytest
from app.db import utcnow
from app.live_executor import LiveExecutor
from app.models import ResourceLock
from app.recovery import recover_stale
from app.resources import active_locks
from app.runner_client import RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, request_cancel, transition


def dispatched(session):
    task = create_task(
        session, title="Live qualification", prompt="Local capture", capability="live.identity"
    )
    run = create_run(
        session,
        task,
        run_type="live",
        capability="live.identity",
        executor_type="live_identity",
        permissions=["filesystem_read", "workspace_write"],
    )
    run.worker_id = "old-worker"
    run.claimed_at = utcnow() - timedelta(minutes=3)
    for status in ("claimed", "preparing", "running"):
        transition(session, run, status, event_type="test.state")
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    run.metadata_json = {"dispatch_attempted": True}
    session.add(ResourceLock(resource_key="gpu:7", run_id=run.id))
    session.commit()
    return run


@pytest.mark.parametrize("reachable", [True, False])
def test_lost_dispatch_is_fenced_before_gpu_release(session, reachable):
    run = dispatched(session)

    class Native:
        fenced = False

        def inspect_process(self, identity):
            raise RunnerError(404, "not found")

        def request(self, method, path):
            assert method == "POST" and path == f"/v1/live/{run.id}/cancel"
            if not reachable:
                raise RunnerUnavailable("offline")
            self.fenced = True
            return {"run_id": run.id, "executor": "live_identity", "alive": False, "status": "canceled"}

    native = Native()
    assert recover_stale(session, native) == [run.id]
    assert native.fenced is reachable
    if reachable:
        assert run.status == "interrupted" and not active_locks(session)
    else:
        assert run.status == "running" and active_locks(session)


def test_expired_worker_resumes_inspection_without_restarting_capture(session):
    run = dispatched(session)

    class Native:
        def inspect_process(self, identity, **offsets):
            return {
                "run_id": identity,
                "executor": "live_identity",
                "alive": False,
                "status": "exited",
                "exit_code": 75,
                "stdout": "",
                "stderr": "",
                "stdout_offset": 0,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }

    native = Native()
    assert recover_stale(session, native) == [run.id]
    assert run.status == "queued" and run.metadata_json["media_inspection_resume"]
    assert active_locks(session)
    request_cancel(session, run)
    assert run.status == "queued"  # The original owned native stop still needs inspection.
    session.rollback()


def test_ended_capture_is_interrupted_without_publishing_a_recording(session):
    run = dispatched(session)
    LiveExecutor().on_inspection(session, run, {"alive": False, "exit_code": 75, "stdout": ""})
    assert run.status == "interrupted" and not active_locks(session)
    assert run.metadata_json["process_confirmed_gone"]
