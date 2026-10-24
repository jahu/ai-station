"""Only actual same-conversation report bytes become frozen follow-up context."""

from uuid import uuid4

import pytest
from app.agent_result_context import reference
from app.config import get_settings
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from app.paths import safe_join
from sqlalchemy import select
from test_conversation_agent_control import enable, result, send, step
from test_conversation_agent_control import saved as saved

REPORT = "WillowReport: 41 completed items and 1 remaining item, for an exact total of 42."


def completed(saved, monkeypatch):
    enable(saved)
    queued = send(saved)
    step()

    async def stream(self, **kwargs):
        yield REPORT

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    for _ in range(12):
        if step() is None:
            break
    message = result(saved, queued["id"])
    assert message["agent_control_run"]["status"] == "succeeded"
    with session_factory()() as db:
        source = db.scalar(
            select(Run).where(
                Run.task_id == message["agent_control_run"]["task_id"], Run.executor_type == "agent"
            )
        )
        artifact = db.scalar(
            select(Artifact).where(Artifact.run_id == source.id, Artifact.artifact_type == "markdown")
        )
        return message["id"], source.id, artifact.id


def followup(saved, *, mode="chat", action="chat", prompt="Jaki był dokładny wynik tego agenta?"):
    api, cid, _, _ = saved
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": prompt, "execution_mode": mode, "action": action},
    )
    assert response.status_code == 202, response.text
    return response.json()


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_actual_report_is_quoted_with_exact_provenance_without_new_execution(saved, monkeypatch, mode):
    mid, rid, aid = completed(saved, monkeypatch)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield "The actual report totals 42."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    followup(saved, mode=mode)
    for _ in range(6):
        if step() is None:
            break
    assert len(calls) == 1
    assert REPORT in str(calls[0]["messages"]) and "untrusted quoted source data" in str(calls[0]["messages"])
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
        source = reply.parameters["agent_result_sources"][0]
        assert (
            source["available"]
            and source["source_message_id"] == mid
            and source["run_id"] == rid
            and source["artifact_id"] == aid
        )
        assert "filesystem_read" not in reply.effective_permissions
        message = db.scalar(select(Message).where(Message.run_id == reply.id, Message.role == "assistant"))
        assert message.metadata_json["agent_result_sources"] == reply.parameters["agent_result_sources"]
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))) == 1


@pytest.mark.parametrize(
    "problem", ["changed", "trashed", "partial", "owner", "wrong_task", "failed", "duplicate"]
)
def test_invalid_report_never_becomes_invented_or_fallback_context(saved, monkeypatch, problem):
    mid, rid, aid = completed(saved, monkeypatch)
    with session_factory()() as db:
        artifact, source = db.get(Artifact, aid), db.get(Run, rid)
        if problem == "changed":
            safe_join(get_settings().data_dir, artifact.relative_path).write_text(
                "Forged replacement contents"
            )
        elif problem == "trashed":
            from app.db import utcnow

            artifact.trashed_at = utcnow()
        elif problem == "partial":
            artifact.metadata_json = {**artifact.metadata_json, "partial": True}
        elif problem == "owner":
            artifact.metadata_json = {**artifact.metadata_json, "agent_id": str(uuid4())}
        elif problem == "wrong_task":
            source.task_id = db.get(Run, db.get(Message, mid).run_id).task_id
        elif problem == "failed":
            source.status = "failed"
        else:
            db.add(
                Artifact(
                    artifact_type="markdown",
                    mime_type="text/markdown",
                    run_id=rid,
                    relative_path=artifact.relative_path,
                    size_bytes=artifact.size_bytes,
                    sha256=artifact.sha256,
                    original_filename="duplicate.md",
                    metadata_json=artifact.metadata_json,
                )
            )
        db.commit()
        quoted, provenance = reference(db, db.get(Message, mid))
        assert not provenance["available"]
        assert "do not invent" in quoted or "instead of inventing" in quoted
        assert REPORT not in quoted and "Forged replacement" not in quoted


