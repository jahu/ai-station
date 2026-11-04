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
        calls.append(params)
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
        assert root["executor_type"] == "orchestrator"
        assert "manage_agents" in root["effective_permissions"]
        assert root["parameters"]["web_search"]["enabled"] is False
        assert not calls
        assert work() == root["id"]
        with session_factory()() as db:
            parent = db.get(Run, root["id"])
            child = db.get(Run, parent.metadata_json["child_run_id"])
            assert child.executor_type == "agent_draft"
            assert child.task_id == parent.task_id and child.parent_run_id == parent.id
            child_id = child.id
        assert work() == child_id
        reset_engine()
        with session_factory()() as db:
            agents = list(db.scalars(select(Agent)))
            assert len(agents) == 1
            agent = agents[0]
            assert agent.trigger == "interval" and agent.interval_seconds == 900
            assert not agent.enabled and agent.next_run_at is None
            assert agent.tools == ["create_media"] and agent.media["kind"] == kind
            assert {r.executor_type for r in db.scalars(select(Run))} == {"orchestrator", "agent_draft"}
            assert all(r.status == "succeeded" for r in db.scalars(select(Run)))
        detail = client.get("/api/chat/conversations/" + result["conversation_id"]).json()
        assert detail["messages"][-1]["metadata"]["agent_id"] == agent.id
        assert len(calls) == 1, "Only agent-factory inference, no classifier or ordinary reply"
        assert work() is None, "The disabled agent does not launch media or scheduled work"
        replay = submit(client, text, client_request_id=request_id, web_search={"enabled": True})
        assert replay["run"]["id"] == root["id"]
        assert work() is None and len(calls) == 1


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
    async def stream(_self, **_params):
        yield "A normal reply"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        result = submit(client, text, action=action)
        assert result["run"]["executor_type"] == "chat"
        assert "manage_agents" not in result["run"]["effective_permissions"]
        work()
        with session_factory()() as db:
            assert not list(db.scalars(select(Agent)))
            assert {r.executor_type for r in db.scalars(select(Run))} == {"chat"}
