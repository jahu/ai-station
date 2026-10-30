"""Shared startup readiness never creates cross-account Run dependencies."""

from datetime import timedelta

import pytest
from app.data_access import data_session_for_run
from app.db import control_session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run, RuntimeInstance, Task
from app.recovery import recover_stale
from app.runner_client import RunnerClient
from app.task_control import cancel_task
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_llama import managed as managed


def pending_shared_chat(owner, alice, model):
    load = owner.post("/api/llama/load", json={"model_file_id": model, "gpus": [2, 7]})
    assert load.status_code == 202, load.text
    conversation = alice.post(
        "/api/chat/conversations", json={"model": "llamacpp:" + model, "execution_mode": "chat"}
    )
    assert conversation.status_code == 201, conversation.text
    response = alice.post(
        f"/api/chat/conversations/{conversation.json()['id']}/messages",
        json={"content": "Synthetic independent waiting question", "web_search": {"enabled": False}},
    )
    assert response.status_code == 202, response.text
    chat_id = response.json()["id"]
    with control_session_factory()() as queue:
        waiter = queue.scalar(select(Run).where(Run.executor_type == "llama_wait"))
        assert waiter is not None and waiter.owner_id == queue.get(Run, chat_id).owner_id
        assert waiter.owner_id != queue.get(Run, load.json()["id"]).owner_id
        return load.json()["id"], chat_id, waiter.id


def test_concurrent_accounts_share_pending_load_through_private_readiness_run(accounts, managed, monkeypatch):
    owner, alice, bob = accounts

    async def reply(self, **kwargs):
        yield "Synthetic answer after another account prepared the model"

    monkeypatch.setattr(LocalChatProvider, "stream", reply)
    loader, chat, waiter = pending_shared_chat(owner, alice, managed[0])
    assert not managed[1]
    for path in ("/api/runs/" + waiter, "/api/runs/" + chat, "/api/runs/" + chat + "/events"):
        response = alice.get(path)
        assert response.status_code == 200 and loader not in response.text
        assert owner.get(path).status_code == bob.get(path).status_code == 404
    with control_session_factory()() as queue:
        assert tick(queue, "shared-startup") == loader
        assert tick(queue, "private-readiness") == waiter
        assert tick(queue, "private-answer") == chat
    assert alice.get("/api/runs/" + chat).json()["status"] == "succeeded"
    assert len(managed[1]) == 1
    assert alice.get("/api/runs/" + loader).status_code == 404


@pytest.mark.parametrize("outcome", ["failed", "canceled", "source_changed"])
def test_foreign_startup_failure_or_replacement_fails_private_waiter_without_replay(
    accounts, managed, outcome
):
    owner, alice, _ = accounts
    loader, chat, waiter = pending_shared_chat(owner, alice, managed[0])
    with control_session_factory()() as queue:
        load = queue.get(Run, loader)
        instance = queue.get(RuntimeInstance, load.parameters["instance_id"])
        if outcome == "source_changed":
            load.parameters = {**load.parameters, "mtime": 999}
            load.status = "succeeded"
            instance.status = "ready"
        else:
            load.status = outcome
            instance.status = "failed" if outcome == "failed" else "stopped"
        load.error_message = "Synthetic private producer failure detail"
        queue.commit()
        assert tick(queue, "failed-startup-waiter") == waiter
        assert tick(queue, "failed-startup-consumer") == chat
    for identity in (waiter, chat):
        result = alice.get("/api/runs/" + identity)
        assert result.json()["status"] == "failed", result.text
        assert loader not in result.text and "private producer failure detail" not in result.text
    assert not managed[1]


def test_waiter_yields_worker_and_cancel_does_not_signal_foreign_startup(accounts, managed):
    owner, alice, bob = accounts
    loader, chat, waiter = pending_shared_chat(owner, alice, managed[0])
    with control_session_factory()() as queue:
        producer = queue.get(Run, loader)
        producer.status = "claimed"
        producer.lease_expires_at = utcnow() + timedelta(minutes=5)
        queue.commit()
        assert tick(queue, "observe-in-flight") == waiter
        row = queue.get(Run, waiter)
        assert row.status == "queued" and row.worker_id is None and row.lease_expires_at is None
        assert tick(queue, "waiter-backoff") is None
    independent = bob.post("/api/testing/runs", json={"title": "Synthetic unrelated task"})
    assert independent.status_code == 202, independent.text
    with control_session_factory()() as queue:
        assert tick(queue, "unrelated-ready-work") == independent.json()["id"]
    assert alice.post("/api/runs/" + waiter + "/cancel").status_code == 200
    with control_session_factory()() as queue:
        assert tick(queue, "canceled-wait-consumer") == chat
        assert queue.get(Run, loader).status == "claimed"
    assert not managed[1]
    assert owner.get("/api/runs/" + loader).json()["status"] == "claimed"


def test_stale_waiter_resumes_observation_without_host_inspection(accounts, managed, monkeypatch):
    owner, alice, _ = accounts
    loader, _, waiter = pending_shared_chat(owner, alice, managed[0])

    def forbidden(*args, **kwargs):
        raise AssertionError("A readiness waiter cannot inspect or cancel a foreign process")

    monkeypatch.setattr(RunnerClient, "inspect_process", forbidden)
    monkeypatch.setattr(RunnerClient, "cancel_process", forbidden)
    with control_session_factory()() as queue:
        row = queue.get(Run, waiter)
        row.status = "running"
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        queue.commit()
        assert recover_stale(queue) == [waiter]
        queue.commit()
        assert queue.get(Run, waiter).status == "queued"
        assert queue.get(Run, loader).status == "queued"


def test_waiter_deadline_fails_without_canceling_foreign_startup(accounts, managed):
    owner, alice, _ = accounts
    loader, _, waiter = pending_shared_chat(owner, alice, managed[0])
    with control_session_factory()() as queue:
        row = queue.get(Run, waiter)
        row.parameters = {
            **row.parameters,
            "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
        }
        queue.get(Run, loader).status = "running"
        queue.get(Run, loader).lease_expires_at = utcnow() + timedelta(minutes=1)
        queue.commit()
        assert tick(queue, "expired-private-wait") == waiter
        assert queue.get(Run, waiter).status in {"failed", "canceled"}
        assert queue.get(Run, loader).status == "running"
    assert not managed[1]


def test_stopping_original_task_retains_startup_needed_by_another_account(accounts, managed):
    owner, alice, _ = accounts
    loader, chat, waiter = pending_shared_chat(owner, alice, managed[0])
    with control_session_factory()() as queue:
        load = queue.get(Run, loader)
        owner_id, task_id = load.owner_id, load.task_id
    with data_session_for_run(loader, owner_id) as session:
        result = cancel_task(session, session.get(Task, task_id))
        assert result["retained_run_ids"] == [loader], result
        session.commit()
    with control_session_factory()() as queue:
        assert queue.get(Run, loader).status == "queued"
        assert queue.get(Run, chat).status == queue.get(Run, waiter).status == "queued"
    assert alice.get("/api/runs/" + loader).status_code == 404
