from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from alembic import command
from app.db import alembic_config, session_factory, utcnow
from app.engine import tick
from app.events import list_events
from app.models import ResourceLock, Run
from app.recovery import recover_stale
from app.resources import reserve_gpu
from app.runner_client import RunnerError, RunnerUnavailable
from app.runs import claim_next, create_run, create_task, request_cancel, transition
from app.state import InvalidTransition, RunStatus
from sqlalchemy import inspect, select, text


def queued(session, **kwargs):
    task = create_task(session, title="test", prompt="", capability="test")
    run = create_run(session, task, run_type="test", capability="test", executor_type="fake", **kwargs)
    session.commit()
    return run


def test_migrations_and_wal(session):
    assert session.scalar(text("PRAGMA journal_mode")) == "wal"
    assert session.scalar(text("PRAGMA foreign_keys")) == 1
    assert "runs" in inspect(session.connection()).get_table_names()
    session.rollback()
    command.check(alembic_config())


def test_lifecycle(session):
    run = queued(session)
    assert tick(session, "test-worker") == run.id
    session.refresh(run)
    assert run.status == "succeeded"
    assert run.started_at.tzinfo is not None
    assert run.finished_at >= run.started_at
    events = list_events(session, run.id)
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert [e.event_type for e in events] == [
        "run.created",
        "run.claimed",
        "executor.preparing",
        "executor.started",
        "stdout",
        "run.completed",
    ]
    with pytest.raises(InvalidTransition):
        transition(session, run, "running", event_type="bad")


def test_two_workers_cannot_claim_same_run(session):
    run = queued(session)
    barrier = Barrier(2)

    def claim(worker):
        barrier.wait()
        with session_factory()() as current:
            item = claim_next(current, worker)
            current.commit()
            return item.id if item else None

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(claim, ["one", "two"]))
    assert ids.count(run.id) == 1
    assert ids.count(None) == 1


def test_cancellation_survives_stale_executor(session):
    run = queued(session)
    claim_next(session, "worker")
    transition(session, run, "preparing", event_type="executor.preparing")
    transition(session, run, "running", event_type="executor.started")
    session.commit()
    with session_factory()() as other:
        request_cancel(other, other.get(Run, run.id))
        other.commit()
    with pytest.raises(InvalidTransition):
        transition(session, run, "succeeded", event_type="run.completed")
    assert run.status == "cancel_requested"


class Missing:
    def inspect_process(self, run_id):
        raise RunnerError(404, "not found")


class Offline:
    def inspect_process(self, run_id):
        raise RunnerUnavailable("offline")


@pytest.mark.parametrize(
    "status,retry,target,expected",
    [
        ("claimed", "safe", "host", "queued"),
        ("preparing", "safe", "host", "interrupted"),
        ("running", "safe", "host", "interrupted"),
        ("claimed", "inspect", "host", "interrupted"),
        ("cancel_requested", "safe", "host", "canceled"),
    ],
)
def test_recovery_never_repeats_dispatched_work(session, status, retry, target, expected):
    run = queued(session, retry_class=retry, execution_target=target)
    run.status = status
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    session.commit()
    recover_stale(session, Missing())
    assert run.status == expected


def test_runner_outage_preserves_lease_and_gpu_reservation(session):
    run = queued(session, requested_gpu="7", retry_class="safe")
    reserve_gpu(session, run, [7])
    run.status = "preparing"
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    session.commit()
    recover_stale(session, Offline())
    assert run.status == "preparing"
    assert run.lease_expires_at > utcnow()
    assert session.scalar(select(ResourceLock)).released_at is None


def test_resource_exclusion_uses_discovered_ids(session):
    first = queued(session, requested_gpu="auto")
    second = queued(session, requested_gpu="7")
    assert reserve_gpu(session, first, [7]) == "7"
    assert reserve_gpu(session, second, [7]) is None


@pytest.mark.parametrize("source", list(RunStatus))
@pytest.mark.parametrize("target", list(RunStatus))
def test_state_machine(source, target):
    from app.state import TRANSITIONS, assert_transition

    if target in TRANSITIONS[source]:
        assert_transition(source, target)
    else:
        with pytest.raises(InvalidTransition):
            assert_transition(source, target)


def test_reaping_pending_preserves_lease_and_gpu_reservation(session):
    class Reaping:
        def inspect_process(self, run_id):
            return {"alive": False, "completion_pending": True, "exit_code": None}

    run = queued(session, requested_gpu="7", retry_class="safe")
    reserve_gpu(session, run, [7])
    run.status = "running"
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    session.commit()
    recover_stale(session, Reaping())
    assert run.status == "running"
    assert run.lease_expires_at > utcnow()
    assert session.scalar(select(ResourceLock)).released_at is None
