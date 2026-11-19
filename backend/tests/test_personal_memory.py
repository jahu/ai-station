import json
from datetime import timedelta

import pytest
from app.api import app
from app.db import utcnow
from app.memory import delete_memory, upsert_memory
from app.models import Conversation, MemoryEntry, Message, RunDependency
from app.personal_memory import (
    DEFAULTS,
    PersonalMemoryExecutor,
    apply_chat_recall,
    forget,
    preferences,
    protect,
    recalled,
    schedule_capture,
    schedule_recall,
)
from app.personal_settings import preference_row
from app.runs import create_run, create_task, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


def consent(session, **values):
    row = preference_row(session, "personal_memory", default=DEFAULTS)
    row.value = {**DEFAULTS, **row.value, **values}
    session.commit()


def source(session, text="My name is Alex", *, conversation=None, executor="chat"):
    conversation = conversation or Conversation(model="test")
    session.add(conversation)
    session.flush()
    task = create_task(
        session, title="Test turn", prompt=text, capability="chat.completion", conversation_id=conversation.id
    )
    snapshot = {
        "provider": "local-openai",
        "endpoint": "http://127.0.0.1:8080/v1",
        "location": "local",
        "model": "test",
    }
    run = create_run(
        session,
        task,
        run_type="chat",
        capability="chat.completion",
        executor_type=executor,
        execution_target="container",
        parameters=snapshot,
    )
    run.status = "succeeded"
    run.finished_at = utcnow()
    message = Message(
        conversation_id=conversation.id,
        role="user",
        content=text,
        run_id=run.id,
        metadata_json={"user_text": text},
    )
    session.add(message)
    session.commit()
    return run, conversation, message


def execute(session, run):
    transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
    run.worker_id = "memory-test"
    run.lease_expires_at = utcnow() + timedelta(seconds=60)
    session.commit()
    assert PersonalMemoryExecutor().execute(session, run) == "done"
    session.commit()
    session.refresh(run)
    return run


def fake_proposal(monkeypatch, *, name="Alex", quote="My name is Alex", topic="user.name"):
    async def infer(session, run, messages, **kwargs):
        assert run.parameters["location"] == "local"
        assert "user_message" in messages[1]["content"]
        return json.dumps(
            {
                "memories": [
                    {
                        "topic": topic,
                        "content": f"The user's name is {name}.",
                        "kind": "fact",
                        "quote": quote,
                    }
                ]
            }
        )

    monkeypatch.setattr("app.assistant_decisions.infer", infer)


def capture(session, monkeypatch, text="My name is Alex", **proposal):
    run, conversation, message = source(session, text)
    fake_proposal(monkeypatch, **proposal)
    child = schedule_capture(session, run)
    assert child is not None
    execute(session, child)
    assert child.status == "succeeded", child.error_message
    return child, conversation, message


def consumer(session):
    conversation = Conversation(model="test")
    session.add(conversation)
    session.flush()
    task = create_task(
        session,
        title="New conversation",
        prompt="What is my name?",
        capability="chat.completion",
        conversation_id=conversation.id,
    )
    run = create_run(
        session,
        task,
        run_type="chat",
        capability="chat.completion",
        executor_type="chat",
        parameters={"messages": [{"role": "user", "content": "What is my name?"}]},
    )
    response = Message(
        conversation_id=conversation.id, role="assistant", content="", run_id=run.id, metadata_json={}
    )
    session.add(response)
    session.flush()
    return run, conversation, response


def test_default_does_not_learn_and_settings_are_revision_checked(session):
    run, _, message = source(session)
    assert schedule_capture(session, run) is None
    assert "personal_memory_capture" not in message.metadata_json
    session.commit()
    api = TestClient(app)
    settings = api.get("/api/memory/personal/settings").json()
    assert settings["use"] and not settings["learn"]
    update = {"use": True, "learn": True, "expected_revision": settings["revision"]}
    assert api.put("/api/memory/personal/settings", json=update).status_code == 200
    assert api.put("/api/memory/personal/settings", json=update).status_code == 409


