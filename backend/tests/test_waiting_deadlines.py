from datetime import timedelta

from app.db import control_session_factory, utcnow
from app.dependencies import depend_on
from app.engine import tick
from app.heartbeat import cancel_expired_waiting
from app.models import Run
from app.resources import RESOURCE_WAIT_KEY
from app.runs import create_run as _create_run
from app.runs import create_task, transition
from app.state import RunStatus


def make_run(session, task, **kwargs):
    return _create_run(session, task, run_type="test", capability="test", executor_type="test", **kwargs)


def test_waiting_deadline_expires_even_with_a_blocked_prerequisite_and_resource_backoff():
    with control_session_factory()() as session:
        task = create_task(session, title="Bounded waiting", prompt="Neutral QA", capability="test")
        blocker = make_run(session, task)
        consumer = make_run(
            session,
            task,
            parameters={
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            },
        )
        depend_on(session, consumer, blocker)
        transition(session, consumer, RunStatus.CLAIMED, event_type="test.claimed")
        transition(session, consumer, RunStatus.PREPARING, event_type="test.preparing")
        transition(session, consumer, RunStatus.RUNNING, event_type="test.running")
        transition(session, consumer, RunStatus.WAITING_FOR_TOOL, event_type="test.waiting")
        consumer.metadata_json = {RESOURCE_WAIT_KEY: (utcnow() + timedelta(hours=1)).isoformat()}
        ids = blocker.id, consumer.id
        session.commit()
        cancel_expired_waiting(session)
        session.commit()
        assert session.get(Run, ids[1]).status == "canceled"
        assert session.get(Run, ids[0]).status == "queued"


def test_queued_expired_budget_is_canceled_before_any_executor_dispatch():
    with control_session_factory()() as session:
        task = create_task(session, title="Expired", prompt="Neutral QA", capability="test")
        expired = make_run(
            session,
            task,
            parameters={
                "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
            },
        )
        expired_id = expired.id
        session.commit()
        assert tick(session, "deadline-test", executors={}) == expired_id
        assert session.get(Run, expired_id).status == "canceled"


def test_waiting_sweep_preserves_future_and_unbounded_work():
    with control_session_factory()() as session:
        task = create_task(session, title="Waiting", prompt="Neutral QA", capability="test")
        runs = [
            make_run(session, task, parameters=p)
            for p in [
                {},
                {"execution_deadline_at": (utcnow() + timedelta(hours=1)).isoformat()},
            ]
        ]
        session.commit()
        cancel_expired_waiting(session)
        assert all(r.status == "queued" for r in runs)


def test_already_requested_native_cleanup_is_not_starved_by_deadline_sweep():
    with control_session_factory()() as session:
        task = create_task(session, title="Owned cleanup", prompt="Neutral QA", capability="test")
        run = _create_run(
            session,
            task,
            run_type="runtime",
            capability="runtime.load",
            executor_type="llama_load",
            parameters={"execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat()},
        )
        run.metadata_json = {"dispatch_attempted": True}
        session.commit()
        assert cancel_expired_waiting(session) == [run.id]
        assert run.status == "queued" and run.metadata_json["cancel_on_resume"] is True
        requested_at = run.cancellation_requested_at
        session.commit()
        assert cancel_expired_waiting(session) == []
        assert run.cancellation_requested_at == requested_at
