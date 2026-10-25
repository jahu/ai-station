"""Contention never restarts unrelated worker slots or retries an executor."""

import sqlite3
from types import SimpleNamespace

import pytest
from app import worker_main
from app.db import sqlite_busy
from sqlalchemy.exc import OperationalError


class StopLoop(BaseException):
    pass


def error(code):
    original = sqlite3.OperationalError("fixture sqlite error")
    original.sqlite_errorcode = code
    return OperationalError("BEGIN IMMEDIATE", {}, original)


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY | 256])
def test_busy_slot_rolls_back_closes_and_continues_without_replaying_work(monkeypatch, caplog, code):
    sessions, calls, sleeps = [], [], []

    def factory():
        state = {"rollback": 0, "close": 0}
        sessions.append(state)
        return SimpleNamespace(
            rollback=lambda: state.__setitem__("rollback", state["rollback"] + 1),
            close=lambda: state.__setitem__("close", state["close"] + 1),
        )

    def tick(session, identity):
        calls.append(identity)
        if len(calls) == 1:
            raise error(code)
        raise StopLoop()

    monkeypatch.setattr(worker_main, "session_factory", lambda: factory)
    monkeypatch.setattr(worker_main, "tick", tick)
    monkeypatch.setattr(worker_main, "time", SimpleNamespace(sleep=sleeps.append))
    with pytest.raises(StopLoop):
        worker_main.worker_loop("same-worker/slot-1")
    assert calls == ["same-worker/slot-1"] * 2
    assert sessions == [{"rollback": 1, "close": 1}, {"rollback": 0, "close": 1}]
    assert len(sleeps) == 1 and "SQLite busy" in caplog.text
    assert "BEGIN IMMEDIATE" not in caplog.text  # Never log bound SQL/parameters.


@pytest.mark.parametrize(
    "exc", [error(sqlite3.SQLITE_ERROR), OperationalError("SELECT", {}, RuntimeError("database is locked"))]
)
def test_other_database_errors_are_not_hidden_as_transient(monkeypatch, exc):
    calls = []
    current = SimpleNamespace(rollback=lambda: calls.append("rollback"), close=lambda: calls.append("close"))
    monkeypatch.setattr(worker_main, "session_factory", lambda: lambda: current)

    def tick(*args):
        raise exc

    monkeypatch.setattr(worker_main, "tick", tick)
    with pytest.raises(OperationalError) as caught:
        worker_main.worker_loop("worker")
    assert caught.value is exc and calls == ["rollback", "close"]
    assert not sqlite_busy(exc)