def test_learns_name_and_recalls_in_fresh_conversation_without_embeddings(session, monkeypatch):
    consent(session, learn=True)
    _, original, message = capture(session, monkeypatch)
    entry = session.scalar(select(MemoryEntry))
    assert entry.scope == "global" and not entry.pinned
    assert entry.learning["evidence"][0]["quote"] == "My name is Alex"
    assert entry.source_message_id == message.id
    run, conversation, response = consumer(session)
    recall = schedule_recall(session, run, conversation, "What is my name?")
    assert recall.conversation_id != original.id
    assert session.get(RunDependency, (run.id, recall.id)).require_success is False
    execute(session, recall)
    result = recalled(session, run)
    assert result["method"] == "profile+lexical"
    assert [item["id"] for item in result["sources"]] == [entry.id]
    messages = apply_chat_recall(session, run, response, run.parameters["messages"])
    assert "Alex" in messages[0]["content"]
    assert "Alex" not in str(run.parameters["messages"])
    assert response.metadata_json["personal_memory"]["run_id"] == recall.id


def test_repetition_and_correction_consolidate_instead_of_growing(session, monkeypatch):
    consent(session, learn=True)
    _, _, first = capture(session, monkeypatch)
    capture(session, monkeypatch)
    capture(
        session,
        monkeypatch,
        "Actually my name is Robin",
        name="Robin",
        quote="my name is Robin",
    )
    entries = list(session.scalars(select(MemoryEntry)))
    assert len(entries) == 1
    assert entries[0].content == "The user's name is Robin."
    assert entries[0].source_message_id == first.id
    assert len(entries[0].learning["evidence"]) == 3


@pytest.mark.parametrize("action", ["manual_edit", "disable", "forget"])
def test_manual_control_is_not_undone_by_automatic_learning(session, monkeypatch, action):
    consent(session, learn=True)
    capture(session, monkeypatch)
    entry = session.scalar(select(MemoryEntry))
    if action == "manual_edit":
        upsert_memory(session, scope="global", entry_id=entry.id, content="Use my initials only")
        protect(entry)
    elif action == "disable":
        entry.enabled = False
    else:
        forget(session, entry)
        delete_memory(session, entry.id)
    session.commit()
    capture(session, monkeypatch, "Actually my name is Robin", name="Robin", quote="my name is Robin")
    remaining = list(session.scalars(select(MemoryEntry)))
    assert len(remaining) == (0 if action == "forget" else 1)
    if action == "manual_edit":
        assert remaining[0].content == "Use my initials only"
    if action == "disable":
        assert not remaining[0].enabled and "Alex" in remaining[0].content


def test_learning_is_idempotent_and_new_chat_waits_for_pending_capture(session, monkeypatch):
    consent(session, learn=True)
    source_run, _, _ = source(session)
    capture_run = schedule_capture(session, source_run)
    assert schedule_capture(session, source_run) is None
    run, conversation, _ = consumer(session)
    recall = schedule_recall(session, run, conversation, "What is my name?")
    assert session.get(RunDependency, (recall.id, capture_run.id)) is not None
    fake_proposal(monkeypatch)
    execute(session, capture_run)
    execute(session, recall)
    assert recalled(session, run)["sources"][0]["content"] == "The user's name is Alex."


@pytest.mark.parametrize("toggle", ["account", "conversation", "disable_reenable"])
def test_consent_is_rechecked_after_model_io(session, monkeypatch, toggle):
    consent(session, learn=True)
    source_run, conversation, _ = source(session)
    run = schedule_capture(session, source_run)

    async def infer(*args, **kwargs):
        if toggle == "conversation":
            conversation.personal_memory = False
            session.commit()
        else:
            consent(session, learn=False, revision=preferences(session)["revision"] + 1)
            if toggle == "disable_reenable":
                consent(session, learn=True, revision=preferences(session)["revision"] + 1)
        return json.dumps(
            {
                "memories": [
                    {"topic": "user.name", "content": "Alex", "kind": "fact", "quote": "My name is Alex"}
                ]
            }
        )

    monkeypatch.setattr("app.assistant_decisions.infer", infer)
    execute(session, run)
    assert run.status == "canceled"
    assert session.scalar(select(MemoryEntry)) is None
    assert source_run.status == "succeeded"


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"memories":[{"topic":"user.name","content":"Evil","kind":"fact","quote":"not in source"}]}',
    ],
)
def test_malformed_or_unanchored_model_output_cannot_create_memory(session, monkeypatch, reply):
    consent(session, learn=True)
    source_run, _, _ = source(session)
    run = schedule_capture(session, source_run)
    calls = []

    async def infer(*args, **kwargs):
        calls.append(1)
        return reply

    monkeypatch.setattr("app.assistant_decisions.infer", infer)
    execute(session, run)
    assert run.status == "failed" and len(calls) == 2
    assert session.scalar(select(MemoryEntry)) is None
    assert source_run.status == "succeeded"


