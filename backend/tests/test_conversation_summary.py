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


@pytest.mark.parametrize("enabled,count,expected", [(False, 20, False), (True, 12, False), (True, 14, True)])
def test_automatic_summary_requires_opt_in_and_threshold(fake, enabled, count, expected):
    cid = seed(count)
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    assert api.get(path).json()["auto_summary"] is False
    assert api.patch(path + "/context", json={"auto_summary": "true"}).status_code == 422
    assert api.patch(path + "/context", json={"auto_summary": enabled}).status_code == 200
    reply = api.post(path + "/messages", json={"content": "Continue"}).json()
    assert api.patch(path + "/context", json={"auto_summary": False}).status_code == 409
    execute()
    finished = api.get(f"/api/runs/{reply['id']}").json()
    assert finished["status"] == "succeeded"
    active = api.get(path).json()["active_run"]
    assert bool(active) == expected
    if expected:
        assert active["executor_type"] == "chat_summary"
        assert active["parent_run_id"] == reply["id"]
        assert active["triggered_by"] == "automatic_context"
        assert finished["metadata"]["summary_run_id"] == active["id"]
        assert len(fake) == 1  # Enqueueing does not execute another provider call.
        execute()
        detail = api.get(path).json()
        assert detail["summary"]["enabled"] and not detail["active_run"]
        reset_engine()
        assert api.get(path).json()["auto_summary"] is True
        next_reply = api.post(path + "/messages", json={"content": "What did we decide?"}).json()
        assert next_reply["parameters"]["summary_source"]["id"] == detail["summary"]["id"]
        execute()
        assert api.get(path).json()["active_run"] is None  # Eight recent messages remain below threshold.


def test_automatic_summary_does_not_restore_disabled_memory(fake):
    cid = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    api.post(path + "/summarize")
    execute()
    summary = api.get(path).json()["summary"]
    with session_factory()() as session:
        session.get(MemoryEntry, summary["memory_id"]).enabled = False
        session.commit()
    api.patch(path + "/context", json={"auto_summary": True})
    reply = api.post(path + "/messages", json={"content": "Continue"}).json()
    execute()
    assert api.get(f"/api/runs/{reply['id']}").json()["status"] == "succeeded"
    assert api.get(path).json()["active_run"] is None
    assert not api.get(path).json()["summary"]["enabled"]


@pytest.mark.parametrize("failure", ["reply", "summary", "enqueue"])
def test_automatic_summary_failure_preserves_successful_reply_without_retry(fake, monkeypatch, failure):
    cid = seed()
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    api.patch(path + "/context", json={"auto_summary": True})
    reply = api.post(path + "/messages", json={"content": "Continue"}).json()

    async def broken(self, **kwargs):
        raise ProviderError("Unavailable")
        yield

    def cannot_prepare(*args, **kwargs):
        raise ProviderError("Model unavailable")

    if failure == "reply":
        monkeypatch.setattr(LocalChatProvider, "stream", broken)
    if failure == "enqueue":
        monkeypatch.setattr("app.llama.prepare_consumer", cannot_prepare)
    execute()
    result = api.get(f"/api/runs/{reply['id']}").json()
    assert result["status"] == ("failed" if failure == "reply" else "succeeded")
    if failure == "summary":
        pending = api.get(path).json()["active_run"]
        monkeypatch.setattr(LocalChatProvider, "stream", broken)
        execute()
        assert api.get(f"/api/runs/{pending['id']}").json()["status"] == "failed"
        assert api.get(path).json()["summary_update"]["status"] == "failed"
    assert api.get(path).json()["active_run"] is None
    assert api.get(path).json()["summary"] is None
    with session_factory()() as session:
        expected = 2 if failure == "summary" else 1
        assert session.scalar(select(func.count()).select_from(Run)) == expected


def test_automatic_context_migration_defaults_off_and_preserves_history():
    from alembic import command
    from app.db import alembic_config

    cid = seed()
    command.downgrade(alembic_config(), "0006")
    command.upgrade(alembic_config(), "head")
    reset_engine()
    detail = TestClient(app).get(f"/api/chat/conversations/{cid}").json()
    assert detail["auto_summary"] is False
    assert len(detail["messages"]) == 20


