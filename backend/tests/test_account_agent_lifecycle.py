"""A private conversation can draft and control its own persistent agent."""

import json

from app.db import control_session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def test_member_can_create_and_pause_agent_from_private_conversation(accounts, monkeypatch):
    _, alice, bob = accounts
    calls = []

    async def draft(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(
            {"name": "Synthetic private report", "goal": "Write a short private report", "tools": []}
        )

    monkeypatch.setattr(LocalChatProvider, "stream", draft)
    conversation = alice.post(
        "/api/chat/conversations", json={"model": "synthetic-local", "execution_mode": "assistant"}
    )
    assert conversation.status_code == 201, conversation.text
    path = "/api/chat/conversations/" + conversation.json()["id"]
    created = alice.post(
        path + "/messages",
        json={
            "content": "Create an agent that writes a report",
            "action": "agent.create",
            "web_search": {"enabled": False},
        },
    )
    assert created.status_code == 202, created.text
    with control_session_factory()() as queue:
        for _ in range(6):
            if tick(queue, "private-agent-draft") is None:
                break
        else:
            raise AssertionError("Synthetic draft did not finish its bounded graph")
    detail = alice.get(path).json()
    source = next(
        message
        for message in detail["messages"]
        if message["role"] == "assistant" and message["metadata"].get("agent_id")
    )
    assert source["run_status"] == "succeeded", source
    aid = source["metadata"]["agent_id"]
    assert bob.get("/api/agents/" + aid).status_code == 404
    assert bob.get(path).status_code == 404
    assert len(calls) == 1

    async def forbidden(self, **kwargs):
        raise AssertionError("A deterministic control cannot call inference")
        yield ""

    monkeypatch.setattr(LocalChatProvider, "stream", forbidden)
    paused = alice.post(
        path + "/messages", json={"content": "Pause this agent", "web_search": {"enabled": False}}
    )
    assert paused.status_code == 202, paused.text
    with control_session_factory()() as queue:
        assert tick(queue, "private-agent-pause") == paused.json()["id"]
    result = alice.get("/api/runs/" + paused.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert result["metadata"]["agent_control_result"]["outcome"] == "paused"
    assert not alice.get("/api/agents/" + aid).json()["enabled"]
    assert bob.get("/api/runs/" + paused.json()["id"]).status_code == 404
