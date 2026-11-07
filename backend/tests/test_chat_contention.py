"""Real writer contention must not replay inference or lose delivered stream batches."""

import asyncio
import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from app import run_checkpoint
from app.db import control_session_factory, get_engine, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from sqlalchemy import event
from test_account_private_api import accounts, private_app  # noqa: F401


def enqueue(alice, monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    conversation = alice.post("/api/chat/conversations", json={"model": "fixture-model"}).json()["id"]
    response = alice.post(
        f"/api/chat/conversations/{conversation}/messages",
        json={
            "content": "Synthetic private streaming test",
            "web_search": {"enabled": False},
        },
    )
    assert response.status_code == 202, response.text
    return conversation, response.json()["id"]


@pytest.mark.parametrize("provider_pause", [0, 0.35])
def test_real_busy_writer_preserves_single_provider_and_exactly_once_deltas(
    accounts,  # noqa: F811
    monkeypatch,
    provider_pause,
):
    _, alice, bob = accounts
    conversation, run_id = enqueue(alice, monkeypatch)
    ready = threading.Event()
    errors, busy, calls, closed = [], [], [], []
    engine = get_engine()
    original_busy = run_checkpoint.sqlite_busy

    def short_timeout(connection, *_):
        connection.execute("PRAGMA busy_timeout=10")

    def writer():
        try:
            with sqlite3.connect(engine.url.database, timeout=1) as db:
                db.execute("BEGIN IMMEDIATE")
                ready.set()
                time.sleep(0.55)
                db.commit()
        except Exception as exc:
            errors.append(exc)
            ready.set()

    thread = threading.Thread(target=writer)

    def checked_busy(exc):
        result = original_busy(exc)
        if result:
            busy.append(True)
        return result

    async def stream(self, **params):
        calls.append(params)
        try:
            yield "Durable. "
            thread.start()
            assert ready.wait(2)
            await asyncio.sleep(provider_pause)
            yield "Received during contention. "
            yield "Finished."
        finally:
            closed.append(True)

    event.listen(engine, "checkout", short_timeout)
    monkeypatch.setattr(run_checkpoint, "sqlite_busy", checked_busy)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    try:
        with control_session_factory()() as queue:
            assert tick(queue, "contended-stream-owner") == run_id
    finally:
        thread.join(3)
        event.remove(engine, "checkout", short_timeout)
    assert not errors and busy and len(calls) == 1 and closed == [True]
    answer = alice.get(f"/api/chat/conversations/{conversation}").json()["messages"][-1]
    expected = "Durable. Received during contention. Finished."
    assert answer["content"] == expected and answer["metadata"]["partial"] is False
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
    events = alice.get(f"/api/runs/{run_id}/events").json()
    assert "".join(e["payload"]["text"] for e in events if e["event_type"] == "chat.delta") == expected
    assert bob.get(f"/api/runs/{run_id}/events").status_code == 404


@pytest.mark.parametrize("replacement", ["interrupted", "new_claim"])
def test_lost_stream_claim_cannot_append_or_overwrite_recovery(accounts, monkeypatch, replacement):  # noqa: F811
    _, alice, _ = accounts
    conversation, run_id = enqueue(alice, monkeypatch)
    closed = []

    async def stream(self, **params):
        try:
            yield "Preserved before recovery."
            with control_session_factory()() as other:
                run = other.get(Run, run_id)
                if replacement == "interrupted":
                    run.status = "interrupted"
                    run.error_type = "Interrupted"
                    run.error_message = "Recovery already recorded the failure"
                else:
                    run.worker_id = "replacement-worker"
                    run.claimed_at = utcnow() + timedelta(seconds=1)
                other.commit()
            yield "This stale stream has no write authority."
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with control_session_factory()() as queue:
        assert tick(queue, "original-stream-worker") == run_id
    answer = alice.get(f"/api/chat/conversations/{conversation}").json()["messages"][-1]
    assert answer["content"] == "Preserved before recovery." and answer["metadata"]["partial"] is True
    run = alice.get(f"/api/runs/{run_id}").json()
    if replacement == "interrupted":
        assert (
            run["status"] == "interrupted" and run["error_message"] == "Recovery already recorded the failure"
        )
    else:
        assert run["status"] == "running" and run["worker_id"] == "replacement-worker"
    assert closed == [True]