def test_split_chunk_prefers_paragraph_breaks():
    from app.conversation_summary import collect_segment, split_chunk

    text = "alpha\n\n" + ("b" * 2000) + "\n\n" + ("c" * 2000)
    assert split_chunk(text, 2500) == len("alpha\n\n") + 2000 + 2

    class Piece:
        def __init__(self, content, identity):
            self.content = content
            self.id = identity
            self.role = "user"

    first = Piece("x" * 60000, "oversize")
    pieces, covered, offset = collect_segment([first, Piece("later", "later")])
    assert covered is first and offset == 48000
    assert pieces[0]["start"] == 0 and pieces[0]["end"] == 48000 and pieces[0]["total"] == 60000
    remainder, covered, offset = collect_segment([first, Piece("later", "later")], start_offset=48000)
    assert [item["message"].id for item in remainder] == ["oversize", "later"]
    assert remainder[0]["start"] == 48000 and remainder[0]["end"] == 60000
    assert covered.id == "later" and offset == 0


def _set_oldest_content(conversation_id, content):
    with session_factory()() as session:
        message = session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        message.content = content
        session.commit()
        return message.id


def test_oversized_message_is_chunked_and_remainder_stays_in_chat(fake):
    cid = seed(10)
    oversized = ("KEEP-HEAD " * 4800) + ("TAIL-PAD " * 400) + "UNIQUE-TAIL"
    source_id = _set_oldest_content(cid, oversized)
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    queued = api.post(path + "/summarize")
    assert queued.status_code == 202, queued.text
    run = queued.json()
    assert run["parameters"]["covered_message_id"] == source_id
    assert run["parameters"]["covered_offset"] == 48000
    assert run["parameters"]["source_chunks"][0]["end"] == 48000
    payload = run["parameters"]["messages"][1]["content"]
    assert "Partial message characters 1–48000 of" in payload
    assert "KEEP-HEAD" in payload and "UNIQUE-TAIL" not in payload
    execute()
    summary = api.get(path).json()["summary"]
    assert summary["covered_offset"] == 48000
    assert summary["covered_message_length"] == len(oversized)
    next_run = api.post(path + "/messages", json={"content": "Continue"}).json()
    context = str(next_run["parameters"]["messages"])
    assert "UNIQUE-TAIL" in context and "KEEP-HEAD" not in context
    execute()
    follow = api.post(path + "/summarize")
    assert follow.status_code == 202, follow.text
    second = follow.json()
    assert second["parameters"]["covered_offset"] == 0
    assert "UNIQUE-TAIL" in second["parameters"]["messages"][1]["content"]
    execute()
    done = api.get(path).json()["summary"]
    assert done["covered_offset"] == 0
    later = api.post(path + "/messages", json={"content": "After coverage"}).json()
    assert "UNIQUE-TAIL" not in str(later["parameters"]["messages"])


def test_automatic_summary_chunks_an_oversized_uncovered_message(fake):
    cid = seed(8)
    _set_oldest_content(cid, "BLOCK " * 9000)
    api = TestClient(app)
    path = f"/api/chat/conversations/{cid}"
    assert api.patch(path + "/context", json={"auto_summary": True}).status_code == 200
    reply = api.post(path + "/messages", json={"content": "Continue"}).json()
    execute()
    finished = api.get(f"/api/runs/{reply['id']}").json()
    assert finished["status"] == "succeeded"
    active = api.get(path).json()["active_run"]
    assert active and active["executor_type"] == "chat_summary"
    assert active["parameters"]["covered_offset"] > 0
    execute()
    summary = api.get(path).json()["summary"]
    assert summary["enabled"] and summary["covered_offset"] > 0


def test_coverage_offset_migration_defaults_zero_and_preserves_summary(fake):
    from alembic import command
    from app.db import alembic_config

    cid = seed()
    api = TestClient(app)
    api.post(f"/api/chat/conversations/{cid}/summarize")
    execute()
    command.downgrade(alembic_config(), "0015")
    command.upgrade(alembic_config(), "head")
    reset_engine()
    summary = api.get(f"/api/chat/conversations/{cid}").json()["summary"]
    assert summary["enabled"] and summary["covered_offset"] == 0
    assert summary["content"] == "Preserved decisions and preferences."
