import asyncio
import json

import httpx
import pytest
from ai_station_runner import local_model
from ai_station_runner.app import app
from ai_station_runner.config import clear_settings_cache
from fastapi.testclient import TestClient
from starlette.requests import Request

ENDPOINT = "http://127.0.0.1:11434/v1"
HEADERS = {"X-AI-Station-Endpoint": ENDPOINT}
BODY = {
    "model": "fake",
    "messages": [{"role": "user", "content": "Hi"}],
    "temperature": 0.3,
    "max_tokens": 100,
    "stream": True,
}


@pytest.fixture(autouse=True)
def local_settings(monkeypatch):
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", ENDPOINT)
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "test-secret")
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_models_only_returns_names_and_never_credentials(monkeypatch):
    def handler(request):
        assert str(request.url) == ENDPOINT + "/models"
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"data": [{"id": "fake", "token": "server-secret"}]})

    monkeypatch.setattr(
        local_model, "upstream_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    response = TestClient(app).get("/v1/llm/models", headers=HEADERS)
    assert response.json() == {"data": [{"id": "fake"}]}
    assert "secret" not in response.text


def test_stream_closes_upstream_on_completion_and_partial_close(monkeypatch):
    streams, clients = [], []

    class Stream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    def handler(request):
        assert str(request.url) == ENDPOINT + "/chat/completions"
        assert json.loads(request.content) == BODY
        stream = Stream()
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)

    def client():
        value = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(value)
        return value

    monkeypatch.setattr(local_model, "upstream_client", client)
    response = TestClient(app).post("/v1/llm/chat/completions", headers=HEADERS, json=BODY)
    assert "[DONE]" in response.text and streams[0].closed and clients[0].is_closed

    async def disconnect():
        response = await local_model.completion(
            local_model.Completion(**BODY), ENDPOINT, Request({"type": "http"})
        )
        await anext(response.body_iterator)
        await response.body_iterator.aclose()

    asyncio.run(disconnect())
    assert streams[1].closed and clients[1].is_closed


def test_cancellation_before_headers_closes_client(monkeypatch):
    clients = []

    async def exercise():
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.sleep(30)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(local_model, "upstream_client", lambda: client)
        task = asyncio.create_task(
            local_model.completion(local_model.Completion(**BODY), ENDPOINT, Request({"type": "http"}))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert clients[0].is_closed


def test_rejects_arbitrary_endpoint_tools_and_redirect(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/secret"})

    monkeypatch.setattr(
        local_model,
        "upstream_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    api = TestClient(app)
    assert (
        api.get("/v1/llm/models", headers={"X-AI-Station-Endpoint": "http://localhost/other"}).status_code
        == 409
    )
    assert not calls
    assert (
        api.post("/v1/llm/chat/completions", headers=HEADERS, json={**BODY, "tools": []}).status_code == 422
    )
    assert (
        api.post(
            "/v1/llm/chat/completions",
            headers=HEADERS,
            json={**BODY, "messages": [{"role": "tool", "content": "x"}]},
        ).status_code
        == 422
    )
    assert api.get("/v1/llm/models", headers=HEADERS).status_code == 502
    assert len(calls) == 1
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", "https://example.com/v1")
    clear_settings_cache()
    assert (
        api.get("/v1/llm/models", headers={"X-AI-Station-Endpoint": "https://example.com/v1"}).status_code
        == 409
    )
    assert len(calls) == 1


def test_disconnect_before_provider_headers_cancels_upstream(monkeypatch):
    async def exercise():
        stopped = asyncio.Event()

        async def handler(request):
            try:
                await asyncio.sleep(30)
            finally:
                stopped.set()

        async def receive():
            return {"type": "http.disconnect"}

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(local_model, "upstream_client", lambda: client)
        with pytest.raises(local_model.HTTPException) as error:
            await asyncio.wait_for(
                local_model.completion(
                    local_model.Completion(**BODY), ENDPOINT, Request({"type": "http"}, receive)
                ),
                timeout=2,
            )
        assert error.value.status_code == 499
        assert stopped.is_set() and client.is_closed

    asyncio.run(exercise())


def test_reasoning_is_bounded_and_not_forwarded_to_unqualified_local_endpoint():
    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/llm/chat/completions",
                headers=HEADERS,
                json={**BODY, "max_tokens": 768, "reasoning": {"enabled": True, "budget": 128}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/llm/chat/completions",
                headers=HEADERS,
                json={**BODY, "reasoning": {"enabled": True, "budget": 128}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/llm/chat/completions",
                headers=HEADERS,
                json={**BODY, "max_tokens": 768, "reasoning": {"enabled": "yes", "budget": 128}},
            ).status_code
            == 422
        )


@pytest.mark.parametrize("enabled", [False, True])
def test_owned_forwarding_maps_only_typed_reasoning_fields(enabled):
    recorded = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: [DONE]\n\n"

    def handler(request):
        recorded.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = await local_model.forward_completion(
            local_model.Completion(
                **{**BODY, "max_tokens": 768, "reasoning": {"enabled": enabled, "budget": 128}}
            ),
            Request({"type": "http"}),
            "http://llama/v1",
            client,
            {},
        )
        async for _ in response.body_iterator:
            pass
        assert client.is_closed

    asyncio.run(run())
    assert recorded[0]["chat_template_kwargs"] == {"enable_thinking": enabled}
    assert recorded[0]["reasoning_budget_tokens"] == (128 if enabled else 0)
    assert recorded[0]["reasoning_format"] == "deepseek" and "reasoning" not in recorded[0]
    assert ("reasoning_effort" in recorded[0]) == (not enabled)


@pytest.mark.parametrize("enabled", [False, True])
def test_json_object_output_is_typed_and_omitted_from_legacy_requests(enabled):
    captured = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: [DONE]\n\n"

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = await local_model.forward_completion(
            local_model.Completion(**BODY, json_output=enabled),
            Request({"type": "http"}),
            "http://llama/v1",
            client,
            {},
        )
        async for _ in response.body_iterator:
            pass
        assert client.is_closed

    asyncio.run(exercise())
    expected = {**BODY, **({"response_format": {"type": "json_object"}} if enabled else {})}
    assert captured == [expected]


@pytest.mark.parametrize("flag", ["true", 1, {}, None])
def test_json_output_rejects_untyped_flags(flag):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        local_model.Completion(**BODY, json_output=flag)
