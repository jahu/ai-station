import json
from uuid import uuid4

import pytest
from app.api import app
from app.assistant import AssistantExecutor, Plan
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Conversation, Message, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_chat_reasoning import model as model
from test_chat_reasoning import qualify


@pytest.fixture
def fake(monkeypatch):
    state = {"calls": [], "output": "A saved reply"}
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def stream(self, **params):
        state["calls"].append(params)
        yield state["output"]

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return state


def submit(client, text, **values):
    response = client.post(
        "/api/chat/turns",
        json={
            "client_request_id": str(uuid4()),
            "selection": {"execution_mode": "assistant", "model": "test-model"},
            "execution_mode": "assistant",
            "content": text,
            "web_search": {"enabled": False},
            **values,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def work():
    with session_factory()() as db:
        return tick(db, "unified-assistant-test")


@pytest.mark.parametrize(
    "text",
    [
        "Hello",
        "Wyjaśnij mechanikę kwantową",
        "Jak stworzyć agenta?",
        "Explain how to create an agent",
        "Czym jest Work w fizyce?",
        "I want to know how to create an agent",
        "Chcę wiedzieć jak stworzyć agenta",
        "I want you not to create an agent",
        "Chciałbym wiedzieć jak stworzyć agenta",
        "I would like to know how to create an agent",
        "Create a description of an agent",
        "Write a prompt for an agent",
        "Create a list of agents",
        "Prepare a tutorial about agents",
        "Create agent instructions",
    ],
)
def test_ordinary_question_is_one_direct_completion_without_planner_or_authority(fake, text):
    with TestClient(app) as client:
        result = submit(client, text)
        assert result["run"]["executor_type"] == "chat"
        assert result["run"]["effective_permissions"] == []
        work()
        assert len(fake["calls"]) == 1
        detail = client.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert detail["messages"][-1]["content"] == "A saved reply"
        with session_factory()() as db:
            assert len(list(db.scalars(select(Run)))) == 1
            assert list(db.scalars(select(Agent))) == []


def test_saved_legacy_conversation_accepts_a_new_assistant_task_without_rewriting_history(fake):
    with TestClient(app) as client:
        old = client.post(
            "/api/chat/conversations", json={"execution_mode": "chat", "model": "test-model"}
        ).json()
        response = client.post(
            "/api/chat/conversations/" + old["id"] + "/messages",
            json={
                "content": "Generate an image of a red bicycle",
                "execution_mode": "assistant",
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        identifier = response.json()["id"]
        work()
        with session_factory()() as db:
            root = db.get(Run, identifier)
            assert root.status == "succeeded" and root.metadata_json["plan"]["action"] == "image.generate"
            assert (
                root.parameters["policy_mode"] == "assistant"
                and "manage_agents" not in root.effective_permissions
            )
            assert db.get(Conversation, old["id"]).execution_mode == "chat"
            child = db.get(Run, root.metadata_json["child_run_id"])
            assert child.executor_type == "photo_pipe" and child.task_id == root.task_id
        assert fake["calls"] == []


def test_agent_request_creates_a_disabled_draft_without_a_mode_switch(fake):
    fake["output"] = json.dumps(
        {
            "name": "GPU observer",
            "goal": "Summarize workstation telemetry",
            "tools": ["system_snapshot"],
            "trigger": "cron",
            "cron_expr": "0 9 * * *",
        }
    )
    with TestClient(app) as client:
        result = submit(client, "Create an agent that summarizes workstation telemetry every morning")
        assert result["run"]["executor_type"] == "orchestrator"
        assert "manage_agents" in result["run"]["effective_permissions"]
        for _ in range(4):
            if work() is None:
                break
        with session_factory()() as db:
            assert all(item.status == "succeeded" for item in db.scalars(select(Run))), [
                (item.executor_type, item.status, item.error_message) for item in db.scalars(select(Run))
            ]
            agents = list(db.scalars(select(Agent)))
            assert len(agents) == 1 and not agents[0].enabled
            assert all(item.status == "succeeded" for item in db.scalars(select(Run)))
        assert len(fake["calls"]) == 1, "Only the draft model runs; no extra classification inference"


def test_planner_cannot_grant_agent_authority_from_an_unrelated_task(fake, monkeypatch):
    async def plan(*_):
        return Plan(action="agent.create", reason="Model suggestion")

    monkeypatch.setattr(AssistantExecutor, "plan", plan)
    with TestClient(app) as client:
        result = submit(client, "Build a workflow to sort files")
        assert result["run"]["executor_type"] == "orchestrator"
        assert "manage_agents" not in result["run"]["effective_permissions"]
        work()
        with session_factory()() as db:
            actual = db.get(Run, result["run"]["id"])
            assert actual.status == "succeeded" and actual.metadata_json["plan"]["action"] == "clarify"
            assert not list(db.scalars(select(Agent)))


def test_explicit_legacy_chat_restriction_is_preserved(fake):
    with TestClient(app) as client:
        identifier = client.post(
            "/api/chat/conversations", json={"execution_mode": "chat", "model": "test-model"}
        ).json()["id"]
        response = client.post(
            "/api/chat/conversations/" + identifier + "/messages",
            json={"content": "Create an agent", "action": "agent.create", "execution_mode": "chat"},
        )
        assert response.status_code == 422
        assert "Switch to Work" not in response.text


@pytest.mark.parametrize("mode", ["on", "off"])
def test_media_language_override_does_not_translate_ordinary_answers(fake, mode):
    with TestClient(app) as client:
        result = submit(client, "Wyjaśnij mechanikę kwantową", media_translation={"mode": mode})
        assert result["run"]["executor_type"] == "chat"
        work()
        with session_factory()() as db:
            assert len(list(db.scalars(select(Run)))) == 1
        assert len(fake["calls"]) == 1


def test_assistant_direct_reply_retains_qualified_reasoning(model):
    with TestClient(app) as client:
        qualify(client, model)
        result = submit(
            client,
            "17 * 23?",
            selection={"execution_mode": "assistant", "model": model["model"]},
            reasoning={"enabled": True, "budget": 256},
        )
        assert result["run"]["executor_type"] == "chat"
        assert result["run"]["parameters"]["reasoning"]["enabled"]
        work()
        with session_factory()() as db:
            actual = db.get(Run, result["run"]["id"])
            assert actual.status == "succeeded"
            message = db.scalar(
                select(Message).where(Message.run_id == actual.id, Message.role == "assistant")
            )
            assert message.content == "391"
