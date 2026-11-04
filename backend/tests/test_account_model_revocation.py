"""Revocation must preserve physical model ownership and other accounts' demand."""

from datetime import timedelta

import pytest
from app.accounts import update_user
from app.data_access import data_session_for_run
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import ResourceLock, Run, RunEvent, RuntimeInstance, User
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import claim_next, transition
from app.state import RunStatus
from sqlalchemy import select
from test_account_private_access import principal, second_admin
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_runtime_wait import pending_shared_chat
from test_llama import managed as managed


def dispatched(loader, records):
    with control_session_factory()() as queue:
        run = claim_next(queue, "vanished-model-worker")
        assert run.id == loader
        transition(queue, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(queue, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        instance = queue.get(RuntimeInstance, run.parameters["instance_id"])
        instance.status = "loading"
        records[instance.id] = {"status": "loading", "alive": True, "gpus": [2, 7]}
        queue.add_all([ResourceLock(resource_key=f"gpu:{index}", run_id=run.id) for index in (2, 7)])
        queue.add(ResourceLock(resource_key="ram:" + run.id, run_id=run.id))
        queue.commit()
        return instance.id


def revoke(owner, other):
    subject, actor = principal(owner), principal(other)
    with control_session_factory()() as session:
        update_user(session, actor, subject.user_id, enabled=False, is_admin=True)
        session.commit()


def work():
    with control_session_factory()() as queue:
        return tick(queue, "revoked-model-worker")


def test_disabled_load_owner_is_cleaned_before_gpu_reservations_are_released(accounts, private_app, managed):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    response = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    loader = response.json()["id"]
    instance = dispatched(loader, managed[1])
    revoke(owner, other)
    assert work() == loader
    assert managed[1][instance]["alive"] is False
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "canceled"
        assert session.get(RuntimeInstance, instance).status == "stopped"
        assert all(row.released_at is not None for row in session.scalars(select(ResourceLock)))


def test_shared_model_finishes_readiness_for_another_account_after_initiator_is_disabled(
    accounts, private_app, managed, monkeypatch
):
    owner, alice, _ = accounts
    other = second_admin(owner, private_app)
    loader, chat, waiter = pending_shared_chat(owner, alice, managed[0])
    instance = dispatched(loader, managed[1])
    managed[1][instance].update(status="ready", n_ctx=131072)
    revoke(owner, other)

    async def reply(self, **kwargs):
        yield "Private answer from retained shared model"

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    assert work() == loader
    assert managed[1][instance]["alive"] is True
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "canceled"
        assert session.get(RuntimeInstance, instance).status == "ready"
        assert all(row.released_at is None for row in session.scalars(select(ResourceLock)))
    assert work() == waiter
    assert work() == chat
    answer = alice.get("/api/runs/" + chat)
    assert answer.json()["status"] == "succeeded" and loader not in answer.text
    assert alice.get("/api/runs/" + loader).status_code == 404
    assert loader not in alice.get("/api/llama").text
    from app.runtime_coordination import runtime_coding_facts

    with control_session_factory()() as session:
        user_id = session.get(Run, chat).owner_id
    with data_session_for_run(chat, user_id) as session:
        proof = runtime_coding_facts(session, session.get(RuntimeInstance, instance))
        assert proof["retained"] and proof["ready_observation"]["n_ctx"] == 131072


def expire(identity):
    with control_session_factory()() as session:
        session.get(Run, identity).lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()


@pytest.mark.parametrize("action", ["cancel", "revoke"])
def test_unstarted_owned_load_retires_without_a_stale_queued_instance(accounts, private_app, managed, action):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    response = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    loader = response.json()["id"]
    if action == "cancel":
        assert owner.post(f"/api/runs/{loader}/cancel").status_code == 200
    else:
        revoke(owner, other)
    assert not managed[1]
    with control_session_factory()() as session:
        run = session.get(Run, loader)
        assert run.status == "canceled" and run.metadata_json["process_confirmed_gone"]
        assert session.get(RuntimeInstance, run.parameters["instance_id"]).status == "stopped"
    fresh = other.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert fresh.status_code == 202 and fresh.json()["id"] != loader


@pytest.mark.parametrize("observation", ["unavailable", "wrong_identity", "stopping"])
def test_unknown_model_cleanup_never_releases_live_gpu_reservations(
    accounts, private_app, managed, monkeypatch, observation
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    loader = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]}).json()["id"]
    instance = dispatched(loader, managed[1])
    revoke(owner, other)
    inspect, stop = RunnerClient.inspect_llama, RunnerClient.stop_llama

    def uncertain(_client, iid):
        if observation == "unavailable":
            raise RunnerUnavailable("Synthetic private native log DO-NOT-LEAK")
        return {"status": "stopped", "alive": False, "instance_id": "another-instance"}

    if observation == "stopping":
        monkeypatch.setattr(RunnerClient, "stop_llama", lambda _, iid: {"status": "stopping", "alive": True})
    else:
        monkeypatch.setattr(RunnerClient, "inspect_llama", uncertain)
    assert work() == loader
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "cancel_requested"
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))
        assert "DO-NOT-LEAK" not in str([event.payload for event in session.scalars(select(RunEvent))])
    monkeypatch.setattr(RunnerClient, "inspect_llama", inspect)
    monkeypatch.setattr(RunnerClient, "stop_llama", stop)
    expire(loader)
    assert work() == loader
    assert managed[1][instance]["alive"] is False
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "canceled"
        assert all(lock.released_at is not None for lock in session.scalars(select(ResourceLock)))


