"""Scheduled media in the unified conversation creates a reviewable definition."""

import json
from uuid import uuid4

import pytest
from app import web_search
from app.api import app
from app.db import reset_engine, session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import implemented_media as implemented_media
from test_assistant_controller import drain, finish, tool
from test_unified_assistant import submit, work


@pytest.mark.parametrize(
    ("text", "kind", "media_request"),
    [
        ("co 15 minut generuj mi zdjęcie gór", "image", {"mode": "t2i", "prompt": "Mountain landscape"}),
        (
            "Generate a photograph of mountains every 15 minutes",
            "image",
            {"mode": "t2i", "prompt": "Mountain landscape"},
        ),
        (
            "Wygeneruj instrumentalną muzykę co 15 minut",
            "music",
            {"caption": "Calm instrumental piano", "duration_seconds": 30},
        ),
        (
            "Every 15 minutes generate a ten-second forest video",
            "video",
            {"prompt": "Quiet forest", "duration_seconds": 10},
        ),
    ],
)
def test_scheduled_media_uses_only_factory_model_and_never_generates_or_enables(
    monkeypatch, implemented_media, text, kind, media_request
):
    calls = []

    async def stream(_self, **params):
        if params["messages"][0]["content"].startswith("Infer the user's requested outcomes"):
            yield json.dumps(
                {
                    "reason": "Interpret the current request",
                    "outcomes": [
                        {"kind": "agent_draft", "count": 1, "description": "A disabled recurring agent"}
                    ],
                }
            )
            return
        calls.append(params)
        if params["messages"][0]["content"].startswith("You operate AI Station"):
            context = json.loads(params["messages"][1]["content"])
            value = (
                finish(1)
                if context["observations"]
                else {
                    **tool("agent.create", instruction=text),
                    "outcomes": [
                        {"kind": "agent_draft", "count": 1, "description": "A recurring creative agent"}
                    ],
                }
            )
            value.pop("outcomes", None)  # Intent is independently frozen before tool selection.
            yield json.dumps(value)
            return
        yield json.dumps(
            {
                "name": "Recurring creative work",
                "goal": "Create a fresh local result",
                "tools": ["create_media"],
                "media": {"kind": kind, "description_source": "goal", "request": media_request},
                "trigger": "interval",
                "interval_seconds": 900,
            }
        )

    async def no_search(*_args, **_kwargs):
        pytest.fail("Preparing a scheduled agent must not search the instruction")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", no_search)
    with TestClient(app) as client:
        request_id = str(uuid4())
        result = submit(client, text, client_request_id=request_id, web_search={"enabled": True})
        root = result["run"]
        assert root["executor_type"] == "assistant_controller"
        assert "manage_agents" not in root["effective_permissions"]
        assert not calls
        drain()
        reset_engine()
        with session_factory()() as db:
            agents = list(db.scalars(select(Agent)))
            assert len(agents) == 1
            agent = agents[0]
            assert (agent.trigger == "interval" and agent.interval_seconds == 900) or (
                agent.trigger == "cron" and agent.cron_expr == "*/15 * * * *"
            )
            assert not agent.enabled and agent.next_run_at is None
            assert agent.tools == ["create_media"] and agent.media["kind"] == kind
            assert all(r.status == "succeeded" for r in db.scalars(select(Run)))
            factory = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
            assert "manage_agents" in factory.effective_permissions
        detail = client.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert detail["messages"][-1]["controller_steps"][0]["agent_draft"]["agent_id"] == agent.id
        assert len(calls) == 3, "Two decisions and one factory inference, without public search"
        assert work() is None
        replay = submit(client, text, client_request_id=request_id, web_search={"enabled": True})
        assert replay["run"]["id"] == root["id"]
        assert work() is None and len(calls) == 3


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("Jak generować zdjęcie co 15 minut?", "auto"),
        ('"Co 15 minut generuj mi zdjęcie"', "auto"),
        ("Co 15 minut nie generuj zdjęć", "auto"),
        ("co 15 minut generuj mi zdjęcie", "chat"),
    ],
)
def test_recurring_topics_and_explicit_conversation_override_keep_reply_policy(monkeypatch, text, action):
    async def stream(_self, **params):
        if params["messages"][0]["content"].startswith("Infer the user's requested outcomes"):
            yield json.dumps(
                {
                    "reason": "Answer the question",
                    "outcomes": [{"kind": "text", "count": 1, "description": "A normal reply"}],
                }
            )
            return
        if params["messages"][0]["content"].startswith("You operate AI Station"):
            yield json.dumps(
                {
                    **tool("chat.reply", instruction="Answer the user's question without executing an agent"),
                    "outcomes": [{"kind": "text", "count": 1, "description": "A normal reply"}],
                }
            )
        else:
            yield "A normal reply"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        result = submit(client, text, action=action)
        assert result["run"]["executor_type"] == ("chat" if action == "chat" else "assistant_controller")
        assert "manage_agents" not in result["run"]["effective_permissions"]
        drain()
        with session_factory()() as db:
            assert not list(db.scalars(select(Agent)))
            assert not any(r.executor_type == "agent_draft" for r in db.scalars(select(Run)))
