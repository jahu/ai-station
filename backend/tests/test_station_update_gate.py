from datetime import timedelta

import pytest
from app import station_update_gate as gate
from app.db import control_session_factory, utcnow
from app.models import Run, User
from app.runs import claim_next, create_run, create_task, transition
from app.state import RunStatus
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def updating(accounts):
    owner = accounts[0]
    identity = owner.post("/api/maintenance/updates/checks", json={}).json()["id"]
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        row.executor_type = gate.EXECUTOR
        row.capability = "station.updates.install"
        row.execution_target = "host"
        row.parameters = {
            "release_id": 123,
            "fingerprint": "a" * 64,
            "current_version": "0.4.0",
            "platform": "linux-amd64",
        }
        row.status = "running"
        row.worker_id = "update-owner"
        row.claimed_at = utcnow()
        row.lease_expires_at = utcnow() + timedelta(minutes=2)
        claim = row.worker_id, row.claimed_at
        session.commit()
    return identity, claim


def job(session):
    task = create_task(session, title="Preserved queued work", prompt="example", capability="test")
    run = create_run(
        session, task, run_type="test", capability="test", executor_type="fake", execution_target="container"
    )
    session.commit()
    return run.id


def test_gate_keeps_queued_work_and_blocks_dispatch_until_matching_release(accounts):
    identity, claim = updating(accounts)
    with control_session_factory()() as session:
        waiting = job(session)
    value = gate.take(identity, claim)
    assert value and value["run_id"] == identity
    assert gate.take(identity, claim) == value
    with control_session_factory()() as session:
        assert claim_next(session, "other-worker") is None
        assert session.get(Run, waiting).status == "queued"
    with pytest.raises(ValueError, match="identity does not match"):
        gate.release("foreign", value)
    gate.release(identity, value)
    with control_session_factory()() as session:
        assert claim_next(session, "other-worker").id == waiting


def test_busy_jobs_finish_without_stop_before_maintenance_is_admitted(accounts):
    identity, claim = updating(accounts)
    with control_session_factory()() as session:
        job(session)
        busy = claim_next(session, "owned-job")
        busy_id = busy.id
        session.commit()
    assert gate.take(identity, claim) is None
    with control_session_factory()() as session:
        row = session.get(Run, busy_id)
        assert row.status == "claimed"
        transition(session, row, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, row, RunStatus.RUNNING, event_type="run.started")
        transition(session, row, RunStatus.SUCCEEDED, event_type="run.completed")
        session.commit()
    assert gate.take(identity, claim)


@pytest.mark.parametrize(
    "mutation", ["demoted", "disabled", "claim", "expired", "agent", "permissions", "url"]
)
def test_untrusted_update_cannot_freeze_workstation(accounts, mutation):
    identity, claim = updating(accounts)
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        if mutation == "demoted":
            session.get(User, run.owner_id).is_admin = False
        elif mutation == "disabled":
            session.get(User, run.owner_id).enabled = False
        elif mutation == "claim":
            run.worker_id = "another-worker"
        elif mutation == "expired":
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
        elif mutation == "agent":
            run.conversation_id = "forged-context"
        elif mutation == "permissions":
            run.effective_permissions = ["network_read"]
        else:
            run.parameters = {**run.parameters, "url": "https://other.example"}
        # Testing the admission boundary rather than a foreign-key violation.
        if mutation == "agent":
            run.parent_run_id = run.id
            run.conversation_id = None
        session.commit()
        waiting = job(session)
    with pytest.raises(ValueError):
        gate.take(identity, claim)
    with control_session_factory()() as session:
        assert claim_next(session, "other-worker").id == waiting
