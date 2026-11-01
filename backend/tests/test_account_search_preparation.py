"""Prepared search must use only the executing account's conversation context."""

import json

from app import web_search
from app.db import control_session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Message, Run, Task
from test_account_private_api import accounts, private_app  # noqa: F401


def test_search_preparation_and_results_stay_private_across_api_and_worker(accounts, monkeypatch):  # noqa: F811
    admin, alice, bob = accounts
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    conversations = []
    for browser in (alice, bob):
        response = browser.post("/api/chat/conversations", json={"model": "fixture-model"})
        assert response.status_code == 201, response.text
        conversations.append(response.json()["id"])
    owner = alice.get("/api/auth").json()["user"]["id"]
    other = bob.get("/api/auth").json()["user"]["id"]
    with control_session_factory()() as session:
        task = Task(owner_id=other, title="Bob private fixture")
        session.add(task)
        session.flush()
        foreign_run = Run(owner_id=other, task_id=task.id, executor_type="synthetic", status="succeeded")
        session.add(foreign_run)
        session.flush()
        session.add_all(
            [
                Message(
                    conversation_id=conversations[0],
                    role="user",
                    content="Alice public topic: Breaking Bad Walter Jr actor",
                ),
                Message(conversation_id=conversations[1], role="user", content="BOB PRIVATE CONVERSATION"),
                # Even inconsistent historical references must not enter A's context.
                Message(
                    conversation_id=conversations[0],
                    run_id=foreign_run.id,
                    role="assistant",
                    content="BOB PRIVATE RUN CONTENT",
                ),
            ]
        )
        session.commit()
    calls = []
    query = "Breaking Bad Walter Jr actor fact check"

    async def stream(self, **params):
        calls.append(params)
        assert "BOB PRIVATE" not in json.dumps(params["messages"])
        if params.get("json_output"):
            assert "Alice public topic" in json.dumps(params["messages"])
            yield json.dumps({"search_needed": True, "query": query})
        else:
            yield "Synthetic sourced answer."

    async def search(value):
        assert value == query
        return {
            "query": value,
            "provider": "synthetic",
            "searched_at": "2026-10-30T00:00:00Z",
            "partial": False,
            "sources": [
                {"id": 1, "title": "Fixture", "url": "https://example.org", "snippet": "Synthetic source."}
            ],
        }

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", search)
    response = alice.post(
        f"/api/chat/conversations/{conversations[0]}/messages",
        json={"content": "sprawdź to jeszcze raz", "web_search": {"enabled": True}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with control_session_factory()() as queue:
        assert tick(queue, "private-search-worker") == run_id
    assert alice.get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
    assert len(calls) == 2 and calls[0]["json_output"]
    message = alice.get(f"/api/chat/conversations/{conversations[0]}").json()["messages"][-1]
    result = message["metadata"]["web_search"]
    assert result["query_preparation"] == {"location": "local", "model": "fixture-model"}
    assert bob.get(f"/api/runs/{run_id}/events").status_code == 404
    assert bob.get(f"/api/artifacts/{result['artifact_id']}/file").status_code == 404
    assert alice.get(f"/api/artifacts/{result['artifact_id']}/file").status_code == 200
    inspected = admin.get(f"/api/admin/users/{owner}/workspace/runs/{run_id}")
    assert inspected.status_code == 200 and inspected.json()["metadata"]["web_search"]["query"] == query


def test_skipped_search_decision_is_private_and_creates_no_sources(accounts, monkeypatch):  # noqa: F811
    admin, alice, bob = accounts
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["fixture-model"])
    owner = alice.get("/api/auth").json()["user"]["id"]

    async def stream(_self, **params):
        yield '{"search_needed":false,"query":null}' if params.get("json_output") else "Hello."

    async def forbidden(_query):
        raise AssertionError("The skipped tool must never send an outbound query")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", forbidden)
    row = alice.post("/api/chat/conversations", json={"model": "fixture-model"}).json()
    path = "/api/chat/conversations/" + row["id"]
    sent = alice.post(path + "/messages", json={"content": "Say hello", "web_search": {"enabled": True}})
    assert sent.status_code == 202, sent.text
    run_id = sent.json()["id"]
    with control_session_factory()() as queue:
        assert tick(queue, "private-no-search") == run_id
    run = alice.get("/api/runs/" + run_id).json()
    assert run["status"] == "succeeded", run
    message = alice.get(path).json()["messages"][-1]
    assert message["content"] == "Hello." and "web_search" not in message["metadata"]
    assert message["metadata"]["web_search_decision"]["search_needed"] is False
    assert bob.get(path).status_code == 404
    assert bob.get("/api/runs/" + run_id).status_code == 404
    assert bob.get("/api/runs/" + run_id + "/events").status_code == 404
    inspected = admin.get(f"/api/admin/users/{owner}/workspace/runs/{run_id}")
    assert inspected.status_code == 200
    assert inspected.json()["metadata"]["web_search_decision"]["search_needed"] is False
