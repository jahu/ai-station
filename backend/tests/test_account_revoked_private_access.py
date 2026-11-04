"""A vanished worker must still clean owned native work after account revocation."""

from datetime import timedelta

import pytest
from app.accounts import update_user
from app.data_access import DataAccessError, data_session_for
from app.db import control_session_factory, utcnow
from app.models import ResourceLock, Run, RunEvent, Setting
from app.private_ui_state import KEY
from app.revoked_private_access import cleanup_revoked_private_access
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import claim_next, transition
from app.state import RunStatus
from sqlalchemy import select
from test_account_private_access import enqueue, principal, second_admin, work
from test_account_private_access import native as native
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def dispatched_operation(owner):
    response = enqueue(owner, "login")
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    with control_session_factory()() as queue:
        run = claim_next(queue, "vanished-private-worker")
        assert run.id == identity
        transition(queue, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(queue, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        queue.commit()
    return identity


def revoke(owner, other, identity, reason):
    subject, administrator = principal(owner), principal(other)
    with control_session_factory()() as auth:
        update_user(
            auth,
            administrator,
            subject.user_id,
            enabled=reason != "disabled",
            is_admin=reason != "role",
        )
        auth.get(Run, identity).lease_expires_at = utcnow() - timedelta(seconds=1)
        auth.commit()


@pytest.mark.parametrize("reason", ["disabled", "role"])
def test_revoked_account_recovery_cancels_owned_native_action_instead_of_failing_it(
    accounts, private_app, native, reason
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    identity = dispatched_operation(owner)
    revoke(owner, other, identity, reason)
    assert native[0] == []  # The account HTTP/service path does not execute native work.
    assert work() == identity
    assert [call[1] for call in native[0]] == ["/v1/private-access/cancel"]
    assert native[0][0][2]["run_id"] == identity
    assert other.get("/api/runs/" + identity).status_code == 404
    with control_session_factory()() as queue:
        run = queue.get(Run, identity)
        assert run.status == "canceled" and run.metadata_json["process_confirmed_gone"]


@pytest.mark.parametrize(
    "observation", ["pending", "unavailable", "wrong_identity", "malformed", "invalid_json"]
)
def test_unconfirmed_cleanup_retains_owned_reservations_and_retries_only_cancellation(
    accounts, private_app, native, monkeypatch, observation
):
    owner, alice, _ = accounts
    other = second_admin(owner, private_app)
    identity = dispatched_operation(owner)
    foreign = alice.post("/api/testing/runs", json={"title": "Unrelated private work"}).json()["id"]
    with control_session_factory()() as queue:
        unrelated = queue.get(Run, foreign)
        unrelated.status = "running"
        unrelated.worker_id = "other-worker"
        unrelated.lease_expires_at = utcnow() + timedelta(minutes=5)
        queue.add_all(
            [
                ResourceLock(resource_key="gpu:93", run_id=identity),
                ResourceLock(resource_key="gpu:94", run_id=foreign),
            ]
        )
        before = dict(queue.get(Setting, KEY).value)
        queue.commit()
    revoke(owner, other, identity, "disabled")
    original = RunnerClient.request

    def uncertain(_client, method, path, json=None):
        native[0].append((method, path, json))
        if observation == "unavailable":
            raise RunnerUnavailable("https://login.tailscale.com/a/PRIVATE-DO-NOT-LOG")
        if observation == "invalid_json":
            raise ValueError("Invalid native JSON: PRIVATE-DO-NOT-LOG")
        return {
            "phase": []
            if observation == "malformed"
            else "running"
            if observation == "pending"
            else "canceled",
            "process_confirmed_gone": observation in {"wrong_identity", "malformed"},
            **({"run_id": foreign} if observation == "wrong_identity" else {}),
        }

    monkeypatch.setattr(RunnerClient, "request", uncertain)
    assert work() == identity
    with control_session_factory()() as queue:
        run = queue.get(Run, identity)
        assert run.status == "cancel_requested" and run.lease_expires_at > utcnow()
        assert run.metadata_json["cleanup_requires_inspection"]
        assert all(lock.released_at is None for lock in queue.scalars(select(ResourceLock)))
        assert queue.get(Run, foreign).status == "running"
        assert queue.get(Setting, KEY).value == before
        assert "PRIVATE-DO-NOT-LOG" not in str([row.payload for row in queue.scalars(select(RunEvent))])
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        queue.commit()
    monkeypatch.setattr(RunnerClient, "request", original)
    assert work() == identity
    assert all(call[1] == "/v1/private-access/cancel" and call[2]["run_id"] == identity for call in native[0])
    with control_session_factory()() as queue:
        assert queue.get(Run, identity).status == "canceled"
        locks = {lock.run_id: lock.released_at for lock in queue.scalars(select(ResourceLock))}
        assert locks[identity] is not None and locks[foreign] is None
        assert queue.get(Run, foreign).status == "running"
        assert queue.get(Setting, KEY).value == before


def test_cleanup_cannot_publish_after_another_worker_acquires_the_operation(
    accounts, private_app, native, monkeypatch
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    identity = dispatched_operation(owner)
    revoke(owner, other, identity, "disabled")
    original = RunnerClient.request

    def replaced(client, method, path, json=None):
        with control_session_factory()() as queue:
            queue.get(Run, identity).worker_id = "replacement-worker"
            queue.commit()
        return original(client, method, path, json)

    monkeypatch.setattr(RunnerClient, "request", replaced)
    assert work() == identity
    with control_session_factory()() as queue:
        run = queue.get(Run, identity)
        assert run.worker_id == "replacement-worker" and run.status == "cancel_requested"
        assert not run.metadata_json.get("process_confirmed_gone")


@pytest.mark.parametrize("inspect_all", [False, True])
def test_owner_and_inspection_sessions_cannot_borrow_revoked_worker_cleanup(accounts, native, inspect_all):
    owner, _, _ = accounts
    identity = dispatched_operation(owner)
    with data_session_for(principal(owner), inspect_all=inspect_all) as session:
        with pytest.raises(DataAccessError):
            cleanup_revoked_private_access(session, session.get(Run, identity), "vanished-private-worker")
    assert native[0] == []


def test_unknown_operation_identity_requires_inspection_without_native_calls_or_lock_release(
    accounts, private_app, native
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    identity = dispatched_operation(owner)
    with control_session_factory()() as queue:
        queue.get(Run, identity).task.intent = "unexpected.action"
        queue.add(ResourceLock(resource_key="gpu:93", run_id=identity))
        queue.commit()
    revoke(owner, other, identity, "disabled")
    assert work() == identity
    assert native[0] == []
    with control_session_factory()() as queue:
        run = queue.get(Run, identity)
        assert run.status == "interrupted" and run.metadata_json["cleanup_requires_inspection"]
        assert queue.scalar(select(ResourceLock)).released_at is None


@pytest.mark.parametrize("boundary", ["before_owner_factory", "after_owner_factory"])
def test_revocation_racing_owner_session_opening_still_cancels_owned_action(
    accounts, private_app, native, monkeypatch, boundary
):
    from app import data_access

    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    actor, administrator = principal(owner), principal(other)
    identity = dispatched_operation(owner)
    with control_session_factory()() as queue:
        queue.get(Run, identity).lease_expires_at = utcnow() - timedelta(seconds=1)
        queue.commit()
    original = data_access.data_session_for_run

    def racing(run_id, owner_id):
        session = original(run_id, owner_id) if boundary == "after_owner_factory" else None
        with control_session_factory()() as auth:
            update_user(
                auth,
                administrator,
                actor.user_id,
                enabled=boundary != "before_owner_factory",
                is_admin=False,
            )
            auth.commit()
        return session if session is not None else original(run_id, owner_id)

    monkeypatch.setattr(data_access, "data_session_for_run", racing)
    assert work() == identity
    assert [call[1] for call in native[0]] == ["/v1/private-access/cancel"]
    with control_session_factory()() as queue:
        assert queue.get(Run, identity).status == "canceled"
