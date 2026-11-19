import sqlite3
from datetime import timedelta

from app.db import control_session_factory, get_engine, utcnow
from app.models import UserSession
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def test_chat_polling_reads_committed_state_while_another_connection_holds_the_writer(accounts):
    _, alice, bob = accounts
    private_chat = alice.post("/api/chat/conversations", json={"model": "test"})
    assert private_chat.status_code == 201, private_chat.text
    chat_id = private_chat.json()["id"]

    with sqlite3.connect(get_engine().url.database) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE conversations SET title = ? WHERE id = ?", ("Uncommitted", chat_id))
        assert alice.get("/api/health").status_code == 200
        assert alice.get("/api/auth").json()["authenticated"] is True
        history = alice.get("/api/chat/conversations")
        assert history.status_code == 200, history.text
        assert history.json()[0]["title"] == private_chat.json()["title"]
        detail = alice.get(f"/api/chat/conversations/{chat_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["title"] == private_chat.json()["title"]
        assert alice.get("/api/memory/personal/settings").status_code == 200
        assert bob.get(f"/api/chat/conversations/{chat_id}").status_code == 404
        blocked = alice.post("/api/chat/conversations", json={"model": "test"})
        assert blocked.status_code == 503, blocked.text
        assert blocked.headers["retry-after"] == "1"
        writer.rollback()

    assert len(alice.get("/api/chat/conversations").json()) == 1


def test_account_activity_refresh_still_updates_the_device_when_due(accounts):
    _, alice, _ = accounts
    account_id = alice.get("/api/auth").json()["user"]["id"]
    old = utcnow() - timedelta(minutes=2)
    with control_session_factory()() as session:
        device = session.scalar(select(UserSession).where(UserSession.user_id == account_id))
        device.token_record = {**device.token_record, "last_seen_at": old.isoformat()}
        session.commit()
        device_id = device.id

    assert alice.get("/api/chat/conversations").status_code == 200

    with control_session_factory()() as session:
        device = session.get(UserSession, device_id)
        assert device.token_record["last_seen_at"] > old.isoformat()
