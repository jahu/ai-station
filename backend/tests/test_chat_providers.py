import json

import httpx
import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from fastapi.testclient import TestClient


class Stream(httpx.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        yield ("data: " + json.dumps({"choices": [{"delta": {"content": "Hello"}}]}) + "\n\n").encode()
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


def _builtin(client):
    row = client.get("/api/chat/provider").json()
    assert row["key"] == LocalChatProvider.key
    assert row["location"] == "local"
    assert row["builtin"] is True
    assert "secret" not in row
    return row


def test_builtin_provider_is_seeded_without_secret_value(provider):
    with TestClient(app) as client:
        row = _builtin(client)
        listed = client.get("/api/chat/providers").json()
        assert listed[0]["key"] == row["key"]
        assert listed[0]["secret_source"] == "none"
        assert listed[0]["secret_present"] is False
        assert (
            client.post("/api/chat/conversations", json={"model": "local-model"}).json()["provider"]
            == LocalChatProvider.key
        )


def test_external_provider_uses_secret_reference_not_plaintext(provider, monkeypatch):
    monkeypatch.setenv("AI_STATION_OPENAI_API_KEY", "sk-test-secret-value")
    with TestClient(app) as client:
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "openai",
                "name": "OpenAI",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
                "default_model": "gpt-test",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        dumped = json.dumps(body)
        assert "sk-test-secret-value" not in dumped
        assert body["secret_ref"] == "env:AI_STATION_OPENAI_API_KEY"
        assert body["secret_source"] == "env"
        assert body["secret_present"] is True
        assert body["location"] == "external"
        conversation = client.post(
            "/api/chat/conversations",
            json={"provider": "openai", "model": "gpt-test"},
        )
        assert conversation.status_code == 201, conversation.text
        assert conversation.json()["provider"] == "openai"
        run = client.post(
            f"/api/chat/conversations/{conversation.json()['id']}/messages",
            json={"content": "Hi"},
        )
        assert run.status_code == 202, run.text
        assert run.json()["effective_permissions"] == ["external_ai"]
        assert run.json()["parameters"]["secret_ref"] == "env:AI_STATION_OPENAI_API_KEY"
        assert "sk-test-secret-value" not in json.dumps(run.json())
        with session_factory()() as session:
            tick(session, "chat-providers")
        assert provider[1]
        assert provider[1][0].headers["Authorization"] == "Bearer sk-test-secret-value"
        events = client.get(f"/api/runs/{run.json()['id']}/events").json()
        assert "sk-test-secret-value" not in json.dumps(events)


def test_missing_secret_fails_closed(provider, monkeypatch):
    monkeypatch.delenv("AI_STATION_OPENAI_API_KEY", raising=False)
    with TestClient(app) as client:
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "openai",
                "name": "OpenAI",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
            },
        )
        assert created.status_code == 201
        assert created.json()["secret_present"] is False
        assert created.json()["status"] == "unavailable"
        blocked = client.post(
            "/api/chat/conversations",
            json={"provider": "openai", "model": "gpt-test"},
        )
        assert blocked.status_code == 409
        assert "secret" in blocked.json()["detail"].lower()
        assert "sk-" not in blocked.json()["detail"]


def test_stored_secret_is_write_only_and_never_returned(provider):
    with TestClient(app) as client:
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "cloud",
                "name": "Cloud",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret": "sk-stored-never-echo",
                "default_model": "cloud-model",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["secret_source"] == "stored"
        assert body["secret_ref"] == ""
        assert body["secret_present"] is True
        assert "sk-stored-never-echo" not in json.dumps(body)
        detail = client.get(f"/api/chat/providers/{body['id']}").json()
        assert "sk-stored-never-echo" not in json.dumps(detail)
        conversation = client.post(
            "/api/chat/conversations",
            json={"provider": "cloud", "model": "cloud-model"},
        ).json()
        run = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages", json={"content": "Hi"}
        ).json()
        with session_factory()() as session:
            tick(session, "chat-providers")
        assert provider[1][0].headers["Authorization"] == "Bearer sk-stored-never-echo"
        assert "sk-stored-never-echo" not in json.dumps(run)


