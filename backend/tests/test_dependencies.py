import pytest
from app.db import session_factory
from app.dependencies import depend_on
from app.engine import tick
from app.models import Run, RunDependency
from app.runs import create_run, create_task, request_cancel, transition


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


def test_waiting_controller_observes_failed_tool_and_resumes_on_one_worker_slot(session):
    root = queued(session)
    root.executor_type = "controller-test"
    session.commit()

    class Controller:
        def execute(self, current, run):
            transition(current, run, "preparing", event_type="executor.preparing")
            transition(current, run, "running", event_type="executor.started")
            if not run.metadata_json.get("tool_id"):
                tool = create_run(
                    current,
                    run.task,
                    run_type="test",
                    capability="test",
                    executor_type="failing-tool",
                    parent_run_id=run.id,
                )
                run.metadata_json = {"tool_id": tool.id}
                transition(current, run, "waiting_for_tool", event_type="assistant.awaiting_tool")
                run.worker_id = None
                run.lease_expires_at = None
                depend_on(current, run, tool, require_success=False)
            else:
                assert current.get(Run, run.metadata_json["tool_id"]).status == "failed"
                transition(current, run, "succeeded", event_type="run.completed")

    class Failing:
        def execute(self, current, run):
            transition(current, run, "failed", event_type="run.failed")

    executors = {"controller-test": Controller(), "failing-tool": Failing()}
    root_id = root.id
    assert tick(session, "single-slot", executors=executors) == root_id
    session.refresh(root)
    assert root.status == "waiting_for_tool" and root.worker_id is None
    tool_id = root.metadata_json["tool_id"]
    assert tick(session, "single-slot", executors=executors) == tool_id
    assert tick(session, "single-slot", executors=executors) == root_id
    session.refresh(root)
    assert root.status == "succeeded"


def test_observation_edges_do_not_weaken_existing_dependencies_and_waiting_cancel_is_immediate(session):
    root, tool = queued(session), queued(session)
    depend_on(session, root, tool)
    with pytest.raises(ValueError, match="cannot be changed"):
        depend_on(session, root, tool, require_success=False)
    assert session.get(RunDependency, (root.id, tool.id)).require_success is True
    root.status = "waiting_for_tool"
    session.flush()
    request_cancel(session, root)
    assert root.status == "canceled"


def test_downgrade_refuses_a_queued_controller_before_it_publishes_dependencies(session):
    from alembic import command
    from app.db import alembic_config, get_engine

    task = create_task(
        session, title="Pending conversation", prompt="A request", capability="assistant.orchestrate"
    )
    root = create_run(
        session,
        task,
        run_type="assistant",
        capability="assistant.orchestrate",
        executor_type="assistant_controller",
    )
    session.commit()
    with get_engine().begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="durable controller state"):
            command.downgrade(config, "0044")
    assert session.get(Run, root.id).status == "queued"