def test_foreign_demand_keeps_loading_then_publishes_shared_readiness(accounts, private_app, managed):
    owner, alice, _ = accounts
    other = second_admin(owner, private_app)
    loader, _, _ = pending_shared_chat(owner, alice, managed[0])
    instance = dispatched(loader, managed[1])
    revoke(owner, other)
    assert work() == loader
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "cancel_requested"
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))
    managed[1][instance].update(status="ready", n_ctx=131072)
    expire(loader)
    assert work() == loader
    with control_session_factory()() as session:
        run = session.get(Run, loader)
        assert run.status == "canceled" and run.metadata_json["shared_model_retained"]
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))


def test_account_disable_during_native_start_preserves_another_accounts_model(
    accounts, private_app, managed, monkeypatch
):
    owner, alice, _ = accounts
    other = second_admin(owner, private_app)
    subject, actor = principal(owner), principal(other)
    loader, _, _ = pending_shared_chat(owner, alice, managed[0])
    original = RunnerClient.load_llama

    def revoke_during_load(client, body):
        result = original(client, body)
        result["n_ctx"] = 131072
        with control_session_factory()() as session:
            update_user(session, actor, subject.user_id, enabled=False, is_admin=True)
            session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "load_llama", revoke_during_load)
    assert work() == loader
    with control_session_factory()() as session:
        run = session.get(Run, loader)
        assert run.status == "canceled" and run.metadata_json["shared_model_retained"]
        assert session.get(RuntimeInstance, run.parameters["instance_id"]).status == "ready"
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))


def test_a_new_request_during_shutdown_waits_for_confirmed_gpu_release(
    accounts, private_app, managed, monkeypatch
):
    owner, alice, _ = accounts
    other = second_admin(owner, private_app)
    loader = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]}).json()["id"]
    dispatched(loader, managed[1])
    revoke(owner, other)
    original = RunnerClient.stop_llama
    chats = []

    def new_demand(client, iid):
        conversation = alice.post("/api/chat/conversations", json={"model": "llamacpp:" + managed[0]})
        sent = alice.post(
            f"/api/chat/conversations/{conversation.json()['id']}/messages",
            json={"content": "New private question", "web_search": {"enabled": False}},
        )
        assert sent.status_code == 202, sent.text
        chats.append(sent.json()["id"])
        return original(client, iid)

    async def reply(self, **kwargs):
        yield "New model after confirmed release"

    monkeypatch.setattr(RunnerClient, "stop_llama", new_demand)
    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    assert work() == loader
    for _ in range(3):
        assert work() is not None
    assert alice.get("/api/runs/" + chats[0]).json()["status"] == "succeeded"
    assert len(managed[1]) == 2


