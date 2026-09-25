from uuid import uuid4

from app.api import app
from app.db import reset_engine, session_factory
from app.memory import upsert_memory
from app.models import Conversation, MemoryEntry, Message, Project, Run
from fastapi.testclient import TestClient
from sqlalchemy import select, text


def client():
    return TestClient(app)


def test_memory_crud_fts_version_and_restart():
    api = client()
    created = api.post(
        "/api/memory", json={"content": "Prefer concise Polish responses", "tags": ["language"]}
    )
    assert created.status_code == 201
    row = created.json()
    assert api.get("/api/memory?q=Polish").json()[0]["id"] == row["id"]
    assert api.get("/api/memory?tag=language").json()[0]["id"] == row["id"]
    update = {
        "content": "Prefer short English responses",
        "tags": ["style"],
        "pinned": True,
        "expected_updated_at": row["updated_at"],
    }
    changed = api.put(f"/api/memory/{row['id']}", json=update)
    assert changed.status_code == 200
    assert api.put(f"/api/memory/{row['id']}", json=update).status_code == 409
    assert api.get("/api/memory?q=Polish").json() == []
    assert api.get("/api/memory?tag=language").json() == []
    reset_engine()
    assert api.get("/api/memory?q=English").json()[0]["content"] == update["content"]
    update.update(enabled=False, expected_updated_at=changed.json()["updated_at"])
    disabled = api.put(f"/api/memory/{row['id']}", json=update).json()
    assert api.get("/api/memory?q=English").json() == []
    assert len(api.get("/api/memory?q=English&include_disabled=true").json()) == 1
    assert (
        api.request(
            "DELETE", f"/api/memory/{row['id']}", json={"expected_updated_at": row["updated_at"]}
        ).status_code
        == 409
    )
    assert (
        api.request(
            "DELETE", f"/api/memory/{row['id']}", json={"expected_updated_at": disabled["updated_at"]}
        ).status_code
        == 204
    )
    assert api.get(f"/api/memory/{row['id']}").status_code == 404
    with session_factory()() as session:
        assert session.scalar(text("SELECT count(*) FROM memory_fts")) == 0


def test_search_scopes_before_limit_and_escapes_fts(session):
    project = Project(name="Target", repo_path="/unused")
    session.add(project)
    session.flush()
    for _ in range(55):
        upsert_memory(session, scope="global", content="needle", pinned=True)
    desired = upsert_memory(session, scope="project", scope_id=project.id, content="needle other words")
    session.commit()
    rows = client().get(f"/api/memory?q=needle&scope=project&scope_id={project.id}&limit=1").json()
    assert [row["id"] for row in rows] == [desired.id]
    assert client().get("/api/memory?q=%22%20OR%20NOT%20*").status_code == 200
    assert client().get("/api/memory?q=%22%22").json() == []
    assert len(client().get("/api/memory?limit=10&offset=50").json()) == 6


def test_memory_input_and_provenance_validation(session):
    first, second = Conversation(model="test"), Conversation(model="test")
    session.add_all([first, second])
    session.flush()
    message = Message(conversation_id=first.id, role="user", content="A decision")
    session.add(message)
    session.commit()
    api = client()
    for body in [
        {"content": " "},
        {"content": "x", "scope": "global", "scope_id": first.id},
        {"content": "x", "scope": "project"},
        {"content": "x", "scope": "project", "scope_id": str(uuid4())},
        {"content": "x", "confidence": 1.1},
        {"content": "x", "source_run_id": str(uuid4())},
        {"content": "x", "source_message_id": message.id, "source_conversation_id": second.id},
        {"content": "x", "scope": "conversation", "scope_id": second.id, "source_message_id": message.id},
    ]:
        assert api.post("/api/memory", json=body).status_code == 422, body
    created = api.post(
        "/api/memory",
        json={
            "content": "Decision excerpt",
            "scope": "conversation",
            "scope_id": first.id,
            "source_message_id": message.id,
        },
    ).json()
    assert created["source_conversation_id"] == first.id
    assert created["source_message_id"] == message.id
    update = {
        "content": "Revised",
        "expected_updated_at": created["updated_at"],
        "source_message_id": str(uuid4()),
    }
    assert api.put(f"/api/memory/{created['id']}", json=update).status_code == 422


def test_pinned_context_is_scoped_bounded_and_snapshotted(session):
    first, second = Conversation(model="test"), Conversation(model="test")
    session.add_all([first, second])
    session.flush()
    included = upsert_memory(
        session, scope="conversation", scope_id=first.id, content="Use Polish", pinned=True
    )
    upsert_memory(session, scope="global", content="Explain assumptions", pinned=True)
    upsert_memory(
        session, scope="conversation", scope_id=second.id, content="PRIVATE OTHER CONVERSATION", pinned=True
    )
    upsert_memory(session, scope="project", scope_id=str(uuid4()), content="PRIVATE PROJECT", pinned=True)
    upsert_memory(session, scope="global", content="UNPINNED")
    disabled = upsert_memory(session, scope="global", content="DISABLED", pinned=True)
    disabled.enabled = False
    upsert_memory(session, scope="global", content="X" * 13000, pinned=True)
    session.commit()
    response = client().post(f"/api/chat/conversations/{first.id}/messages", json={"content": "Hello"})
    assert response.status_code == 202
    session.expire_all()
    run = session.get(Run, response.json()["id"])
    context = str(run.parameters["messages"])
    assert "Use Polish" in context and "Explain assumptions" in context
    for excluded in ("PRIVATE", "UNPINNED", "DISABLED", "X" * 100):
        assert excluded not in context
    assert included.id in [source["id"] for source in run.parameters["memory_sources"]]
    included.content = "Changed after dispatch"
    session.commit()
    assert "Changed after dispatch" not in str(run.parameters["messages"])
    assert len(list(session.scalars(select(MemoryEntry)))) == 7