def test_reference_cannot_cross_conversation_or_come_from_quoted_user_text(saved, monkeypatch):
    mid, _, _ = completed(saved, monkeypatch)
    with session_factory()() as db:
        message = db.get(Message, mid)
        original = message.conversation_id
        # Move the message to another real conversation; its controller remains original.
        from app.models import Conversation

        other = Conversation(model="fake-local", execution_mode="chat")
        db.add(other)
        db.flush()
        message.conversation_id = other.id
        assert reference(db, message) is None
        message.conversation_id = original
        message.role = "user"
        assert reference(db, message) is None


def test_active_execution_is_explicitly_unfinished_and_never_reexecuted(saved):
    enable(saved, require_approval=True)
    queued = send(saved)
    step()
    message = result(saved, queued["id"])
    with session_factory()() as db:
        text, provenance = reference(db, db.get(Message, message["id"]))
        assert not provenance["available"] and provenance["status"] == "waiting_for_approval"
        assert "unfinished" in text
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_reference_has_a_real_budget_and_truncation_provenance(saved, monkeypatch):
    mid, _, aid = completed(saved, monkeypatch)
    import hashlib

    with session_factory()() as db:
        artifact = db.get(Artifact, aid)
        data = (REPORT * 1000).encode()
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(data)
        artifact.size_bytes = len(data)
        artifact.sha256 = hashlib.sha256(data).hexdigest()
        db.commit()
        text, source = reference(db, db.get(Message, mid), budget=1800)
        assert len(text) <= 1800 and source["truncated"]
        assert source["included_characters"] < source["total_characters"] == len(data)
        assert reference(db, db.get(Message, mid), budget=500) is None


def test_work_planner_receives_untrusted_result_context_without_inheriting_tool_scope(saved, monkeypatch):
    _, _, _ = completed(saved, monkeypatch)
    import json

    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        if kwargs.get("json_output"):
            yield json.dumps({"action": "chat", "reason": "Answer a question using the recorded result."})
        else:
            yield "The recorded total is 42."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    followup(saved, mode="work", action="auto")
    for _ in range(6):
        if step() is None:
            break
    assert len(calls) == 2
    planner = json.loads(calls[0]["messages"][1]["content"])
    assert REPORT in str(planner["recent_context"]) and "untrusted quoted source data" in str(planner)
    assert (
        not planner["coding_scope_selected"]
        and not planner["runtime_load_selected"]
        and not planner["external_cursor_allowed"]
    )
    with session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_report_context_is_frozen_at_enqueue_not_replaced_during_inference(saved, monkeypatch):
    _, _, aid = completed(saved, monkeypatch)
    queued = followup(saved)
    step()  # Ordinary orchestration publishes the actual Chat Run and its context.
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat", Run.parent_run_id == queued["id"]))
        before = reply.parameters["messages"]
        artifact = db.get(Artifact, aid)
        safe_join(get_settings().data_dir, artifact.relative_path).write_text(
            "Changed after the context snapshot"
        )
        assert REPORT in str(before)
    captured = []

    async def stream(self, **kwargs):
        captured.append(kwargs["messages"])
        yield "Answer from the frozen report."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    step()
    assert captured == [before] and "Changed after" not in str(captured)


def test_same_execution_is_not_quoted_twice_after_a_busy_run_receipt(saved, monkeypatch):
    enable(saved, require_approval=True)
    first = send(saved)
    step()
    second = send(saved)
    step()
    assert first["id"] != second["id"]
    assert result(saved, second["id"])["metadata"]["agent_control_result"]["outcome"] == "already_running"
    followup(saved)
    step()  # Queue the normal Chat child without executing inference.
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
        assert len(reply.parameters["agent_result_sources"]) == 1
        assert str(reply.parameters["messages"]).count("Agent result reference (") == 1


def test_newer_unfinished_execution_does_not_reuse_an_older_completed_report(saved, monkeypatch):
    completed(saved, monkeypatch)
    enable(saved, require_approval=True)
    newer = send(saved)
    step()
    waiting = result(saved, newer["id"])["agent_control_run"]
    assert waiting["status"] == "waiting_for_approval"
    followup(saved)
    step()
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
        sources = reply.parameters["agent_result_sources"]
        assert len(sources) == 1 and sources[0]["workflow_run_id"] == waiting["id"]
        assert not sources[0]["available"]
        assert REPORT not in str(reply.parameters["messages"])
