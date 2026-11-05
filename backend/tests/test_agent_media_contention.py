"""Real SQLite contention must not redispatch an in-flight text completion."""

import asyncio
import json
import sqlite3
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app import agent_media
from app.agent_media import AgentMediaExecutor, MediaClaimLost
from app.db import get_engine, session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Run, RunEvent, Task
from app.providers import ProviderError
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError


def running(session):
    task = Task(title="Neutral media stream")
    session.add(task)
    session.flush()
    run = Run(
        task_id=task.id,
        run_type="agent",
        capability="agent.media.prepare",
        executor_type="agent_media",
        execution_target="container",
        status="running",
        worker_id="stream-owner",
        claimed_at=utcnow(),
        parameters={
            "endpoint": "http://unused",
            "execution_deadline_at": (utcnow() + timedelta(seconds=10)).isoformat(),
        },
    )
    session.add(run)
    session.commit()
    return run


def definition():
    return SimpleNamespace(model="fake", media=SimpleNamespace(kind="image", vary_scenes=False))


@pytest.mark.parametrize("provider_pause", [0, 0.35])
def test_busy_database_keeps_single_provider_stream_and_exactly_once_deltas(
    session, monkeypatch, provider_pause
):
    run = running(session)
    engine = get_engine()
    ready = threading.Event()
    errors = []
    busy = []
    calls = []
    closed = []
    original_busy = agent_media.sqlite_busy

    def short_timeout(connection, *_):
        connection.execute("PRAGMA busy_timeout=10")

    event.listen(engine, "checkout", short_timeout)

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
            busy.append(type(exc.orig))
        return result

    async def stream(self, **kwargs):
        calls.append(kwargs)
        thread.start()
        assert ready.wait(2)
        try:
            await asyncio.sleep(provider_pause)
            yield '{"description":'
            yield '"A neutral wardrobe"}'
        finally:
            closed.append(True)

    monkeypatch.setattr(agent_media, "sqlite_busy", checked_busy)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    try:
        text = asyncio.run(AgentMediaExecutor().consume(session, run, definition(), []))
        assert json.loads(text) == {"description": "A neutral wardrobe"}
        assert len(calls) == 1 and closed == [True] and busy
        events = list(
            session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.sequence))
        )
        assert "".join(row.payload["text"] for row in events) == text
        assert [row.sequence for row in events] == [1, 2]
        assert run.status == "running"
    finally:
        if thread.ident is not None:
            thread.join(timeout=2)
        event.remove(engine, "checkout", short_timeout)
    assert not errors and not thread.is_alive()


@pytest.mark.parametrize("change", ["cancel", "claim"])
def test_stream_closes_without_writing_after_cancel_or_claim_change(session, monkeypatch, change):
    run = running(session)
    run_id = run.id
    closed = []

    async def stream(self, **kwargs):
        with session_factory()() as other:
            row = other.get(Run, run_id)
            if change == "cancel":
                row.status = "cancel_requested"
            else:
                row.worker_id = "new-owner"
            other.commit()
        try:
            yield '"not published"'
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    # Recheck ownership/cancellation before recording the token that just arrived.
    with pytest.raises(MediaClaimLost):
        asyncio.run(AgentMediaExecutor().consume(session, run, definition(), []))
    if change == "cancel":
        session.refresh(run)
        assert run.status == "canceled"
    assert closed == [True]
    assert (
        session.scalar(
            select(RunEvent.id).where(RunEvent.run_id == run_id, RunEvent.event_type == "agent.delta")
        )
        is None
    )


@pytest.mark.parametrize("busy", [False, True])
def test_database_retry_does_not_mask_other_errors_or_outlive_its_deadline(session, busy):
    run = running(session)
    calls = []

    def action():
        calls.append(True)
        if not busy:
            raise ValueError("Invalid observation")
        original = sqlite3.OperationalError("database is locked")
        original.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise OperationalError("BEGIN IMMEDIATE", {}, original)

    with pytest.raises(ProviderError if busy else ValueError):
        asyncio.run(
            AgentMediaExecutor().stream_database_step(
                session, run, (run.worker_id, run.claimed_at), utcnow() - timedelta(seconds=1), action
            )
        )
    assert calls == [True]
