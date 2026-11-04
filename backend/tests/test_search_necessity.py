"""Web availability must not turn self-contained instructions into public queries."""

import asyncio
from uuid import uuid4

import pytest
from app import web_search
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Message, Run
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


def step():
    with session_factory()() as session:
        return tick(session, "search-necessity")


def queue(client, content, *, web=True, explicit="", mode="local"):
    row = client.post("/api/chat/conversations", json={"model": "fixture-model", "execution_mode": mode})
    assert row.status_code == 201, row.text
    path = "/api/chat/conversations/" + row.json()["id"]
    sent = client.post(
        path + "/messages",
        json={
            "content": content,
            "action": "auto" if mode == "assistant" else "chat",
            "web_search": {"enabled": web, "query": explicit},
        },
    )
    assert sent.status_code == 202, sent.text
    return path, sent.json()["id"]


@pytest.mark.parametrize("mode", ["local", "assistant"])
@pytest.mark.parametrize(
    "content",
    [
        "Reply with exactly WINDOWS_MODEL_OK.",
        "Cześć!",
        "Translate this supplied text into Polish: Bitcoin is a word in this sentence.",
        "Write a fictional story about a computer called Windows.",
    ],
)
def test_self_contained_reply_has_no_search_sources_or_artifact(monkeypatch, content, mode):
    calls = []

    async def stream(_self, **params):
        calls.append(params)
        if params["messages"][0]["content"].startswith("Route the user's request"):
            yield '{"action":"chat","reason":"A self-contained conversation request."}'
            return
        if params.get("json_output"):
            assert '"search_needed"' in params["messages"][0]["content"]
            assert params["max_tokens"] == 256 and "reasoning" not in params
            yield '{"search_needed":false,"query":null}'
        else:
            assert params["messages"][-1]["content"] == content
            yield "SELF_CONTAINED_OK"

    async def forbidden(_query):
        pytest.fail("A self-contained request must never reach the search service")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    with TestClient(app) as client:
        path, run_id = queue(client, content, mode=mode)
        assert step() == run_id
        if mode == "assistant":
            root = client.get("/api/runs/" + run_id).json()
            if root["executor_type"] != "chat":
                run_id = root["metadata"]["child_run_id"]
                assert step() == run_id
        run = client.get("/api/runs/" + run_id).json()
        assert run["parameters"]["web_search_plan_version"] == 2
        assert run["status"] == "succeeded", run
        message = client.get(path).json()["messages"][-1]
        assert message["content"] == "SELF_CONTAINED_OK"
        assert "web_search" not in message["metadata"]
        assert message["metadata"]["web_search_decision"]["search_needed"] is False
        events = client.get("/api/runs/" + run_id + "/events").json()
        assert any(e["event_type"] == "tool.skipped" for e in events)
        assert not any(e["event_type"] in {"tool.requested", "tool.started"} for e in events)
        with session_factory()() as session:
            assert session.scalar(select(Artifact.id).where(Artifact.run_id == run_id)) is None
        assert (
            sum(
                bool(p.get("json_output")) and not p["messages"][0]["content"].startswith("Route the user")
                for p in calls
            )
            == 1
        )
        assert len(calls) in ({2} if mode == "local" else {2, 3})


@pytest.mark.parametrize(
    "response",
    [
        "{}",
        '{"query":"unapproved query"}',
        '{"search_needed":"false"}',
        '{"search_needed":false,"query":"private text"}',
        '{"search_needed":true}',
        '{"search_needed":true,"query":""}',
        '{"search_needed":false,"command":"search anyway"}',
    ],
)
def test_invalid_necessity_never_searches_or_silently_answers(monkeypatch, response):
    closed = []

    async def stream(_self, **params):
        assert params["json_output"]
        try:
            yield response
        finally:
            closed.append(True)

    async def forbidden(_query):
        pytest.fail("An invalid decision cannot authorize an outbound query")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    with TestClient(app) as client:
        _, run_id = queue(client, "Verify this reported event")
        step()
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == "failed" and "prepare a public search query" in run["error_message"]
    assert closed == [True]