def test_rejects_plaintext_keys_in_urls_and_secret_ref():
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/chat/providers",
                json={
                    "key": "bad-url",
                    "name": "Bad",
                    "location": "external",
                    "endpoint": "https://user:sk-secret@api.example.test/v1",
                    "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/chat/providers",
                json={
                    "key": "bad-ref",
                    "name": "Bad",
                    "location": "external",
                    "endpoint": "https://api.example.test/v1",
                    "secret_ref": "sk-this-is-a-key",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/chat/providers",
                json={
                    "key": "http-cloud",
                    "name": "Bad",
                    "location": "external",
                    "endpoint": "http://api.example.test/v1",
                    "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
                },
            ).status_code
            == 422
        )


def test_cannot_delete_builtin_or_put_llama_on_external(provider, monkeypatch):
    monkeypatch.setenv("AI_STATION_OPENAI_API_KEY", "sk-test")
    with TestClient(app) as client:
        builtin = client.get("/api/chat/providers").json()[0]
        assert client.delete(f"/api/chat/providers/{builtin['id']}").status_code == 409
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "openai",
                "name": "OpenAI",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
            },
        ).json()
        assert (
            client.post(
                "/api/chat/conversations",
                json={"provider": "openai", "model": "llamacpp:not-a-model"},
            ).status_code
            == 409
        )
        conversation = client.post(
            "/api/chat/conversations",
            json={"provider": "openai", "model": "gpt-test"},
        ).json()["id"]
        assert client.delete(f"/api/chat/providers/{created['id']}").status_code == 409
        client.patch(
            f"/api/chat/conversations/{conversation}",
            json={
                "provider": LocalChatProvider.key,
                "model": "local-model",
                "title": "Moved",
                "system_prompt": "",
                "temperature": 0.7,
                "max_tokens": 32,
            },
        )
        assert client.delete(f"/api/chat/providers/{created['id']}").status_code == 204


def test_missing_or_replaced_secret_fails_queued_external_run(provider, monkeypatch):
    monkeypatch.setenv("AI_STATION_OPENAI_API_KEY", "sk-original")
    with TestClient(app) as client:
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "openai",
                "name": "OpenAI",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
                "default_model": "gpt-test",
            },
        ).json()
        conversation = client.post(
            "/api/chat/conversations", json={"provider": "openai", "model": "gpt-test"}
        ).json()["id"]
        run = client.post(f"/api/chat/conversations/{conversation}/messages", json={"content": "Hi"}).json()
        monkeypatch.setenv("AI_STATION_OTHER_KEY", "sk-other")
        patched = client.patch(
            f"/api/chat/providers/{created['id']}", json={"secret_ref": "env:AI_STATION_OTHER_KEY"}
        )
        assert patched.status_code == 200, patched.text
        with session_factory()() as session:
            tick(session, "chat-providers")
        failed = client.get(f"/api/runs/{run['id']}").json()
        assert failed["status"] == "failed"
        assert provider[1] == []
        assert "sk-original" not in json.dumps(failed)
        assert "sk-other" not in json.dumps(failed)


def test_external_model_discovery_uses_mock_not_network(monkeypatch):
    monkeypatch.setenv("AI_STATION_OPENAI_API_KEY", "sk-test")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "mock-model"}]})

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["local-model"])
    with TestClient(app) as client:
        created = client.post(
            "/api/chat/providers",
            json={
                "key": "openai",
                "name": "OpenAI",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "secret_ref": "env:AI_STATION_OPENAI_API_KEY",
            },
        ).json()
        detail = client.get(f"/api/chat/providers/{created['key']}").json()
        assert detail["models"] == ["mock-model"]
        assert requests and str(requests[0].url).startswith("https://api.example.test/v1/models")
        assert requests[0].headers["Authorization"] == "Bearer sk-test"
