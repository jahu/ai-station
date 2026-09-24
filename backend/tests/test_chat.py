import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from app.api import app
from app.config import clear_settings_cache
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider, local_endpoint
from app.models import Run
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient


class Stream(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        for token in ["Hello ", "**world**"]:
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": token}}]}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


@pytest.fixture
def provider(monkeypatch):
    client = httpx.AsyncClient
    stream = Stream()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=transport))
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["local-model"])
    return stream, requests


def new_conversation(client):
    result = client.post(
        "/api/chat/conversations", json={"model": "local-model", "system_prompt": "Be concise"}
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_chat_persistence_context_regeneration_and_sse(provider):
    stream, requests = provider
    with TestClient(app) as client:
        assert client.get("/api/chat/provider").json()["location"] == "local"
        conversation_id = new_conversation(client)
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()
        assert run["status"] == "queued"
        assert run["parameters"]["messages"] == [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hi"},
        ]
        with session_factory()() as session:
            tick(session, "chat-test")
        assert stream.closed
        assert json.loads(requests[0].content)["model"] == "local-model"
        detail = client.get(f"/api/chat/conversations/{conversation_id}").json()
        assert detail["messages"][-1]["content"] == "Hello **world**"
        assert detail["messages"][-1]["run_status"] == "succeeded"
        assert detail["messages"][-1]["metadata"]["partial"] is False
        assert "chat.delta" in client.get(f"/api/runs/{run['id']}/stream").text
        reset_engine()
        assert (
            client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"] == detail["messages"]
        )
        retry = client.post(f"/api/chat/conversations/{conversation_id}/regenerate").json()
        assert retry["parent_run_id"] == run["id"]
        assert retry["task_id"] == run["task_id"]
        assert retry["parameters"]["messages"] == run["parameters"]["messages"]
        history = client.get(f"/api/chat/conversations/{conversation_id}").json()["messages"]
        assert history[1]["metadata"]["superseded"] is True


def test_only_one_active_run_per_conversation(provider):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        barrier = Barrier(2)

        def send():
            barrier.wait()
            return client.post(
                f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(lambda _: send(), range(2)))
        assert sorted(codes) == [202, 409]
        assert (
            client.patch(f"/api/chat/conversations/{conversation_id}", json={"model": "other"}).status_code
            == 409
        )
        assert client.post(f"/api/chat/conversations/{conversation_id}/regenerate").status_code == 409


def test_cancel_silent_provider_closes_connection(monkeypatch, provider):
    stopped = []

    async def silent(self, **kwargs):
        try:
            with session_factory()() as other:
                run = other.get(Run, run_id)
                request_cancel(other, run)
                other.commit()
            await asyncio.Event().wait()
            yield "never"
        finally:
            stopped.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run_id = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()["id"]
        with session_factory()() as session:
            tick(session, "chat-test")
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "canceled"
        assert stopped == [True]


def test_partial_output_survives_provider_failure(monkeypatch, provider):
    async def broken(self, **kwargs):
        yield "Preserved partial response"
        raise ProviderError("Stream disconnected")

    monkeypatch.setattr(LocalChatProvider, "stream", broken)
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run_id = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()["id"]
        with session_factory()() as session:
            tick(session, "chat-test")
        detail = client.get(f"/api/chat/conversations/{conversation_id}").json()
        assert detail["messages"][-1]["content"] == "Preserved partial response"
        assert detail["messages"][-1]["metadata"]["partial"] is True
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com/v1",
        "http://169.254.169.254/v1",
        "http://user:secret@localhost/v1",
        "http://8.8.8.8/v1",
        "file:///etc/passwd",
    ],
)
def test_local_chat_rejects_external_or_credential_urls(monkeypatch, url):
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", url)
    clear_settings_cache()
    with pytest.raises(ProviderError):
        local_endpoint()
    with TestClient(app) as client:
        assert client.post("/api/chat/conversations", json={"model": "local-model"}).status_code == 409


def test_endpoint_change_does_not_reroute_queued_prompt(provider, monkeypatch):
    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Hi"}
        ).json()
        monkeypatch.setenv("AI_STATION_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        clear_settings_cache()
        with session_factory()() as session:
            tick(session, "chat-test")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        assert provider[1] == []


@pytest.mark.parametrize(
    "records",
    [
        b"data: bad-json\n\n",
        b'data: {"error":{"message":"secret"}}\n\n',
        b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
    ],
)
def test_incomplete_or_invalid_provider_stream_fails(records, monkeypatch):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=records))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs, transport=transport))

    async def consume():
        return [
            piece
            async for piece in LocalChatProvider().stream(
                endpoint=local_endpoint(), messages=[], model="m", temperature=0.7, max_tokens=20
            )
        ]

    with pytest.raises(ProviderError):
        asyncio.run(consume())


@pytest.mark.parametrize(
    "url", ["http://[::1]:8080/v1", "http://192.168.1.4:8080/v1", "http://host.docker.internal:8080/v1"]
)
def test_local_endpoint_forms(url, monkeypatch):
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", url)
    clear_settings_cache()
    assert local_endpoint() == url


def test_context_window_preserves_valid_turn_order(provider):
    from app.models import Message

    with TestClient(app) as client:
        conversation_id = new_conversation(client)
        with session_factory()() as session:
            for index in range(12):
                for role in ("user", "assistant"):
                    session.add(
                        Message(
                            conversation_id=conversation_id,
                            role=role,
                            content=f"{role} {index}",
                            metadata_json={},
                        )
                    )
                    session.flush()
            session.commit()
        run = client.post(
            f"/api/chat/conversations/{conversation_id}/messages", json={"content": "Latest question"}
        ).json()
        messages = run["parameters"]["messages"]
        assert len(messages) <= 17
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[-1]["content"] == "Latest question"
        assert all(a["role"] != b["role"] for a, b in zip(messages[1:], messages[2:]))