@pytest.mark.parametrize("enabled", [False, True])
def test_web_off_and_explicit_query_do_not_invoke_necessity_planning(monkeypatch, enabled):
    queries = []

    async def stream(_self, **params):
        assert not params.get("json_output")
        yield "Answer."

    async def search(query):
        queries.append(query)
        return {
            "query": query,
            "sources": [{"id": 1, "url": "https://example.org", "title": "Fixture", "snippet": "Data"}],
            "partial": False,
        }

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        _, run_id = queue(client, "Reply with a literal.", web=enabled, explicit="explicit public query")
        step()
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == "succeeded", run
        assert "web_search_plan_version" not in run["parameters"]
    assert queries == (["explicit public query"] if enabled else [])


def test_legacy_queued_run_and_regeneration_keep_original_search_contract(monkeypatch):
    queries = []

    async def stream(_self, **params):
        if params.get("json_output"):
            assert '"search_needed"' not in params["messages"][0]["content"]
            assert params["messages"][0]["content"].startswith(
                "Prepare a concise, relevant public search-engine query for the question. "
                'Return only JSON {"query": "..."}. Preserve named subjects and the information requested; '
            )
            yield '{"query":"legacy public query"}'
        else:
            yield "Legacy answer."

    async def search(query):
        queries.append(query)
        return {
            "query": query,
            "sources": [{"id": 1, "url": "https://example.org", "title": "Fixture", "snippet": "Data"}],
            "partial": False,
        }

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", search)
    with TestClient(app) as client:
        path, run_id = queue(client, "A historical factual question")
        with session_factory()() as session:
            run = session.get(Run, run_id)
            run.parameters = {k: v for k, v in run.parameters.items() if k != "web_search_plan_version"}
            user = session.scalar(
                select(Message).where(
                    Message.conversation_id == path.rsplit("/", 1)[1], Message.role == "user"
                )
            )
            user.metadata_json = {
                k: v for k, v in user.metadata_json.items() if k != "web_search_plan_version"
            }
            session.commit()
        step()
        assert client.get("/api/runs/" + run_id).json()["status"] == "succeeded"
        retry = client.post(path + "/regenerate")
        assert retry.status_code == 202, retry.text
        assert "web_search_plan_version" not in retry.json()["parameters"]
        step()
        assert client.get("/api/runs/" + retry.json()["id"]).json()["status"] == "succeeded"
    assert queries == ["legacy public query", "legacy public query"]


@pytest.mark.parametrize("fast", [False, True])
def test_stop_during_no_search_decision_never_produces_an_answer(monkeypatch, fast):
    closed = []
    run_id = None

    async def stream(_self, **params):
        assert params["json_output"]
        try:
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            if not fast:
                await asyncio.Future()
            yield '{"search_needed":false,"query":null}'
        finally:
            closed.append(True)

    async def forbidden(_query):
        pytest.fail("Stop must never dispatch a search")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    with TestClient(app) as client:
        path, run_id = queue(client, "Say hello")
        step()
        assert client.get("/api/runs/" + run_id).json()["status"] == "canceled"
        assert client.get(path).json()["messages"][-1]["content"] == ""
    assert closed == [True]


def test_unified_turn_receipt_remains_idempotent_after_a_skipped_search(monkeypatch):
    async def stream(_self, **params):
        yield '{"search_needed":false,"query":null}' if params.get("json_output") else "Hello."

    async def forbidden(_query):
        pytest.fail("This turn does not need research")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    body = {
        "client_request_id": str(uuid4()),
        "selection": {"model": "fixture-model", "execution_mode": "assistant"},
        "content": "Say hello",
        "web_search": {"enabled": True},
    }
    with TestClient(app) as client:
        first = client.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        receipt = first.json()
        assert receipt["run"]["parameters"]["web_search_plan_version"] == 2
        step()
        assert client.get("/api/runs/" + receipt["run"]["id"]).json()["status"] == "succeeded"
        repeated = client.post("/api/chat/turns", json=body)
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["run"]["id"] == receipt["run"]["id"]
        messages = client.get("/api/chat/conversations/" + receipt["conversation_id"]).json()["messages"]
        assert [m["content"] for m in messages] == ["Say hello", "Hello."]
        assert client.post("/api/chat/turns", json={**body, "content": "different"}).status_code == 409
