"""Telemetry may wait on a busy host, never while holding SQLite's writer."""

import sqlite3

import pytest
from app import scheduler_main


class StopLoop(BaseException):
    pass


def test_empty_reconciliation_releases_transaction_before_native_telemetry(session, monkeypatch):
    inspected = []
    database = session.bind.url.database
    session.commit()

    class Runner:
        def hardware(self):
            with sqlite3.connect(database, timeout=0.05) as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            inspected.append(True)
            return {"gpus": []}

    def stop(_seconds):
        raise StopLoop()

    monkeypatch.setattr(scheduler_main, "migrate", lambda: None)
    monkeypatch.setattr(scheduler_main, "RunnerClient", lambda **kwargs: Runner())
    monkeypatch.setattr(scheduler_main.time, "sleep", stop)
    with pytest.raises(StopLoop):
        scheduler_main.main()
    assert inspected == [True]