@pytest.mark.parametrize("observed", ["stopped", "stopping", "ready"])
def test_revoked_stop_observes_existing_work_without_reissuing_stop(
    accounts, private_app, managed, monkeypatch, observed
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    loaded = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert work() == loaded.json()["id"]
    with control_session_factory()() as session:
        instance = session.get(Run, loaded.json()["id"]).parameters["instance_id"]
    stopped = owner.post(f"/api/llama/{instance}/stop", json={})
    assert stopped.status_code == 202, stopped.text
    stop_id = stopped.json()["id"]
    with control_session_factory()() as session:
        run = claim_next(session, "old-stop-worker")
        assert run.id == stop_id
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        run.metadata_json = {"dispatch_attempted": True}
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    managed[1][instance].update(status=observed, alive=observed != "stopped")
    revoke(owner, other)
    monkeypatch.setattr(
        RunnerClient, "stop_llama", lambda *_: pytest.fail("Recovery cannot issue a new stop")
    )
    assert work() == stop_id
    with control_session_factory()() as session:
        run = session.get(Run, stop_id)
        assert (
            run.status
            == {"stopped": "canceled", "stopping": "cancel_requested", "ready": "interrupted"}[observed]
        )
        locks = list(session.scalars(select(ResourceLock)))
        assert all((row.released_at is not None) == (observed == "stopped") for row in locks)


def test_revoked_unknown_dispatched_work_keeps_reservations_for_inspection(accounts):
    owner, alice, _ = accounts
    response = alice.post("/api/testing/runs", json={"title": "Synthetic physical work"})
    identity = response.json()["id"]
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.executor_type = "unknown_owned_adapter"
        run.metadata_json = {"dispatch_attempted": True}
        session.get(User, run.owner_id).enabled = False
        session.add(ResourceLock(resource_key="gpu:93", run_id=identity))
        session.commit()
    assert work() == identity
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        assert run.status == "interrupted" and run.metadata_json["cleanup_requires_inspection"]
        assert session.scalar(select(ResourceLock)).released_at is None


def test_an_authorized_ordinary_accounts_internal_model_stop_is_not_treated_as_revoked(accounts, managed):
    from app.data_access import data_session_for
    from app.llama import enqueue_stop

    owner, alice, _ = accounts
    loaded = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert work() == loaded.json()["id"]
    with control_session_factory()() as session:
        instance_id = session.get(Run, loaded.json()["id"]).parameters["instance_id"]
    with data_session_for(principal(alice)) as session:
        stop = enqueue_stop(session, session.get(RuntimeInstance, instance_id))
        stop_id = stop.id
        session.commit()
    assert work() == stop_id
    assert managed[1][instance_id]["alive"] is False
    assert alice.get("/api/runs/" + stop_id).json()["status"] == "succeeded"
    assert owner.get("/api/runs/" + stop_id).status_code == 404


def test_changed_model_binding_during_inspection_cannot_stop_or_release_a_replacement(
    accounts, private_app, managed, monkeypatch
):
    owner, _, _ = accounts
    other = second_admin(owner, private_app)
    loader = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]}).json()["id"]
    instance_id = dispatched(loader, managed[1])
    revoke(owner, other)
    original = RunnerClient.inspect_llama

    def replace(client, iid):
        result = original(client, iid)
        with control_session_factory()() as session:
            instance = session.get(RuntimeInstance, instance_id)
            instance.metadata_json = {**instance.metadata_json, "gpus": [7]}
            session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "inspect_llama", replace)
    monkeypatch.setattr(
        RunnerClient, "stop_llama", lambda *_: pytest.fail("Replaced binding cannot authorize a stop")
    )
    assert work() == loader
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "interrupted"
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))


def test_missing_account_scope_cannot_read_shared_model_demand():
    from app.data_access import DataAccessError, ScopedSession
    from app.db import get_engine
    from app.model_cancellation import foreign_demand

    with ScopedSession(bind=get_engine(), scope=None) as session, pytest.raises(DataAccessError):
        foreign_demand(session, None, None)


@pytest.mark.parametrize("inspect_all", [False, True])
def test_http_and_inspection_scopes_cannot_borrow_model_recovery_or_publish_readiness(
    accounts, managed, inspect_all
):
    from app.data_access import DataAccessError, data_session_for
    from app.model_cancellation import cleanup_revoked_load, cleanup_revoked_stop, retain_ready

    owner, _, _ = accounts
    queued = owner.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    loader = queued.json()["id"]
    instance_id = dispatched(loader, managed[1])
    with data_session_for(principal(owner), inspect_all=inspect_all) as session:
        run, instance = session.get(Run, loader), session.get(RuntimeInstance, instance_id)
        for cleanup in (cleanup_revoked_load, cleanup_revoked_stop):
            with pytest.raises(DataAccessError):
                cleanup(session, run, "vanished-model-worker")
        with pytest.raises(DataAccessError):
            retain_ready(session, run, instance, {"status": "ready", "alive": True})
    with control_session_factory()() as session:
        assert session.get(Run, loader).status == "running"
        assert not session.get(Run, loader).metadata_json.get("shared_model_retained")
        assert all(lock.released_at is None for lock in session.scalars(select(ResourceLock)))
