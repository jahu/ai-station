from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from app.api import app
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, ChatTurnRequest, Conversation, Message, Project, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def stream(self, **kwargs):
        yield "A saved reply"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)


def turn(**updates):
    return {
        "client_request_id": str(uuid4()),
        "selection": {"execution_mode": "chat", "model": "test-model"},
        "content": "Hello",
        **updates,
    }


def counts():
    with session_factory()() as session:
        return {
            cls.__name__: session.scalar(select(func.count()).select_from(cls))
            for cls in (Conversation, Message, Task, Run, ChatTurnRequest, Artifact, Project)
        }


def test_first_turn_is_atomic_idempotent_and_survives_restart(local):
    body = turn(attachments=[{"name": "notes.txt", "content": "Useful context", "kind": "text"}])
    with TestClient(app) as client:
        result = client.post("/api/chat/turns", json=body)
        assert result.status_code == 202, result.text
        receipt = result.json()
        before = counts()
        assert before == {
            "Conversation": 1,
            "Message": 2,
            "Task": 1,
            "Run": 1,
            "ChatTurnRequest": 1,
            "Artifact": 1,
            "Project": 0,
        }
        assert client.post("/api/chat/turns", json=body).json() == receipt
        assert counts() == before
        reset_engine()
        with session_factory()() as session:
            tick(session, "turn-test")
        replay = client.post("/api/chat/turns", json=body).json()
        assert replay["conversation_id"] == receipt["conversation_id"]
        assert replay["run"]["status"] == "succeeded"
        detail = client.get(f"/api/chat/conversations/{receipt['conversation_id']}").json()
        assert detail["messages"][-1]["content"] == "A saved reply"
        assert detail["settings_version"] == 1
        assert client.post("/api/chat/turns", json={**body, "content": "Another task"}).status_code == 409
        assert counts() == before


def test_concurrent_retries_publish_one_turn(local):
    body, barrier = turn(), Barrier(2)
    with TestClient(app) as client:

        def send():
            barrier.wait()
            return client.post("/api/chat/turns", json=body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        assert [r.status_code for r in results] == [202, 202]
        assert results[0].json() == results[1].json()
        assert counts()["Conversation"] == counts()["ChatTurnRequest"] == counts()["Run"] == 1


@pytest.mark.parametrize(
    "action",
    [
        "coding.local",
        "project.create",
        "project.create_code",
        "agent.create",
        "runtime.load",
        "coding.commit",
    ],
)
def test_chat_rejects_work_actions_before_creating_domain_rows(local, action):
    with TestClient(app) as client:
        result = client.post("/api/chat/turns", json=turn(action=action))
        assert result.status_code == 422
        assert "Switch to Work" in result.text
        assert all(n == 0 for n in counts().values())


def test_chat_natural_project_instruction_cannot_publish_project(local):
    with TestClient(app) as client:
        receipt = client.post("/api/chat/turns", json=turn(content="Create a project named Weather")).json()
        with session_factory()() as session:
            tick(session, "policy-test")
        detail = client.get(f"/api/chat/conversations/{receipt['conversation_id']}").json()
        assert "Switch to Work" in detail["messages"][-1]["content"]
        assert counts()["Project"] == 0
        assert counts()["Run"] == 1
        assert "manage_agents" not in receipt["run"]["effective_permissions"]


def test_chat_media_queues_existing_executor_but_model_plan_cannot_escalate(local, monkeypatch):
    from app.assistant import AssistantExecutor, Plan

    async def malicious(self, session, run):
        return Plan(action="agent.create", reason="I decided to create an agent")

    monkeypatch.setattr(AssistantExecutor, "plan", malicious)
    with TestClient(app) as client:
        receipt = client.post(
            "/api/chat/turns", json=turn(action="image.generate", content="A forest")
        ).json()
        with session_factory()() as session:
            tick(session, "media-test")
        runs = client.get("/api/runs").json()
        assert any(r["executor_type"] == "photo_pipe" for r in runs)
        assert all(r["capability"] != "agent.execute" for r in runs)
        assert (
            client.post(f"/api/chat/conversations/{receipt['conversation_id']}/regenerate").status_code == 409
        )


def test_followup_checks_settings_revision_and_preferences_are_versioned(local):
    with TestClient(app) as client:
        receipt = client.post("/api/chat/turns", json=turn()).json()
        cid = receipt["conversation_id"]
        with session_factory()() as session:
            tick(session, "turn-test")
        changed = client.patch(
            f"/api/chat/conversations/{cid}", json={"model": "test-model", "execution_mode": "chat"}
        )
        assert changed.json()["settings_version"] == 2
        body = turn(conversation_id=cid, selection=None, expected_settings_version=1)
        assert client.post("/api/chat/turns", json=body).status_code == 409
        assert (
            client.post("/api/chat/turns", json={**body, "expected_settings_version": 2}).status_code == 202
        )
        defaults = client.get("/api/chat/preferences").json()
        assert defaults["mode"] == "chat"
        saved = client.put("/api/chat/preferences", json={**defaults, "mode": "work", "model": "test-model"})
        assert saved.json()["version"] == defaults["version"] + 1
        assert client.put("/api/chat/preferences", json=defaults).status_code == 409
        assert client.get("/api/chat/preferences").json()["mode"] == "work"


def test_provider_version_is_stable_on_read_and_stale_send_has_no_side_effects(local):
    from app.chat_providers import BUILTIN_KEY
    from app.db import utcnow
    from app.models import ChatProvider

    with TestClient(app) as client:
        provider = client.get("/api/chat/providers/" + BUILTIN_KEY).json()
        version = provider["updated_at"]
        assert client.get("/api/chat/providers/" + BUILTIN_KEY).json()["updated_at"] == version
        body = turn(expected_provider_version=version)
        with session_factory()() as session:
            row = session.scalar(select(ChatProvider).where(ChatProvider.key == BUILTIN_KEY))
            row.name = "Renamed provider"
            row.updated_at = utcnow()
            session.commit()
        before = counts()
        assert client.post("/api/chat/turns", json=body).status_code == 409
        assert counts() == before
        fresh = client.get("/api/chat/providers/" + BUILTIN_KEY).json()["updated_at"]
        accepted = client.post("/api/chat/turns", json={**body, "expected_provider_version": fresh})
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["run"]["parameters"]["provider_config_version"] == fresh
        with session_factory()() as session:
            row = session.scalar(select(ChatProvider).where(ChatProvider.key == BUILTIN_KEY))
            row.updated_at = utcnow()
            session.commit()
        replay = client.post("/api/chat/turns", json={**body, "expected_provider_version": fresh})
        assert replay.json() == accepted.json()
        assert client.post("/api/chat/turns", json=body).status_code == 409


def test_legacy_receipt_replays_after_optional_scope_schema_extension(local):
    import hashlib
    import json

    from app.chat import TurnBody

    with TestClient(app) as client:
        body = turn()
        accepted = client.post("/api/chat/turns", json=body)
        assert accepted.status_code == 202
        legacy = TurnBody.model_validate(body).model_dump(mode="json")
        legacy.pop("expected_provider_version")
        legacy.pop("reasoning")
        legacy.pop("continuation")
        legacy.pop("new_project")
        with session_factory()() as session:
            receipt = session.get(ChatTurnRequest, body["client_request_id"])
            receipt.payload_hash = hashlib.sha256(
                json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            session.commit()
        before = counts()
        assert client.post("/api/chat/turns", json=body).json() == accepted.json()
        assert counts() == before
        assert client.post("/api/chat/turns", json={**body, "content": "Different goal"}).status_code == 409
