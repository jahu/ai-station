from datetime import timedelta
from uuid import uuid4

from app.api import app
from app.db import session_factory, utcnow
from app.models import Conversation, Message, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def test_history_cursor_reaches_old_rows_and_is_stable_when_new_chat_arrives():
    at = utcnow()
    with session_factory()() as session:
        for n in range(205):
            session.add(Conversation(id=str(uuid4()), title=f"Conversation {n}", updated_at=at))
        session.commit()
    with TestClient(app) as client:
        first = client.get("/api/chat/conversations").json()
        assert len(first) == 100
        with session_factory()() as session:
            session.add(Conversation(title="New arrival", updated_at=at + timedelta(seconds=1)))
            session.commit()
        second = client.get(
            "/api/chat/conversations",
            params={"before": first[-1]["updated_at"], "before_id": first[-1]["id"]},
        ).json()
        third = client.get(
            "/api/chat/conversations",
            params={"before": second[-1]["updated_at"], "before_id": second[-1]["id"]},
        ).json()
        ids = [row["id"] for row in first + second + third]
        assert len(second) == 100 and len(third) == 5
        assert len(ids) == len(set(ids)) == 205
        assert (
            client.get(
                "/api/chat/conversations",
                params={"before": third[-1]["updated_at"], "before_id": third[-1]["id"]},
            ).json()
            == []
        )


def test_search_reaches_message_text_and_treats_wildcards_literally_without_work():
    with session_factory()() as session:
        one = Conversation(title="Old project", updated_at=utcnow() - timedelta(days=10))
        two = Conversation(title="100% done")
        session.add_all([one, two])
        session.flush()
        session.add(Message(conversation_id=one.id, role="user", content="Remember the telescope decision"))
        session.commit()
        one_id, two_id = one.id, two.id
    with TestClient(app) as client:
        assert [r["id"] for r in client.get("/api/chat/conversations", params={"q": "telescope"}).json()] == [
            one_id
        ]
        assert [r["id"] for r in client.get("/api/chat/conversations", params={"q": "%"}).json()] == [two_id]
        assert client.get("/api/chat/conversations", params={"q": "unmatched"}).json() == []
        assert (
            client.get("/api/chat/conversations", params={"before": utcnow().isoformat()}).status_code == 422
        )
        assert client.get("/api/chat/conversations", params={"before_id": str(uuid4())}).status_code == 422
        assert client.get("/api/chat/conversations", params={"q": "x" * 201}).status_code == 422
        assert (
            client.get(
                "/api/chat/conversations", params={"before": "2026-01-01T00:00:00", "before_id": str(uuid4())}
            ).status_code
            == 422
        )
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 0
        assert session.scalar(select(func.count()).select_from(Task)) == 0
