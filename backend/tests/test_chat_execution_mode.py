import httpx
import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent
from fastapi.testclient import TestClient
from sqlalchemy import select


class Stream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n'
        yield b"data: [DONE]\n"


@pytest.fixture
def provider(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream()))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=transport))
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["local-model"])


def test_local_conversation_rejects_capability_actions_until_this_turn_is_assistant():
    api = TestClient(app)
    cid = api.post("/api/chat/conversations", json={"model": "fake-local"}).json()["id"]
    assert api.get(f"/api/chat/conversations/{cid}").json()["execution_mode"] == "local"
    denied = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Create a weekly GPU agent", "action": "agent.create"},
    )
    assert denied.status_code == 422
    queued = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Create a weekly GPU agent",
            "execution_mode": "orchestrator",
            "action": "agent.create",
        },
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["executor_type"] == "orchestrator"
    with session_factory()() as session:
        tick(session, "mode-test")
        agent = session.scalar(select(Agent))
        assert agent is not None and agent.enabled is False
    saved = api.get(f"/api/chat/conversations/{cid}").json()
    assert saved["execution_mode"] == "local"
    assert saved["messages"][0]["metadata"]["execution_mode"] == "orchestrator"
    assert saved["messages"][0]["metadata"]["execution_mode_override"] == "orchestrator"


def test_assistant_conversation_can_send_one_local_turn_without_changing_settings(provider):
    api = TestClient(app)
    cid = api.post(
        "/api/chat/conversations", json={"model": "local-model", "execution_mode": "orchestrator"}
    ).json()["id"]
    queued = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Hi", "execution_mode": "local"},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["executor_type"] == "chat"
    assert queued.json()["parameters"]["execution_mode"] == "local"
    with session_factory()() as session:
        tick(session, "mode-test")
    saved = api.get(f"/api/chat/conversations/{cid}").json()
    assert saved["execution_mode"] == "orchestrator"
    assert saved["messages"][0]["metadata"]["execution_mode"] == "local"
    retry = api.post(f"/api/chat/conversations/{cid}/regenerate")
    assert retry.status_code == 202, retry.text
    assert retry.json()["parent_run_id"] == queued.json()["id"]
