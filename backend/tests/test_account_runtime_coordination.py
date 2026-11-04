"""Shared model activity guards do not grant access to foreign private Runs."""

import pytest
from app.data_access import DataAccessError, DataScope, ScopedSession, data_session_for_run
from app.db import control_session_factory, get_engine
from app.engine import tick
from app.llama import enqueue_stop, evict_idle_models, prepare_consumer
from app.local_provider import LocalChatProvider
from app.models import ResourceLock, Run, RuntimeInstance
from app.resources import active_locks
from app.runtime_coordination import release_runtime_allocation
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_llama import managed as managed


def runtime(owner, model):
    response = owner.post("/api/llama/load", json={"model_file_id": model, "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    with control_session_factory()() as queue:
        tick(queue, "shared-model-fixture")
        run = queue.get(Run, response.json()["id"])
        assert run.status == "succeeded", run.error_message
        instance = queue.get(RuntimeInstance, run.parameters["instance_id"])
        return instance.id, instance.endpoint


def active(browser, instance_id, endpoint, *, operation=False):
    response = browser.post("/api/testing/runs", json={"title": "Synthetic private consumer marker"})
    assert response.status_code == 202
    with control_session_factory()() as queue:
        row = queue.get(Run, response.json()["id"])
        row.parameters = {"instance_id": instance_id} if operation else {"endpoint": endpoint}
        if operation:
            row.executor_type = "llama_health"
        queue.commit()
        return row.id


def test_another_accounts_consumer_blocks_stop_restart_and_automatic_eviction(accounts, managed):
    owner, alice, _ = accounts
    instance_id, endpoint = runtime(owner, managed[0])
    foreign_id = active(alice, instance_id, endpoint)
    for action in ("stop", "restart"):
        response = owner.post(f"/api/llama/{instance_id}/{action}", json={})
        assert response.status_code == 409, response.text
        assert foreign_id not in response.text and "Synthetic private" not in response.text
    assert owner.get("/api/runs/" + foreign_id).status_code == 404
    own = owner.post("/api/testing/runs", json={"title": "Synthetic GPU requester"}).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, own).owner_id
    with data_session_for_run(own, owner_id) as session:
        evict_idle_models(session, session.get(Run, own), [2, 7], desired={2})
        session.commit()
    with control_session_factory()() as queue:
        assert not list(queue.scalars(select(Run).where(Run.executor_type == "llama_stop")))
        assert queue.get(RuntimeInstance, instance_id).status == "ready"
    assert managed[1][instance_id]["status"] == "ready"


def test_another_accounts_operation_is_only_a_busy_fact_and_never_a_foreign_run_lookup(accounts, managed):
    owner, alice, _ = accounts
    instance_id, endpoint = runtime(owner, managed[0])
    foreign_id = active(alice, instance_id, endpoint, operation=True)
    response = owner.post(f"/api/llama/{instance_id}/health", json={})
    assert response.status_code == 409 and foreign_id not in response.text
    assert owner.get("/api/runs/" + foreign_id).status_code == 404
    assert alice.get("/api/runs/" + foreign_id).status_code == 200
    with control_session_factory()() as queue:
        queue.get(Run, foreign_id).status = "succeeded"
        queue.commit()
    response = owner.post(f"/api/llama/{instance_id}/health", json={})
    assert response.status_code == 202, response.text


def test_a_ready_model_serves_another_accounts_chat_without_exposing_private_load_or_messages(
    accounts, managed, monkeypatch
):
    owner, alice, bob = accounts
    instance_id, endpoint = runtime(owner, managed[0])
    with control_session_factory()() as queue:
        loader = queue.get(RuntimeInstance, instance_id).metadata_json["load_run_id"]
    catalog = alice.get("/api/llama")
    assert catalog.status_code == 200 and loader not in catalog.text
    assert alice.get("/api/runs/" + loader).status_code == 404
    seen = []

    async def reply(self, **kwargs):
        seen.append(kwargs["messages"])
        yield "Synthetic private Alice response"

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    response = alice.post(
        "/api/chat/conversations", json={"model": "llamacpp:" + managed[0], "execution_mode": "chat"}
    )
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    response = alice.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Synthetic private Alice question", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with control_session_factory()() as queue:
        tick(queue, "shared-model-chat-fixture")
    result = alice.get("/api/runs/" + run_id).json()
    assert result["status"] == "succeeded", result
    assert "Synthetic private Alice response" in alice.get("/api/chat/conversations/" + cid).text
    assert owner.get("/api/chat/conversations/" + cid).status_code == 404
    assert bob.get("/api/runs/" + run_id).status_code == 404
    assert len(seen) == 1 and any("Synthetic private Alice question" in msg["content"] for msg in seen[0])
    assert managed[1][instance_id]["status"] == "ready"


def test_shared_health_and_catalog_do_not_export_server_error_logs_or_foreign_provenance(accounts, managed):
    owner, alice, _ = accounts
    instance_id, _ = runtime(owner, managed[0])
    with control_session_factory()() as queue:
        loader = queue.get(RuntimeInstance, instance_id).metadata_json["load_run_id"]
    managed[1][instance_id]["error"] = "Synthetic private server-log marker from another conversation"
    response = alice.post(f"/api/llama/{instance_id}/health", json={})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with control_session_factory()() as queue:
        tick(queue, "shared-model-health-fixture")
    for path in ("/api/llama", "/api/runs/" + run_id, "/api/runs/" + run_id + "/events"):
        response = alice.get(path)
        assert response.status_code == 200
        assert "Synthetic private server-log marker" not in response.text and loader not in response.text
    for artifact in alice.get("/api/artifacts", params={"run_id": run_id}).json():
        response = alice.get("/api/artifacts/" + artifact["id"] + "/file")
        assert "Synthetic private server-log marker" not in response.text


def test_member_first_send_prepares_shared_model_and_keeps_producer_private(accounts, managed, monkeypatch):
    owner, alice, bob = accounts

    async def reply(self, **kwargs):
        yield "Synthetic automatically prepared private answer"

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    conversation = alice.post(
        "/api/chat/conversations", json={"model": "llamacpp:" + managed[0], "execution_mode": "chat"}
    )
    assert conversation.status_code == 201, conversation.text
    response = alice.post(
        f"/api/chat/conversations/{conversation.json()['id']}/messages",
        json={"content": "Synthetic first question", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    chat_id = response.json()["id"]
    with control_session_factory()() as queue:
        loader = queue.scalar(select(Run).where(Run.executor_type == "llama_load"))
        assert loader.owner_id == queue.get(Run, chat_id).owner_id
        loader_id = loader.id
        assert not managed[1]
        tick(queue, "member-first-load")
        tick(queue, "member-first-answer")
    result = alice.get("/api/runs/" + chat_id).json()
    assert result["status"] == "succeeded", result
    assert len(managed[1]) == 1
    for browser in (owner, bob):
        assert browser.get("/api/runs/" + loader_id).status_code == 404
        assert loader_id not in browser.get("/api/llama").text


def test_member_cannot_create_or_modify_shared_runtime_outside_typed_load_intent(accounts, managed):
    _, alice, _ = accounts
    marker = alice.post("/api/testing/runs", json={"title": "Synthetic own identity"}).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, marker).owner_id
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id)) as session:
        session.add(RuntimeInstance(runtime_key="llama.cpp", name="Forged shared model", ownership="managed"))
        with pytest.raises(DataAccessError):
            session.flush()
        session.rollback()
    response = alice.post("/api/llama/load", json={"model_file_id": managed[0], "gpus": [2, 7]})
    assert response.status_code == 202, response.text
    instance_id = response.json()["parameters"]["instance_id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id)) as session:
        session.get(RuntimeInstance, instance_id).endpoint = "http://unreviewed.invalid"
        with pytest.raises(DataAccessError):
            session.flush()


def test_admin_stop_releases_only_the_foreign_models_confirmed_physical_allocation(accounts, managed):
    owner, alice, bob = accounts
    instance_id, _ = runtime(alice, managed[0])
    unrelated = bob.post("/api/testing/runs", json={"title": "Synthetic independent reservation"}).json()[
        "id"
    ]
    with control_session_factory()() as queue:
        loader = queue.get(RuntimeInstance, instance_id).metadata_json["load_run_id"]
        load = queue.get(Run, loader)
        original = (load.status, load.parameters, load.metadata_json, load.error_message)
        queue.add(ResourceLock(run_id=loader, resource_key="ram:" + loader))
        queue.add(ResourceLock(run_id=unrelated, resource_key="gpu:42"))
        queue.commit()
    # Do not execute the unrelated synthetic Run before the stop fixture.
    with control_session_factory()() as queue:
        queue.get(Run, unrelated).status = "succeeded"
        queue.commit()
    assert alice.post(f"/api/llama/{instance_id}/stop").status_code == 403
    response = owner.post(f"/api/llama/{instance_id}/stop")
    assert response.status_code == 202, response.text
    stop_id = response.json()["id"]
    assert loader not in response.text
    with control_session_factory()() as queue:
        assert tick(queue, "admin-stops-shared-model") == stop_id
        assert queue.get(Run, stop_id).status == "succeeded"
        assert active_locks(queue) == {"gpu:42"}
        assert not list(
            queue.scalars(
                select(ResourceLock).where(ResourceLock.run_id == loader, ResourceLock.released_at.is_(None))
            )
        )
        load = queue.get(Run, loader)
        assert (load.status, load.parameters, load.metadata_json, load.error_message) == original
    assert owner.get("/api/runs/" + loader).status_code == 404


def test_missing_or_live_observation_cannot_release_another_accounts_model(accounts, managed):
    owner, alice, _ = accounts
    instance_id, _ = runtime(owner, managed[0])
    marker = alice.post("/api/testing/runs", json={"title": "Synthetic own coordination scope"}).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, marker).owner_id
    with data_session_for_run(marker, owner_id) as session:
        instance = session.get(RuntimeInstance, instance_id)
        for observation in (
            {"status": "stopped"},
            {"status": "stopped", "alive": True},
            {"status": "ready", "alive": False},
        ):
            release_runtime_allocation(session, instance, observation)
        session.commit()
        assert active_locks(session) == {"gpu:2", "gpu:7"}


