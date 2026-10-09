import asyncio
import json

import httpx
import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider, local_endpoint
from app.providers import ProviderError
from fastapi.testclient import TestClient


def drain(session, worker="tool-call-test", limit=30):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def create(api, **extra):
    result = api.post(
        "/api/agents",
        json={"name": "Caller", "goal": "Summarize available context", "model": "fake-local", **extra},
    )
    assert result.status_code == 201, result.text
    return result.json()


def run_now(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def workflow_step(api, parent_id, key):
    parent = api.get("/api/runs/" + parent_id).json()
    step = next(item for item in parent["workflow"]["steps"] if item["key"] == key)
    return api.get("/api/runs/" + step["run_id"]).json()


def test_legacy_agents_keep_tool_calling_off_and_reject_unknown_mode():
    api = TestClient(app)
    agent = create(api)
    assert agent["tool_calling"] == "none"
    rejected = api.post(
        "/api/agents",
        json={
            "name": "Bad",
            "goal": "Report",
            "model": "fake-local",
            "tool_calling": "unrestricted",
        },
    )
    assert rejected.status_code == 422


def test_factory_mentions_bounded_calling_but_stays_disabled():
    api = TestClient(app)
    draft = api.post(
        "/api/agents/draft",
        json={"instruction": "Call tools to summarize GPU workstation status", "model": "fake-local"},
    ).json()
    assert draft["enabled"] is False
    assert draft["tool_calling"] == "bounded"
    assert draft["tools"] == ["system_snapshot"]
    silent = api.post(
        "/api/agents/draft",
        json={"instruction": "Every morning check GPU workstation status", "model": "fake-local"},
    ).json()
    assert silent["tool_calling"] == "none"


def test_bounded_report_executes_registry_calls_with_events_and_artifacts(monkeypatch):
    from app.runner_client import RunnerClient

    hardware = []
    monkeypatch.setattr(RunnerClient, "hardware", lambda self: hardware.append({"ok": True}) or {"ok": True})
    rounds = {"n": 0}

    async def stream(self, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            assert kwargs.get("tools")
            assert {item["function"]["name"] for item in kwargs["tools"]} == {"system_snapshot"}
            kwargs["on_tool_calls"]([{"id": "c1", "name": "system_snapshot", "arguments": "{}"}])
            return
        assert kwargs.get("tools")
        yield "Report after the extra snapshot."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot"], tool_calling="bounded")
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    parent = api.get("/api/runs/" + queued["id"]).json()
    report = workflow_step(api, queued["id"], "report")
    assert parent["workflow"]["tool_calling"] == "bounded"
    assert parent["status"] == "succeeded" and report["status"] == "succeeded"
    assert hardware == [{"ok": True}, {"ok": True}]
    assert report["metadata"]["tool_calls"] == [
        {"id": "c1", "tool": "system_snapshot", "arguments": {}, "round": 0}
    ]
    assert parent["workflow"]["steps"][1]["tool_calls"][0]["tool"] == "system_snapshot"
    types = {item["type"] for item in api.get("/api/artifacts?run_id=" + report["id"]).json()}
    assert types == {"json", "markdown"}
    events = api.get("/api/runs/" + report["id"] + "/stream").text
    assert "tool.requested" in events and "tool.completed" in events


def test_invented_tool_call_fails_closed_without_executing(monkeypatch):
    async def stream(self, **kwargs):
        kwargs["on_tool_calls"]([{"id": "bad", "name": "shell", "arguments": "{}"}])
        return
        yield

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"], tool_calling="bounded")
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    report = workflow_step(api, queued["id"], "report")
    assert report["status"] == "failed"
    assert "invented" in report["error_message"].lower() or "unauthorized" in report["error_message"].lower()
    assert not report["metadata"].get("tool_calls")


def test_model_cannot_choose_fetch_url_or_search_query(monkeypatch):
    from app import http_fetch

    fetched = []

    async def fake_fetch(session, run, urls, **kwargs):
        fetched.append(list(urls))
        return {"urls": urls, "pages": []}

    async def stream(self, **kwargs):
        kwargs["on_tool_calls"](
            [{"id": "c1", "name": "http_fetch", "arguments": json.dumps({"url": "https://evil.example"})}]
        )
        return
        yield

    monkeypatch.setattr(http_fetch, "execute_fetch", fake_fetch)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(
        api,
        enabled=True,
        tools=["http_fetch"],
        fetch_urls=["https://example.com/public"],
        tool_calling="bounded",
    )
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    report = workflow_step(api, queued["id"], "report")
    assert report["status"] == "failed"
    assert "cannot choose" in report["error_message"].lower()
    assert fetched == [["https://example.com/public"]]


def test_off_mode_does_not_send_tools(monkeypatch):
    seen = []

    async def complete(self, **kwargs):
        seen.append(kwargs.get("tools"))
        yield "Plain report"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    assert workflow_step(api, queued["id"], "report")["status"] == "succeeded"
    assert seen == [None]


def test_provider_assembles_streamed_tool_calls_and_rejects_unexpected_ones(monkeypatch):
    requests = []
    tools = [
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "memory_", "arguments": ""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"name": "search", "arguments": "{}"}}]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks:
                yield ("data: " + json.dumps(chunk) + "\n").encode()
            yield b"data: [DONE]\n"

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=Stream())

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(**kwargs, transport=transport))
    collected = []

    async def consume(**extra):
        return [
            piece
            async for piece in LocalChatProvider().stream(
                endpoint=local_endpoint(),
                messages=[],
                model="m",
                temperature=0.3,
                max_tokens=20,
                **extra,
            )
        ]

    assert asyncio.run(consume(tools=tools, on_tool_calls=collected.extend)) == []
    assert requests[0]["tools"] == tools
    assert collected == [{"id": "c1", "name": "memory_search", "arguments": "{}"}]
    with pytest.raises(ProviderError, match="cannot use"):
        asyncio.run(consume(tools=tools))
