import pytest
from app.db import session_factory
from app.dependencies import depend_on
from app.engine import tick
from app.models import Run
from app.runs import create_run, create_task, request_cancel


def queued(session):
    task = create_task(session, title="test", prompt="", capability="test")
    return create_run(session, task, run_type="test", capability="test", executor_type="fake")


def test_prerequisites_survive_session_restart_and_do_not_block_queue(session):
    dependent, prerequisite, unrelated = [queued(session) for _ in range(3)]
    depend_on(session, dependent, prerequisite)
    ids = dependent.id, prerequisite.id, unrelated.id
    session.commit()
    with session_factory()() as worker:
        assert tick(worker, "one") == ids[1]
        assert tick(worker, "one") == ids[0]
        assert tick(worker, "one") == ids[2]
        assert worker.get(Run, ids[0]).status == "succeeded"


def test_failed_dependency_propagates_without_executing_consumer(session):
    dependent, prerequisite = queued(session), queued(session)
    depend_on(session, dependent, prerequisite)
    request_cancel(session, prerequisite)
    session.commit()
    assert tick(session, "one") == dependent.id
    session.refresh(dependent)
    assert dependent.status == "failed"
    assert dependent.error_type == "PrerequisiteFailed"
    assert dependent.started_at is None


def test_cycles_rejected_and_canceling_consumer_preserves_shared_load(session):
    first, second, third = [queued(session) for _ in range(3)]
    depend_on(session, first, second)
    depend_on(session, second, third)
    with pytest.raises(ValueError, match="cycle"):
        depend_on(session, third, first)
    with pytest.raises(ValueError, match="cycle"):
        depend_on(session, first, first)
    request_cancel(session, first)
    session.commit()
    assert tick(session, "one") == third.id
    assert tick(session, "one") == second.id
    assert tick(session, "one") is None
