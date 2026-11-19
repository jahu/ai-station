import json

from app.db import control_session_factory
from app.engine import tick
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_managed_embeddings import cpu as cpu
from test_managed_embeddings import installed as installed


def drain():
    for _ in range(12):
        with control_session_factory()() as queue:
            if tick(queue, "personal-memory-integration") is None:
                return
    raise AssertionError("Personal memory queue did not finish")


def test_real_scoped_api_worker_learns_recalls_and_isolates_accounts(accounts, monkeypatch, cpu):
    owner, alice, bob = accounts
    setup = owner.get("/api/memory/embeddings/setup").json()
    prepared = owner.post("/api/memory/embeddings/prepare", json={"expected_revision": setup["revision"]})
    assert prepared.status_code == 202, prepared.text
    drain()
    seen = []

    async def stream(self, **params):
        seen.append(params["messages"])
        yield "Nice to meet you."

    monkeypatch.setattr("app.local_provider.LocalChatProvider.stream", stream)

    async def infer(session, run, messages, **kwargs):
        data = json.loads(messages[1]["content"])
        if "Alice" not in data["user_message"]:
            return '{"memories":[]}'
        return json.dumps(
            {
                "memories": [
                    {
                        "topic": "user.name",
                        "content": "The user's name is Alice.",
                        "kind": "fact",
                        "quote": "My name is Alice",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.assistant_decisions.infer", infer)
    settings = alice.get("/api/memory/personal/settings").json()
    assert not settings["learn"]
    assert (
        alice.put(
            "/api/memory/personal/settings",
            json={"use": True, "learn": True, "expected_revision": settings["revision"]},
        ).status_code
        == 200
    )
    assert not bob.get("/api/memory/personal/settings").json()["learn"]

    def chat(browser, content):
        response = browser.post("/api/chat/conversations", json={"model": "test"})
        assert response.status_code == 201, response.text
        cid = response.json()["id"]
        response = browser.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": content, "execution_mode": "local", "web_search": {"enabled": False}},
        )
        assert response.status_code == 202, response.text
        return cid

    first = chat(alice, "My name is Alice")
    drain()
    memories = alice.get("/api/memory").json()
    assert len(memories) == 1, alice.get("/api/memory/personal/settings").json()
    assert memories[0]["source_conversation_id"] == first
    assert alice.get("/api/memory/embeddings/setup").json()["indexed_count"] == 1
    assert bob.get("/api/memory").json() == []
    assert bob.get("/api/memory/" + memories[0]["id"]).status_code == 404
    assert bob.get("/api/memory/personal/settings").json()["recent_runs"] == []
    next_chat = chat(alice, "What is my name?")
    drain()
    detail = alice.get("/api/chat/conversations/" + next_chat).json()
    reply = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert reply["metadata"]["personal_memory"]["sources"][0]["id"] == memories[0]["id"]
    assert reply["metadata"]["personal_memory"]["method"] == "profile+lexical+semantic"
    assert "Alice" in str(seen[-1])
    chat(bob, "What is my name?")
    drain()
    assert "Alice" not in str(seen[-1])
    own_runs = alice.get("/api/memory/personal/settings").json()["recent_runs"]
    assert own_runs
    assert bob.post(f"/api/memory/personal/runs/{own_runs[0]['id']}/cancel").status_code == 404