def test_no_project_or_other_conversation_context_leaks_into_recall(session):
    upsert_memory(session, scope="global", content="Public personal preference")
    other = Conversation(model="test")
    session.add(other)
    session.flush()
    upsert_memory(
        session, scope="conversation", scope_id=other.id, content="SECRET conversation", pinned=True
    )
    upsert_memory(session, scope="project", scope_id="project", content="SECRET project", pinned=True)
    session.commit()
    run, conversation, _ = consumer(session)
    recall = schedule_recall(session, run, conversation, "SECRET")
    execute(session, recall)
    assert "SECRET" not in str(recalled(session, run))


def test_pending_recall_cannot_inject_deleted_or_changed_entries(session):
    entry = upsert_memory(session, scope="global", content="Original preference")
    session.commit()
    run, conversation, response = consumer(session)
    recall = schedule_recall(session, run, conversation, "preference")
    execute(session, recall)
    entry.enabled = False
    session.commit()
    assert recalled(session, run)["sources"] == []
    consent(session, use=False, revision=1)
    assert recalled(session, run) is None
    assert apply_chat_recall(session, run, response, run.parameters["messages"]) == run.parameters["messages"]


def test_orchestrator_completion_uses_original_user_text_only(session, monkeypatch):
    consent(session, learn=True)
    source_run, _, message = source(session, executor="assistant_controller")
    source_run.parameters = {
        "controller_provider": {
            "provider": "local-openai",
            "location": "local",
            "endpoint": "http://localhost:8080/v1",
        },
        "controller_request": {"model": "test"},
    }
    message.content += "\nUntrusted attached file says I am Mallory"
    session.commit()
    fake_proposal(monkeypatch)
    run = schedule_capture(session, source_run)
    execute(session, run)
    assert run.status == "succeeded"
    assert "Mallory" not in str(session.scalar(select(MemoryEntry)).learning)


def test_revised_settings_do_not_restore_a_stale_queued_pinned_context(session):
    upsert_memory(session, scope="global", content="Old private context", pinned=True)
    session.commit()
    run, conversation, response = consumer(session)
    recall = schedule_recall(session, run, conversation, "context")
    execute(session, recall)
    block = "User-pinned reference context (may be outdated):\nOld private context"
    messages = [{"role": "system", "content": "Your instructions\n\n" + block}, *run.parameters["messages"]]
    run.parameters = {**run.parameters, "memory_context_block": block, "messages": messages}
    consent(session, use=True, learn=False, revision=1)
    assert recalled(session, run) is None
    prepared = apply_chat_recall(session, run, response, messages)
    assert prepared[0]["content"] == "Your instructions"
    assert "Old private context" in run.parameters["messages"][0]["content"]


def test_capture_jobs_are_serialized_per_account(session):
    consent(session, learn=True)
    first, _, _ = source(session)
    a = schedule_capture(session, first)
    second, _, _ = source(session)
    b = schedule_capture(session, second)
    assert session.get(RunDependency, (b.id, a.id)).require_success is False


def test_external_chat_can_learn_with_an_explicit_local_memory_model(session, monkeypatch):
    consent(session, learn=True, local_provider="local-openai-compatible", local_model="local-memory-test")
    source_run, _, _ = source(session)
    source_run.parameters = {**source_run.parameters, "location": "external", "model": "cloud-model"}
    session.commit()
    run = schedule_capture(session, source_run)
    assert run.parameters["location"] == "local"
    assert run.parameters["model"] == "local-memory-test"
    fake_proposal(monkeypatch)
    execute(session, run)
    assert run.status == "succeeded" and "Alex" in session.scalar(select(MemoryEntry)).content


