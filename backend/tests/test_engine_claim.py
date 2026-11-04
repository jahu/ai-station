"""An executor exception belongs to its claim, not a recovered worker's Run."""

from datetime import timedelta

import pytest
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.events import list_events
from app.models import ResourceLock, Run
from app.runs import create_run, create_task, transition


@pytest.mark.parametrize("replacement", [None, "different-worker", "same-worker"])
@pytest.mark.parametrize("dispatched", [False, True])
def test_failure_cleanup_is_fenced_by_claim(session, replacement, dispatched):
    task = create_task(session, title="Claim fencing", prompt="", capability="test")
    run = create_run(session, task, run_type="test", capability="test", executor_type="claim_probe")
    session.commit()
    state = {}

    class Probe:
        def execute(self, current, item):
            transition(current, item, "preparing", event_type="executor.preparing")
            transition(current, item, "running", event_type="executor.started")
            item.metadata_json = {"dispatch_attempted": dispatched}
            lock = ResourceLock(resource_key="ram:" + item.id, run_id=item.id)
            current.add(lock)
            current.flush()
            state["lock_id"] = lock.id
            state["worker"] = item.worker_id
            state["claim"] = item.claimed_at
            current.commit()
            if replacement:
                with control_session_factory()() as other:
                    owned = other.get(Run, item.id)
                    if replacement == "different-worker":
                        owned.worker_id = replacement
                    owned.claimed_at += timedelta(seconds=1)
                    owned.lease_expires_at = utcnow() + timedelta(minutes=5)
                    state.update(worker=owned.worker_id, claim=owned.claimed_at, lease=owned.lease_expires_at)
                    other.commit()
            raise ValueError("Executor connection ended")

    assert tick(session, "original-worker", executors={"claim_probe": Probe()}) == run.id
    session.refresh(run)
    assert run.worker_id == state["worker"] and run.claimed_at == state["claim"]
    lock = session.get(ResourceLock, state["lock_id"], populate_existing=True)
    events = [event.event_type for event in list_events(session, run.id)]
    if replacement:
        assert run.status == "running" and not run.error_type, (run.error_message, state)
        assert run.lease_expires_at == state["lease"]
        assert lock.released_at is None
        assert "recovery.inspection_required" not in events and "run.failed" not in events
    elif dispatched:
        assert run.status == "running" and lock.released_at is None
        assert run.lease_expires_at <= utcnow()
        assert "recovery.inspection_required" in events
    else:
        assert run.status == "failed" and run.error_type == "ValueError"
        assert lock.released_at is not None and "run.failed" in events
