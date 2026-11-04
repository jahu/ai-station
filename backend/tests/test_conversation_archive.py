from uuid import uuid4

from app.api import app
from app.db import session_factory
from app.models import ChatTurnRequest, Message, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def create(client):
    result = client.post("/api/chat/conversations", json={"model": "test", "title": "Keep this conversation"})
    assert result.status_code == 201, result.text
    return result.json()


def archive(client, row, value=True, version=None):
    return client.put(
        "/api/chat/conversations/" + row["id"] + "/archive",
        json={"archived": value, "expected_settings_version": version or row["settings_version"]},
    )


def counts():
    with session_factory()() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Run, Task, Message, ChatTurnRequest)
        }


def test_archive_restore_preserves_detail_and_requires_current_revision():
    with TestClient(app) as client:
        row = create(client)
        result = archive(client, row)
        assert result.status_code == 200, result.text
        saved = result.json()
        assert saved["archived_at"] and saved["settings_version"] == 2
        assert client.get("/api/chat/conversations").json() == []
        assert client.get("/api/chat/conversations?archived=true&q=Keep").json()[0]["id"] == row["id"]
        assert client.get("/api/chat/conversations/" + row["id"]).status_code == 200
        assert archive(client, row, False).status_code == 409
        restored = archive(client, saved, False)
        assert restored.status_code == 200 and restored.json()["archived_at"] is None
        assert client.get("/api/chat/conversations").json()[0]["id"] == row["id"]
        assert client.get("/api/chat/conversations?archived=true").json() == []


def test_archived_send_and_regenerate_do_not_create_work():
    with TestClient(app) as client:
        row = archive(client, create(client)).json()
        before = counts()
        result = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "conversation_id": row["id"],
                "expected_settings_version": row["settings_version"],
                "content": "Hello",
            },
        )
        assert result.status_code == 409 and "Restore" in result.text
        result = client.post("/api/chat/conversations/" + row["id"] + "/messages", json={"content": "Hello"})
        assert result.status_code == 409 and "Restore" in result.text
        result = client.post("/api/chat/conversations/" + row["id"] + "/regenerate")
        assert result.status_code == 409 and "Restore" in result.text
        assert counts() == before


def test_archive_rejects_active_run_and_keeps_pending_messages():
    with TestClient(app) as client:
        row = create(client)
        result = client.post("/api/chat/conversations/" + row["id"] + "/messages", json={"content": "Hello"})
        assert result.status_code == 202, result.text
        before = counts()
        result = archive(client, row)
        assert result.status_code == 409 and "active run" in result.text
        assert counts() == before
        assert client.get("/api/chat/conversations/" + row["id"]).json()["archived_at"] is None


def test_migration_preserves_existing_conversation_and_history(legacy_schema):
    from alembic import command
    from app.db import alembic_config

    with TestClient(app) as client:
        row = create(client)
        legacy_schema("0023")
        command.upgrade(alembic_config(), "head")
        saved = client.get("/api/chat/conversations/" + row["id"]).json()
        assert saved["title"] == row["title"] and saved["archived_at"] is None
        assert archive(client, saved).status_code == 200
        command.check(alembic_config())


def test_archive_preserves_receipts_artifacts_and_scoped_memory():
    from app.models import Artifact, MemoryEntry

    with TestClient(app) as client:
        row = create(client)
        body = {
            "client_request_id": str(uuid4()),
            "conversation_id": row["id"],
            "expected_settings_version": 1,
            "content": "A saved question",
        }
        response = client.post("/api/chat/turns", json=body)
        assert response.status_code == 202, response.text
        receipt = response.json()
        run_id = receipt["run"]["id"]
        assert client.post("/api/runs/" + run_id + "/cancel").status_code == 200
        with session_factory()() as session:
            asset = Artifact(artifact_type="text", relative_path="artifacts/kept.txt", run_id=run_id)
            memory = MemoryEntry(
                scope="conversation",
                scope_id=row["id"],
                memory_type="fact",
                content="Keep this fact",
                source_run_id=run_id,
            )
            session.add_all([asset, memory])
            session.commit()
            asset_id, memory_id = asset.id, memory.id
        row = client.get("/api/chat/conversations/" + row["id"]).json()
        before = counts()
        result = archive(client, row)
        assert result.status_code == 200, result.text
        assert (
            client.get("/api/chat/conversations/" + row["id"]).json()["messages"][0]["content"]
            == body["content"]
        )
        replay = client.post("/api/chat/turns", json=body)
        assert replay.status_code == 202 and replay.json()["run"]["id"] == run_id
        assert counts() == before
        with session_factory()() as session:
            assert session.get(Artifact, asset_id).run_id == run_id
            assert session.get(MemoryEntry, memory_id).content == "Keep this fact"
        assert archive(client, result.json(), False).status_code == 200


def test_active_and_archived_search_and_cursor_are_separate():
    from app.db import utcnow
    from app.models import Conversation

    with TestClient(app) as client:
        rows = [create(client) for _ in range(3)]
        assert archive(client, rows[1]).status_code == 200
        stamp = utcnow()
        with session_factory()() as session:
            for row in session.scalars(select(Conversation)):
                row.updated_at = stamp
            session.commit()
        active = client.get("/api/chat/conversations?q=Keep").json()
        assert {r["id"] for r in active} == {rows[0]["id"], rows[2]["id"]}
        cursor = {"before": active[0]["updated_at"], "before_id": active[0]["id"], "q": "Keep"}
        assert [r["id"] for r in client.get("/api/chat/conversations", params=cursor).json()] == [
            active[1]["id"]
        ]
        archived = client.get("/api/chat/conversations?archived=true&q=Keep").json()
        assert [r["id"] for r in archived] == [rows[1]["id"]]
