import asyncio
from datetime import timedelta

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.memory import upsert_memory
from app.models import Artifact, Conversation, ConversationSummary, MemoryEntry, Message, Run
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def seed(count=20, conversation_id=None, start=0):
    with session_factory()() as session:
        row = (
            session.get(Conversation, conversation_id)
            if conversation_id
            else Conversation(model="fake", provider=LocalChatProvider.key)
        )
        session.add(row)
        session.flush()
        for i in range(start, start + count):
            session.add(
                Message(
                    conversation_id=row.id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"message-{i:03}",
                    created_at=utcnow() - timedelta(seconds=1000 - i),
                    metadata_json={},
                )
            )
        session.commit()
        return row.id


def execute():
    with session_factory()() as session:
        tick(session, "summary-test")


@pytest.fixture
def fake(monkeypatch):
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield "Preserved decisions and preferences."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls


def test_summary_persists_sources_and_is_used_only_in_its_conversation(fake):
    conversation_id = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{conversation_id}"
    queued = api.post(path + "/summarize")
    assert queued.status_code == 202, queued.text
    run = queued.json()
    assert len(run["parameters"]["source_message_ids"]) == 12
    assert api.post(path + "/messages", json={"content": "blocked"}).status_code == 409
    execute()
    assert api.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
    detail = api.get(path).json()
    summary = detail["summary"]
    assert summary["enabled"] and len(summary["source_message_ids"]) == 12
    assert len(detail["messages"]) == 20  # no synthetic assistant turn or deleted history
    assert api.get(f"/api/artifacts?run_id={run['id']}").json()[0]["type"] == "markdown"
    reset_engine()
    assert api.get(path).json()["summary"] == summary
    assert api.post(path + "/summarize").status_code == 409
    next_run = api.post(path + "/messages", json={"content": "Continue"}).json()
    context = str(next_run["parameters"]["messages"])
    assert "Preserved decisions" in context and "message-000" not in context and "message-012" in context
    assert next_run["parameters"]["summary_source"]["id"] == summary["id"]
    other = seed(0)
    unrelated = api.post(f"/api/chat/conversations/{other}/messages", json={"content": "Hello"}).json()
    assert unrelated["parameters"]["summary_source"] is None
    assert "Preserved decisions" not in str(unrelated["parameters"])


def test_disabled_and_deleted_summary_is_not_restored_from_history(fake):
    cid = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    api.post(path + "/summarize")
    execute()
    seed(10, cid, 20)
    api.post(path + "/summarize")
    execute()
    summary = api.get(path).json()["summary"]
    assert summary["previous_summary_id"]
    memory_path = f"/api/memory/{summary['memory_id']}"
    memory = api.get(memory_path).json()
    response = api.put(
        memory_path,
        json={
            "content": memory["content"],
            "expected_updated_at": memory["updated_at"],
            "enabled": False,
            "memory_type": "summary",
        },
    )
    assert response.status_code == 200
    assert not api.get(path).json()["summary"]["enabled"]
    response = api.request("DELETE", memory_path, json={"expected_updated_at": response.json()["updated_at"]})
    assert response.status_code == 204, response.text
    assert api.get(path).json()["summary"]["memory_id"] is None
    next_run = api.post(path + "/messages", json={"content": "Continue"}).json()
    assert next_run["parameters"]["summary_source"] is None


def test_partial_and_superseded_responses_are_excluded(fake):
    cid = seed()
    with session_factory()() as session:
        rows = list(
            session.scalars(
                select(Message).where(Message.conversation_id == cid).order_by(Message.created_at)
            )
        )
        rows[1].metadata_json = {"partial": True}
        rows[3].metadata_json = {"superseded": True}
        session.commit()
    queued = TestClient(app).post(f"/api/chat/conversations/{cid}/summarize").json()
    assert "message-001" not in str(queued["parameters"]["messages"])
    assert "message-003" not in str(queued["parameters"]["messages"])


def test_cancel_silent_summary_closes_stream_without_publishing(monkeypatch):
    cid = seed()
    api = TestClient(app)
    run_id = api.post(f"/api/chat/conversations/{cid}/summarize").json()["id"]
    closed = []

    async def silent(self, **kwargs):
        try:
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    execute()
    assert closed == [True]
    assert api.get(f"/api/runs/{run_id}").json()["status"] == "canceled"
    assert api.get(f"/api/chat/conversations/{cid}").json()["summary"] is None


@pytest.mark.parametrize("failure", ["provider", "artifact"])
def test_failed_summary_does_not_publish_memory_or_coverage(monkeypatch, fake, failure):
    cid = seed()
    api = TestClient(app)
    run_id = api.post(f"/api/chat/conversations/{cid}/summarize").json()["id"]

    async def broken(self, **kwargs):
        yield "partial"
        raise ProviderError("Disconnected")

    def artifact_failure(*args, **kwargs):
        raise ValueError("Artifact storage failed")

    if failure == "provider":
        monkeypatch.setattr(LocalChatProvider, "stream", broken)
    else:
        monkeypatch.setattr("app.summary_executor.register_file", artifact_failure)
    execute()
    assert api.get(f"/api/runs/{run_id}").json()["status"] == "failed"
    with session_factory()() as session:
        for model in (ConversationSummary, MemoryEntry, Artifact):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_previous_memory_edit_during_update_is_preserved(monkeypatch, fake):
    cid = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    api.post(path + "/summarize")
    execute()
    prior = api.get(path).json()["summary"]
    seed(10, cid, 20)
    run = api.post(path + "/summarize").json()

    async def edit(self, **kwargs):
        with session_factory()() as session:
            upsert_memory(
                session,
                scope="conversation",
                entry_id=prior["memory_id"],
                content="User correction",
                memory_type="summary",
            )
            session.commit()
        yield "Obsolete generated summary"

    monkeypatch.setattr(LocalChatProvider, "stream", edit)
    execute()
    assert api.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
    assert api.get(path).json()["summary"]["content"] == "User correction"


def test_summary_migration_preserves_conversation_and_memory(fake):
    from alembic import command
    from app.db import alembic_config

    cid = seed()
    api = TestClient(app)
    api.post(f"/api/chat/conversations/{cid}/summarize")
    execute()
    memory_id = api.get(f"/api/chat/conversations/{cid}").json()["summary"]["memory_id"]
    command.downgrade(alembic_config(), "0002")
    command.upgrade(alembic_config(), "head")
    reset_engine()
    assert len(api.get(f"/api/chat/conversations/{cid}").json()["messages"]) == 20
    assert api.get(f"/api/memory/{memory_id}").json()["content"] == "Preserved decisions and preferences."


def test_summary_budget_rejects_oversize_output_without_replacing_prior(monkeypatch, fake):
    cid = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    api.post(path + "/summarize")
    execute()
    original = api.get(path).json()["summary"]
    seed(10, cid, 20)
    run = api.post(path + "/summarize").json()

    async def oversized(self, **kwargs):
        yield "x" * 8001

    monkeypatch.setattr(LocalChatProvider, "stream", oversized)
    execute()
    assert api.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
    assert api.get(path).json()["summary"] == original
