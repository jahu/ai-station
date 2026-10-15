import asyncio
import json

import httpx
import pytest
from app.config import clear_settings_cache
from app.local_provider import LocalChatProvider, local_endpoint


def test_runner_transport_uses_private_socket_and_expected_host_endpoint(monkeypatch):
    monkeypatch.setenv("AI_STATION_LLM_TRANSPORT", "runner")
    monkeypatch.setenv("AI_STATION_LLM_HOST_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "must-not-forward")
    monkeypatch.setenv("AI_STATION_RUNNER_SOCKET", "/private/runner.sock")
    clear_settings_cache()
    transports, requests = [], []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "fake"}]})
        return httpx.Response(200, stream=Stream())

    def transport(**kwargs):
        transports.append(kwargs)
        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)
    provider = LocalChatProvider()
    assert provider.models() == ["fake"]

    async def complete():
        return [
            token
            async for token in provider.stream(
                endpoint=local_endpoint(),
                messages=[{"role": "user", "content": "Hi"}],
                model="fake",
                temperature=0,
                max_tokens=100,
            )
        ]

    assert asyncio.run(complete()) == ["Hi"]
    assert transports == [{"uds": "/private/runner.sock"}] * 2
    assert str(requests[0].url) == "http://runner/v1/llm/models"
    assert str(requests[1].url) == "http://runner/v1/llm/chat/completions"
    assert all(
        request.headers["X-AI-Station-Endpoint"] == "http://127.0.0.1:11434/v1" for request in requests
    )
    assert all("authorization" not in request.headers for request in requests)
    assert "endpoint" not in json.loads(requests[1].content)


@pytest.mark.parametrize("target", ["configured_runner", "owned_runner", "direct_compatible"])
@pytest.mark.parametrize("json_output", [False, True])
def test_json_output_reaches_only_the_selected_inference_target(monkeypatch, target, json_output):
    monkeypatch.setenv("AI_STATION_LLM_TRANSPORT", "runner" if target == "configured_runner" else "direct")
    monkeypatch.setenv("AI_STATION_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("AI_STATION_LLM_HOST_BASE_URL", "http://127.0.0.1:11434/v1")
    clear_settings_cache()
    captured = []
    instance = "12345678-1234-4234-8234-123456789abc"

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"{\\"action\\":\\"chat\\"}"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    def reply(request):
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, stream=Stream())

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(reply)})
    )

    async def generate():
        return [
            part
            async for part in LocalChatProvider().stream(
                endpoint="llamacpp:" + instance if target == "owned_runner" else "http://127.0.0.1:11434/v1",
                model="llamacpp:stored-file" if target == "owned_runner" else "local-model",
                messages=[{"role": "user", "content": "Return JSON"}],
                temperature=0,
                max_tokens=512,
                headers={},
                json_output=json_output,
            )
        ]

    assert asyncio.run(generate()) == ['{"action":"chat"}']
    url, body = captured[0]
    if target.endswith("runner"):
        assert url.startswith("http://runner/")
        assert (body.get("json_output") is True) == json_output
        assert "response_format" not in body
    else:
        assert url == "http://127.0.0.1:11434/v1/chat/completions"
        assert "json_output" not in body
        assert body.get("response_format") == ({"type": "json_object"} if json_output else None)
