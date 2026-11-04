"""Actual queue/worker ownership and shared physical admission, with fake work."""

from datetime import timedelta

import pytest
from app.accounts import bootstrap_admin, create_user, login
from app.data_access import DataScope, ScopedSession
from app.db import control_session_factory, get_engine, session_factory
from app.engine import tick
from app.models import MemoryEntry, ResourceLock, Run
from app.resources import active_locks, memory_observation, release_run_locks, reserve_gpu, reserve_memory
from app.runs import create_run, create_task, transition
from sqlalchemy import select


@pytest.fixture
def users(session):
    owner = bootstrap_admin(session, "Owner", "synthetic owner password", local_setup=True)
    grant = login(session, "Owner", "synthetic owner password")
    alice = create_user(session, grant.principal, "Alice", "synthetic user password")
    bob = create_user(session, grant.principal, "Bob", "synthetic user password")
    session.commit()
    return owner.id, alice.id, bob.id


def owned(owner):
    return ScopedSession(bind=get_engine(), scope=DataScope(owner, execution=True), expire_on_commit=False)


def enqueue(owner, *, executor="fake", gpu="none"):
    with owned(owner) as session:
        task = create_task(
            session, title="Synthetic private task", prompt="Private intent", capability="system.self_test"
        )
        run = create_run(
            session,
            task,
            run_type="test",
            capability="system.self_test",
            executor_type=executor,
            execution_target="container",
            requested_gpu=gpu,
        )
        session.commit()
        return run.id


def test_actual_worker_uses_run_owner_for_primary_and_secondary_sessions(users):
    admin, alice, bob = users
    ids = [enqueue(admin), enqueue(alice), enqueue(bob)]
    for owner in (admin, alice, bob):
        with owned(owner) as session:
            session.add(MemoryEntry(scope="global", content=owner + " private memory"))
            session.commit()

    class Probe:
        def execute(self, session, run):
            assert isinstance(session, ScopedSession) and session.scope.user_id == run.owner_id
            assert not session.scope.inspect_all and not session.scope.administrator
            assert [row.content for row in session.scalars(select(MemoryEntry))] == [
                run.owner_id + " private memory"
            ]
            session.commit()
            with session_factory()() as secondary:
                assert isinstance(secondary, ScopedSession) and secondary.scope.user_id == run.owner_id
                assert secondary.get(Run, next(identity for identity in ids if identity != run.id)) is None
            transition(session, run, "preparing", event_type="test.preparing")
            transition(session, run, "running", event_type="test.started")
            transition(session, run, "succeeded", event_type="test.completed")

    with control_session_factory()() as queue:
        for identity in ids:
            assert tick(queue, "account-worker", executors={"fake": Probe()}) == identity
            assert queue.get(Run, identity).status == "succeeded"
            queue.commit()


def test_disabled_account_is_not_dispatched_and_host_credentials_are_admin_only(session, users):
    from app.models import User

    _, alice, _ = users
    disabled = enqueue(alice)
    session.get(User, alice).enabled = False
    session.commit()
    touched = []

    class MustNotRun:
        def execute(self, *args):
            touched.append(True)

    assert tick(session, "account-worker", executors={"fake": MustNotRun()}) == disabled
    assert session.get(Run, disabled).status == "failed" and not touched
    session.get(User, alice).enabled = True
    session.commit()
    restricted = enqueue(alice, executor="codex_proposal")
    assert tick(session, "account-worker", executors={"codex_proposal": MustNotRun()}) == restricted
    assert session.get(Run, restricted).error_type == "AccountPermissionDenied" and not touched


def test_gpu_and_ram_are_shared_but_reservation_records_and_release_are_private(users):
    _, alice, bob = users
    first, second = enqueue(alice, gpu="auto"), enqueue(bob, gpu="auto")
    with owned(alice) as session:
        run = session.get(Run, first)
        assert reserve_gpu(session, run, [3, 7]) == "3"
        assert reserve_memory(session, run, 16384, 4096)
        session.commit()
    with owned(bob) as session:
        run = session.get(Run, second)
        assert active_locks(session) == {"gpu:3"}
        assert session.scalars(select(ResourceLock)).all() == []
        assert memory_observation(session, run, 16384, 4096)["reserved_mib"] == 4096
        assert reserve_gpu(session, run, [3, 7]) == "7"
        release_run_locks(session, first)
        session.commit()
    with owned(alice) as session:
        assert len(list(session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))))) == 2
        release_run_locks(session, first)
        session.commit()


def test_owned_scheduler_freezes_the_agent_owner_and_disabled_accounts_do_not_launch(session, users):
    from app.db import utcnow
    from app.models import Agent, User
    from app.schedule import scheduler_tick

    _, alice, bob = users
    agents = []
    for owner in (alice, bob):
        with owned(owner) as current:
            agent = Agent(
                name="Scheduled private agent",
                goal="Synthetic report",
                model="fake-local",
                provider="local-openai-compatible",
                permission_profile="agent_local",
                execution_target="container",
                trigger="interval",
                interval_seconds=300,
                next_run_at=utcnow() - timedelta(seconds=1),
                enabled=True,
            )
            current.add(agent)
            current.commit()
            agents.append(agent.id)
    session.get(User, bob).enabled = False
    session.commit()
    created = scheduler_tick(session)
    session.commit()
    assert len(created) == 1
    run = session.get(Run, created[0])
    assert run.owner_id == run.task.owner_id == alice and run.agent_id == agents[0]
    assert not session.get(Agent, agents[1]).enabled
    assert scheduler_tick(session) == []


def test_account_policy_change_stops_only_that_accounts_authority(session, users):
    from app.accounts import update_user
    from app.models import Agent

    admin, alice, bob = users
    grant = login(session, "Owner", "synthetic owner password")
    session.commit()
    first, second = enqueue(alice), enqueue(bob)
    with owned(alice) as current:
        agent = Agent(name="Pause on disable", enabled=True)
        current.add(agent)
        current.commit()
        agent_id = agent.id
    update_user(session, grant.principal, alice, enabled=False, is_admin=False)
    session.commit()
    assert session.get(Run, first).status == "canceled"
    assert session.get(Run, second).status == "queued"
    assert not session.get(Agent, agent_id).enabled
    assert session.get(Run, second).owner_id == bob
