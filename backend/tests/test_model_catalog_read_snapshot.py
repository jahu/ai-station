"""Catalog rendering must allow independent writes while reading model metadata."""

import sqlite3

import pytest
from app.api import app
from app.db import get_engine, read_projection
from app.models import Setting
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session


def test_catalog_projection_does_not_reserve_the_sqlite_writer(monkeypatch):
    observed = []

    def catalog(session):
        # The projection has already read its providers when it reaches this
        # stage. Model enumeration can be slow; authentication must still write.
        try:
            with sqlite3.connect(get_engine().url.database, timeout=0.05) as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            observed.append(None)
        except sqlite3.OperationalError as error:
            observed.append(str(error))
        return {"models": [], "instances": []}

    monkeypatch.setattr("app.llama.catalog", catalog)
    with TestClient(app) as client:
        response = client.get("/api/chat/model-catalog")
    assert response.status_code == 200, response.text
    assert observed == [None], f"Read-only model metadata blocked another writer: {observed}"


def test_snapshot_is_consistent_and_default_transactions_still_reserve_writer(session):
    session.add(Setting(key="projection_test", value={"version": 1}))
    session.commit()
    read_projection(session)
    query = select(Setting.value).where(Setting.key == "projection_test")
    assert session.scalar(query) == {"version": 1}
    with sqlite3.connect(get_engine().url.database, timeout=0.05) as other:
        other.execute("BEGIN IMMEDIATE")
        other.execute("UPDATE settings SET value=? WHERE key=?", ('{"version":2}', "projection_test"))
    assert session.scalar(query) == {"version": 1}
    session.rollback()
    assert session.scalar(query) == {"version": 2}
    with sqlite3.connect(get_engine().url.database, timeout=0.05) as other:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")


@pytest.mark.parametrize("operation", ["orm", "bulk", "raw"])
def test_read_projection_rejects_writes_without_changing_data(session, operation):
    session.add(Setting(key="projection_test", value={"version": 1}))
    session.commit()
    read_projection(session)
    assert session.scalar(select(Setting.key).where(Setting.key == "projection_test"))
    with pytest.raises(RuntimeError, match="only SQLAlchemy SELECT"):
        if operation == "orm":
            session.get(Setting, "projection_test").value = {"version": 2}
            session.flush()
        elif operation == "bulk":
            session.execute(
                update(Setting).where(Setting.key == "projection_test").values(value={"version": 2})
            )
        else:
            session.execute(text("DELETE FROM settings WHERE key='projection_test'"))
    session.rollback()
    assert session.scalar(select(Setting.value).where(Setting.key == "projection_test")) == {"version": 1}


def test_projection_refuses_an_existing_write_transaction(session):
    session.add(Setting(key="projection_test", value={"version": 1}))
    with pytest.raises(RuntimeError, match="Finish the previous transaction"):
        read_projection(session)
    session.rollback()


def test_projection_cannot_poison_a_callers_bound_connection():
    with get_engine().begin() as connection:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as nested:
            with pytest.raises(RuntimeError, match="engine-bound session"):
                read_projection(nested)
        assert not connection.get_execution_options().get("ai_station_read_projection")
        connection.execute(Setting.__table__.insert().values(key="outer_transaction", value={"ok": True}))