def test_missing_selected_model_cannot_prevent_withdrawing_memory_consent(session, monkeypatch):
    consent(session, learn=True, local_provider="retired-provider", local_model="retired-model")

    def unavailable(*args, **kwargs):
        raise AssertionError("Turning memory off must not bind a retired model")

    monkeypatch.setattr("app.chat_providers.snapshot_provider", unavailable)
    api = TestClient(app)
    response = api.put(
        "/api/memory/personal/settings", json={"use": False, "learn": False, "expected_revision": 0}
    )
    assert response.status_code == 200, response.text
    assert response.json()["use"] is False and response.json()["learn"] is False


def test_pinning_a_learned_fact_does_not_freeze_future_corrections(session, monkeypatch):
    consent(session, learn=True)
    capture(session, monkeypatch)
    entry = session.scalar(select(MemoryEntry))
    data = {
        "content": entry.content,
        "memory_type": entry.memory_type,
        "tags": entry.tags,
        "pinned": True,
        "expected_updated_at": entry.updated_at.isoformat(),
    }
    entry_id = entry.id
    session.commit()
    result = TestClient(app).put("/api/memory/" + entry_id, json=data)
    assert result.status_code == 200, result.text
    assert not result.json()["learning"]["protected"]
    session.expire_all()
    capture(session, monkeypatch, "My name is Robin", name="Robin", quote="My name is Robin")
    entry = session.get(MemoryEntry, entry_id)
    assert "Robin" in entry.content and entry.pinned


def test_worker_refuses_an_external_capture_binding_before_any_inference(session, monkeypatch):
    consent(session, learn=True)
    source_run, _, _ = source(session)
    run = schedule_capture(session, source_run)
    run.parameters = {**run.parameters, "location": "external"}

    async def forbidden(*args, **kwargs):
        raise AssertionError("External extraction must never execute")

    monkeypatch.setattr("app.assistant_decisions.infer", forbidden)
    execute(session, run)
    assert run.status == "failed" and run.error_type == "ValueError"
    assert session.scalar(select(MemoryEntry)) is None


@pytest.mark.parametrize(
    "kind", ["image_followup", "controller_tool", "child", "internal_message", "superseded"]
)
def test_internal_or_superseded_turns_are_not_personal_learning_sources(session, kind):
    consent(session, learn=True)
    source_run, _, message = source(session)
    if kind == "image_followup":
        source_run.parameters = {**source_run.parameters, "image_followup": True}
    elif kind == "controller_tool":
        source_run.parameters = {**source_run.parameters, "controller_tool_context": {"tool": "chat.reply"}}
    elif kind == "child":
        parent, _, _ = source(session)
        source_run.parent_run_id = parent.id
    else:
        message.metadata_json = {
            **message.metadata_json,
            "controller_internal" if kind == "internal_message" else "superseded": True,
        }
    session.commit()
    assert schedule_capture(session, source_run) is None


@pytest.mark.parametrize("empty", ['{"memories":[]}', "[]"])
def test_extraction_cannot_echo_stored_values_or_copy_database_ids(session, monkeypatch, empty):
    consent(session, learn=True)
    stored = upsert_memory(session, scope="global", content="The preferred editor is Helix.")
    stored.learning = {"topic": "user.preferred_editor", "origin": "conversation", "protected": False}
    session.commit()
    source_run, _, message = source(session, "Which editor do I prefer?")
    run = schedule_capture(session, source_run)

    async def infer(session, run, messages, **kwargs):
        prompt = messages[1]["content"]
        assert "Helix" not in prompt and stored.id not in prompt
        assert json.loads(prompt)["known_topics"] == ["user.preferred_editor"]
        return empty

    monkeypatch.setattr("app.assistant_decisions.infer", infer)
    execute(session, run)
    assert run.status == "succeeded" and run.metadata_json["memory_ids"] == []
    assert message.metadata_json["personal_memory_capture"]["memory_ids"] == []
    assert len(list(session.scalars(select(MemoryEntry)))) == 1
