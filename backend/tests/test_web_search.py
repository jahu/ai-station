import asyncio

import httpx
import pytest
from app import web_search
from app.api import app
from app.config import clear_settings_cache
from app.db import reset_engine, session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient

RESULT = {
    "query": "llama.cpp GPUs",
    "provider": "searxng",
    "searched_at": "2026-09-29T00:00:00Z",
    "partial": False,
    "sources": [
        {
            "id": 1,
            "title": "llama.cpp",
            "url": "https://github.com/ggml-org/llama.cpp",
            "snippet": "Multi-GPU inference",
        }
    ],
}


def step():
    with session_factory()() as session:
        return tick(session, "search-test")


@pytest.fixture
def inference(monkeypatch):
    seen = []

    async def stream(self, **params):
        seen.append(params)
        yield "Supported by [llama.cpp](https://github.com/ggml-org/llama.cpp)."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return seen


def conversation(client, mode="local"):
    response = client.post("/api/chat/conversations", json={"model": "fixture-model", "execution_mode": mode})
    assert response.status_code == 201, response.text
    return "/api/chat/conversations/" + response.json()["id"]


@pytest.mark.parametrize("mode", ["local", "orchestrator"])
def test_search_is_opt_in_audited_and_persisted(mode, monkeypatch, inference):
    queries = []

    async def search(query):
        queries.append(query)
        return RESULT

    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        route = conversation(client, mode)
        body = {
            "content": "My private instructions: explain the results",
            "web_search": {"enabled": True, "query": "llama.cpp GPUs"},
        }
        queued = client.post(route + "/messages", json=body)
        assert queued.status_code == 202, queued.text
        step()
        if mode == "orchestrator":
            step()
        detail = client.get(route).json()
        answer = detail["messages"][-1]
        assert answer["run_status"] == "succeeded", answer
        assert answer["metadata"]["web_search"]["sources"] == RESULT["sources"]
        run = client.get("/api/runs/" + answer["run_id"]).json()
        assert run["effective_permissions"] == ["network_read"]
        events = client.get("/api/runs/" + run["id"] + "/stream").text
        assert "tool.started" in events and "tool.completed" in events
        artifact = client.get("/api/artifacts?run_id=" + run["id"]).json()[0]
        assert client.get("/api/artifacts/" + artifact["id"] + "/file").json() == RESULT
        assert "untrusted search snippets" in inference[0]["messages"][-1]["content"]
        assert queries == ["llama.cpp GPUs"]
        reset_engine()
        assert (
            client.get(route).json()["messages"][-1]["metadata"]["web_search"]["sources"] == RESULT["sources"]
        )
        if mode == "local":
            response = client.post(route + "/regenerate")
            assert response.status_code == 202
            step()
            assert queries == ["llama.cpp GPUs"] * 2
        # The next ordinary message must not inherit network permission or run another search.
        client.post(
            route + "/messages",
            json={"content": "Explain again", **({"action": "chat"} if mode == "orchestrator" else {})},
        )
        step()
        if mode == "orchestrator":
            step()
        assert len(queries) == (2 if mode == "local" else 1)


@pytest.mark.parametrize("mode", ["cancel", "fail", "missing_permission"])
def test_search_failure_cancellation_and_permission_do_not_generate_answer(mode, monkeypatch, inference):
    closed = []

    async def search(query):
        if mode == "missing_permission":
            raise AssertionError("Search must not execute without permission")
        if mode == "fail":
            raise ProviderError("Search service unavailable")
        try:
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            await asyncio.Future()
        finally:
            closed.append(True)

    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        route = conversation(client)
        response = client.post(
            route + "/messages", json={"content": "Search", "web_search": {"enabled": True}}
        )
        run_id = response.json()["id"]
        if mode == "missing_permission":
            with session_factory()() as session:
                session.get(Run, run_id).effective_permissions = []
                session.commit()
        step()
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == ("canceled" if mode == "cancel" else "failed"), run
        assert inference == []
        if mode == "cancel":
            assert closed
        if mode == "fail":
            assert "tool.failed" in client.get("/api/runs/" + run_id + "/stream").text


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://127.0.0.1/a",
        "http://[::1]/",
        "http://169.254.169.254/",
        "https://user:secret@example.com/",
        "http://2130706433/",
        "https://service.internal/",
        "https://example.com:8080/",
        "https://example.com/\nattack",
    ],
)
def test_result_links_reject_unsafe_targets(url):
    assert web_search.public_link(url) is None


@pytest.mark.asyncio
async def test_provider_caps_results_and_sends_only_query(monkeypatch):
    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    original = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        rows = [{"title": "<b>Unsafe</b>", "url": "http://localhost/", "content": "private"}]
        rows += [
            {"title": "<b>Source</b>", "url": f"https://example.com/{i}", "content": "x" * 1000}
            for i in range(10)
        ]
        return httpx.Response(200, json={"results": rows, "unresponsive_engines": [["engine", "timeout"]]})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )
    result = await web_search.search("public query")
    assert len(result["sources"]) == 5
    assert result["partial"]
    assert result["sources"][0]["title"] == "Source"
    assert len(result["sources"][0]["snippet"]) == 700
    assert requests[0].url == "http://search:8080/search"
    assert requests[0].content == b"q=public+query&format=json&categories=general"
    assert "authorization" not in requests[0].headers


def test_query_validation_and_action_conflicts():
    with TestClient(app) as client:
        route = conversation(client, "orchestrator")
        for body in [
            {"content": "x" * 501, "web_search": {"enabled": True}},
            {"content": "Search", "web_search": {"enabled": True, "url": "http://localhost"}},
            {"content": "Create an image", "action": "image.generate", "web_search": {"enabled": True}},
        ]:
            response = client.post(route + "/messages", json=body)
            assert response.status_code == 422, response.text
        assert client.get(route).json()["messages"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["redirect", "oversize", "all_failed", "malformed"])
async def test_search_rejects_provider_failures(monkeypatch, failure):
    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    original = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        if failure == "malformed":
            return httpx.Response(200, content=b"not JSON")
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [["engine", "timeout"]]})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handle))
    )
    with pytest.raises(ProviderError):
        await web_search.search("test")
    assert len(calls) == 1
