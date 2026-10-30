"""Initial automatic searches prepare locally before sending anything to search."""

import asyncio
import json

import pytest
from app import web_search
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient

QUESTION = "aktor grający niepełnosprawnego syna w Breaking Bad zmarł, jaka była przyczyna?"
QUERY = "Breaking Bad Walter Jr actor death report fact check"


def step():
    with session_factory()() as session:
        tick(session, "search-preparation")


def result(query):
    return {
        "query": query,
        "provider": "searxng",
        "searched_at": "2026-10-30T00:00:00Z",
        "partial": False,
        "sources": [
            {
                "id": 1,
                "title": "Synthetic fact check",
                "url": "https://example.org/check",
                "snippet": "A synthetic result, not a real claim about an actor.",
            }
        ],
    }


def queue(client, *, explicit=""):
    created = client.post(
        "/api/chat/conversations",
        json={"model": "fixture-model", "system_prompt": "SENSITIVE SYSTEM CONTEXT"},
    )
    assert created.status_code == 201, created.text
    route = "/api/chat/conversations/" + created.json()["id"]
    queued = client.post(
        route + "/messages", json={"content": QUESTION, "web_search": {"enabled": True, "query": explicit}}
    )
    assert queued.status_code == 202, queued.text
    return route, queued.json()["id"]


def test_first_query_is_prepared_before_search_and_saved_with_sources(monkeypatch):
    order, completions, queries = [], [], []

    async def stream(self, **params):
        completions.append(params)
        if params.get("json_output"):
            order.append("prepare")
            assert params["model"] == "fixture-model" and params["max_tokens"] == 256
            assert params["temperature"] == 0 and "tools" not in params
            assert params["messages"][-1]["content"] == QUESTION
            assert "SENSITIVE SYSTEM CONTEXT" not in str(params["messages"])
            assert "assume a reported event is true" in params["messages"][0]["content"]
            yield json.dumps({"query": QUERY})
        else:
            order.append("answer")
            yield "Synthetic answer with a [source](https://example.org/check)."

    async def search(query):
        order.append("search")
        queries.append(query)
        return result(query)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        route, run_id = queue(client)
        step()
        detail = client.get("/api/runs/" + run_id).json()
        assert detail["status"] == "succeeded", detail
        assert order == ["prepare", "search", "answer"] and queries == [QUERY]
        evidence = client.get(route).json()["messages"][-1]["metadata"]["web_search"]
        assert evidence["query"] == QUERY and evidence["original_query"] == QUESTION
        assert evidence["query_preparation"] == {"location": "local", "model": "fixture-model"}
        saved = client.get("/api/artifacts/" + evidence["artifact_id"] + "/file").json()
        assert saved["query_preparation"] == evidence["query_preparation"]
        events = client.get("/api/runs/" + run_id + "/events").json()
        assert any(event["event_type"] == "tool.query_prepared" for event in events)


def test_explicit_query_skips_automatic_preparation(monkeypatch):
    queries = []

    async def stream(self, **params):
        assert not params.get("json_output"), "Manual first search must not invoke a planner"
        yield "Synthetic sourced answer."

    async def search(query):
        queries.append(query)
        return result(query)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        _, run_id = queue(client, explicit="reviewed public query")
        step()
        assert client.get("/api/runs/" + run_id).json()["status"] == "succeeded"
    assert queries == ["reviewed public query"]


@pytest.mark.parametrize(
    "output", ['{"query":""}', "not JSON", '{"query":"fact check","command":"bad"}', "x" * 2049]
)
def test_invalid_preparation_never_sends_raw_question_or_generates_answer(monkeypatch, output):
    closed = []

    async def stream(self, **params):
        try:
            assert params["json_output"]
            yield output
        finally:
            closed.append(True)

    async def forbidden(_query):
        pytest.fail("Invalid preparation must not send the raw question to search")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    with TestClient(app) as client:
        route, run_id = queue(client)
        step()
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == "failed" and "prepare a public search query" in run["error_message"]
        assert client.get(route).json()["messages"][-1]["content"] == ""
    assert closed == [True]


@pytest.mark.parametrize("fast", [False, True])
def test_stop_during_first_preparation_closes_model_and_never_searches(monkeypatch, fast):
    closed = []
    run_id = None

    async def stream(self, **params):
        try:
            assert params["json_output"]
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            if not fast:
                await asyncio.Future()
            yield json.dumps({"query": QUERY})
        finally:
            closed.append(True)

    async def forbidden(_query):
        pytest.fail("Stop must cancel preparation before any outbound search")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    with TestClient(app) as client:
        route, run_id = queue(client)
        step()
        assert client.get("/api/runs/" + run_id).json()["status"] == "canceled"
        assert client.get(route).json()["messages"][-1]["content"] == ""
    assert closed == [True]


@pytest.mark.parametrize("granted", [False, True])
def test_external_preparation_uses_selected_provider_and_requires_its_permission(monkeypatch, granted):
    calls = []

    async def stream(self, **params):
        calls.append(params)
        assert params["location"] == "external" and params["model"] == "cloud-model"
        assert params["endpoint"] == "https://api.example.test/v1"
        yield json.dumps({"query": QUERY}) if params.get("json_output") else "Synthetic sourced answer."

    async def forbidden(*_args, **_kwargs):
        pytest.fail("An ungranted external preparation must never reach inference")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["cloud-model"])
    monkeypatch.setattr(web_search, "search", lambda query: asyncio.sleep(0, result=result(query)))
    with TestClient(app) as client:
        provider = client.post(
            "/api/chat/providers",
            json={
                "key": "external-fixture",
                "name": "Explicit external fixture",
                "location": "external",
                "endpoint": "https://api.example.test/v1",
                "default_model": "cloud-model",
                "secret": "synthetic-external-test-only",
            },
        )
        assert provider.status_code == 201, provider.text
        created = client.post(
            "/api/chat/conversations", json={"provider": "external-fixture", "model": "cloud-model"}
        )
        assert created.status_code == 201, created.text
        route = "/api/chat/conversations/" + created.json()["id"]
        queued = client.post(route + "/messages", json={"content": QUESTION, "web_search": {"enabled": True}})
        assert queued.status_code == 202, queued.text
        run_id = queued.json()["id"]
        assert "external_ai" in queued.json()["effective_permissions"]
        if not granted:
            with session_factory()() as session:
                run = session.get(Run, run_id)
                run.effective_permissions = ["network_read"]
                session.commit()
                with pytest.raises(ProviderError, match="external_ai"):
                    asyncio.run(web_search.retrieve(session, run, QUESTION, forbidden, prepare_query=True))
        step()
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == ("succeeded" if granted else "failed"), run
        if granted:
            metadata = client.get(route).json()["messages"][-1]["metadata"]["web_search"]
            assert metadata["query"] == QUERY
            assert metadata["query_preparation"] == {"location": "external", "model": "cloud-model"}
            assert len(calls) == 2 and calls[0]["json_output"]
        else:
            assert calls == []