def test_stop_intent_cannot_change_other_shared_runtime_fields(accounts, managed):
    owner, alice, _ = accounts
    instance_id, _ = runtime(owner, managed[0])
    marker = alice.post("/api/testing/runs", json={"title": "Synthetic own coordination scope"}).json()["id"]
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, marker).owner_id
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id)) as session:
        instance = session.get(RuntimeInstance, instance_id)
        enqueue_stop(session, instance)
        instance.endpoint = "http://unreviewed.invalid"
        with pytest.raises(DataAccessError):
            session.flush()


def test_member_context_preparation_can_replace_idle_foreign_model_without_foreign_dependencies(
    accounts, managed, monkeypatch
):
    owner, alice, _ = accounts
    previous_id, _ = runtime(owner, managed[0])
    marker = alice.post("/api/testing/runs", json={"title": "Synthetic local code preparation"}).json()["id"]
    monkeypatch.setattr("app.llama.coding_context_target", lambda *args, **kwargs: 100352)
    with control_session_factory()() as queue:
        owner_id = queue.get(Run, marker).owner_id
        producer = queue.get(RuntimeInstance, previous_id).metadata_json["load_run_id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner_id)) as session:
        consumer = session.get(Run, marker)
        consumer.executor_type = "local_proposal"
        consumer.parameters = {"model": "llamacpp:" + managed[0]}
        prepare_consumer(session, consumer)
        session.commit()
        stops = list(session.scalars(select(Run).where(Run.executor_type == "llama_stop")))
        loads = list(session.scalars(select(Run).where(Run.executor_type == "llama_load")))
        assert len(stops) == len(loads) == 1
        assert stops[0].parameters["instance_id"] == previous_id
        assert loads[0].parameters["context_size"] == 100352
        assert loads[0].parameters["cache_type"] == "q8_0"
        assert session.get(RuntimeInstance, previous_id).status == "stopping"
        assert session.get(Run, producer) is None
    assert producer not in alice.get("/api/runs/" + marker + "/events").text
