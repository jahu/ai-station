"""SQLite contention before provider I/O cannot abandon a live model decision."""

import asyncio
import json
import sqlite3
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from app import assistant_decisions
from app.api import app
from app.db import get_engine, session_factory, utcnow
from app.models import Run
from app.runs import create_run, create_task, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import event, update
from test_assistant_controller import drain, root_state, submit
from test_assistant_react_workflow import action, react_model  # noqa: F401
from test_worker_database_busy import error


def decision(session):
    task = create_task(
        session,
        title="Decision preparation fixture",
        prompt="Explain a concept",
        capability="assistant.decide",
    )
    run = create_run(
        session,
        task,
        run_type="planning",
        capability="assistant.decide",
        executor_type="assistant_decision",
        execution_target="container",
        parameters={
            "endpoint": "llamacpp:" + str(uuid4()),
            "model": "fixture-model",
            "execution_deadline_at": (utcnow() + timedelta(minutes=2)).isoformat(),
        },
    )
    for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
        transition(session, run, state, event_type="qa.fixture")
    run.worker_id = "original-worker"
    session.commit()
    return run


def test_actual_sqlite_writer_contention_before_managed_binding_preserves_the_live_decision(monkeypatch):
    engine = get_engine()

    def short_timeout(connection, *args):
        connection.execute("PRAGMA busy_timeout=30")

    event.listen(engine, "checkout", short_timeout)
    held, release, failures = threading.Event(), threading.Event(), []
    calls, writes = [], []
    with session_factory()() as session:
        run = decision(session)
        rid = run.id

        def writer():
            try:
                with engine.connect() as connection:
                    with connection.begin():
                        connection.execute(update(Run).where(Run.id == rid).values(error_type=""))
                        held.set()
                        release.wait(0.25)
            except BaseException as exc:
                failures.append(exc)
                held.set()

        thread = threading.Thread(target=writer)
        thread.start()
        assert held.wait(2)

        def bind(db, params):
            # Preparation does perform registry reads. The model must not start
            # while a SQLite writer transaction remains on its request session.
            assert db.in_transaction()

            async def stream():
                assert not db.in_transaction()
                with session_factory()() as peer:
                    peer.execute(
                        update(Run)
                        .where(Run.id == rid)
                        .values(lease_expires_at=utcnow() + timedelta(seconds=45))
                    )
                    peer.commit()
                writes.append(True)
                calls.append(params)
                yield '{"answer":"ready"}'

            return stream()

        monkeypatch.setattr(assistant_decisions, "completion_stream", bind)
        try:
            result = asyncio.run(
                assistant_decisions.infer(
                    session,
                    run,
                    [{"role": "system", "content": "A bounded fixture"}, {"role": "user", "content": "{}"}],
                )
            )
            assert json.loads(result) == {"answer": "ready"}
            assert run.status == "running" and run.worker_id == "original-worker"
            assert len(calls) == len(writes) == 1 and not failures
        finally:
            release.set()
            thread.join(timeout=2)
            event.remove(engine, "checkout", short_timeout)
        assert not thread.is_alive()


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED])
def test_react_binding_retry_after_intent_does_not_replay_inference_or_tools(react_model, monkeypatch, code):  # noqa: F811
    react_model["immediate"] = [{"kind": "text", "description": "Explain the requested idea"}]
    react_model["actions"] = [action("chat_reply", instruction="Explain the idea")]
    original = assistant_decisions.completion_stream
    bindings = []

    def contended(db, params):
        if params.get("json_output") is False:
            bindings.append(True)
            if len(bindings) < 3:
                raise error(code)
        return original(db, params)

    monkeypatch.setattr(assistant_decisions, "completion_stream", contended)
    with TestClient(app) as client:
        queued = submit(client, "Explain how light refracts")
        drain()
        assert root_state(queued)["controller_outcome"] == "replied"
    assert len(bindings) == 3 and len(react_model["calls"]) == 3
    assert not react_model["actions"]


def test_cancellation_during_binding_backoff_prevents_provider_dispatch(monkeypatch):
    attempts = []
    with session_factory()() as session:
        run = decision(session)
        rid = run.id

        def bind(db, params):
            attempts.append(True)
            raise error(sqlite3.SQLITE_BUSY)

        async def stop_during_backoff(seconds):
            from app.runs import request_cancel

            with session_factory()() as peer:
                request_cancel(peer, peer.get(Run, rid))
                peer.commit()

        monkeypatch.setattr(assistant_decisions, "completion_stream", bind)
        monkeypatch.setattr(assistant_decisions.asyncio, "sleep", stop_during_backoff)
        with pytest.raises(assistant_decisions.DecisionStopped):
            asyncio.run(
                assistant_decisions.infer(
                    session,
                    run,
                    [{"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}],
                )
            )
        assert run.status == "canceled" and attempts == [True]
