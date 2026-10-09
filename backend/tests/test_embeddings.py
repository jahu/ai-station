from app.api import app
from app.db import reset_engine, session_factory
from app.embeddings import cosine, validate_vector
from app.engine import tick
from app.memory import upsert_memory
from app.models import MemoryEmbedding, MemoryEntry
from app.providers import ProviderError
from fastapi.testclient import TestClient
from sqlalchemy import select


def drain(session, worker="embed-test", limit=20):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def test_vector_validation_rejects_zeros_and_non_finite():
    assert len(validate_vector([0.1, -0.2] * 4)) == 8
    try:
        validate_vector([0.0] * 8)
    except ValueError as exc:
        assert "all-zero" in str(exc)
    else:
        raise AssertionError("zero vector must fail closed")
    try:
        validate_vector([1.0, float("nan")] + [0.1] * 6)
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("NaN vector must fail closed")
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_embeddings_are_unavailable_until_explicit_local_setup():
    api = TestClient(app)
    setup = api.get("/api/memory/embeddings/setup").json()
    assert setup["configured"] is False and setup["indexed_count"] == 0
    assert api.post("/api/memory/embeddings/health").status_code == 409
    assert api.post("/api/memory/embeddings/index").status_code == 409
    assert api.post("/api/memory/embeddings/search", json={"query": "hello"}).status_code == 409
    assert (
        api.put(
            "/api/memory/embeddings/setup", json={"endpoint": "https://api.openai.com/v1", "model": "x"}
        ).status_code
        == 422
    )
    assert (
        api.put(
            "/api/memory/embeddings/setup",
            json={"endpoint": "http://127.0.0.1:11434/v1/embeddings", "model": "nomic"},
        ).status_code
        == 422
    )


def test_health_index_search_and_stale_or_zero_vectors(monkeypatch):
    calls = []

    async def embed(endpoint, model, text, secret_ref):
        calls.append(text)
        if text == "zero":
            return [0.0] * 8
        if "Prefer" in text:
            return [1.0, 0.0] + [0.0] * 6
        if "Other" in text:
            return [0.0, 1.0] + [0.0] * 6
        if text == "Prefer concise answers":
            return [1.0, 0.0] + [0.0] * 6
        return [1.0, 0.0] + [0.0] * 6

    monkeypatch.setattr("app.embeddings.embed_text", embed)
    api = TestClient(app)
    saved = api.put(
        "/api/memory/embeddings/setup",
        json={"endpoint": "http://127.0.0.1:11434/v1", "model": "nomic-embed"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True and saved.json()["secret_present"] is False
    health = api.post("/api/memory/embeddings/health")
    assert health.status_code == 202
    with session_factory()() as session:
        drain(session)
    assert api.get(f"/api/runs/{health.json()['id']}").json()["status"] == "succeeded"
    assert api.get("/api/memory/embeddings/setup").json()["dimension"] == 8
    with session_factory()() as session:
        upsert_memory(session, scope="global", content="Prefer concise answers")
        upsert_memory(session, scope="global", content="Other topic entirely")
        session.commit()
    indexed = api.post("/api/memory/embeddings/index")
    with session_factory()() as session:
        drain(session)
    done = api.get(f"/api/runs/{indexed.json()['id']}").json()
    assert done["status"] == "succeeded" and len(done["metadata"]["indexed"]) == 2
    with session_factory()() as session:
        assert session.scalar(select(MemoryEmbedding).limit(1)).dimension == 8
    search = api.post("/api/memory/embeddings/search", json={"query": "Prefer concise answers"})
    with session_factory()() as session:
        drain(session)
    result = api.get(f"/api/runs/{search.json()['id']}").json()
    assert result["status"] == "succeeded"
    hits = result["metadata"]["results"]
    assert hits[0]["content"] == "Prefer concise answers"
    assert hits[0]["score"] >= hits[1]["score"]
    artifact = api.get(f"/api/artifacts?run_id={search.json()['id']}").json()[0]
    assert artifact["type"] == "json"

    async def zeros(*args, **kwargs):
        raise ProviderError("Refusing an all-zero embedding vector")

    monkeypatch.setattr("app.embeddings.embed_text", zeros)
    with session_factory()() as session:
        upsert_memory(session, scope="global", content="zero")
        session.commit()
        before = session.scalar(
            select(MemoryEmbedding).where(
                MemoryEmbedding.memory_id
                == session.scalar(select(MemoryEntry.id).where(MemoryEntry.content == "zero"))
            )
        )
        assert before is None
    failed = api.post("/api/memory/embeddings/index")
    with session_factory()() as session:
        drain(session)
    assert api.get(f"/api/runs/{failed.json()['id']}").json()["status"] == "failed"
    with session_factory()() as session:
        assert (
            session.scalar(
                select(MemoryEmbedding).where(
                    MemoryEmbedding.memory_id.in_(select(MemoryEntry.id).where(MemoryEntry.content == "zero"))
                )
            )
            is None
        )
    cleared = api.put("/api/memory/embeddings/setup", json={"clear": True, "endpoint": "", "model": ""})
    assert cleared.status_code == 200 and cleared.json()["configured"] is False
    reset_engine()


def test_embeddings_migration_preserves_memories():
    from alembic import command
    from app.db import alembic_config

    api = TestClient(app)
    created = api.post("/api/memory", json={"content": "Keep me", "scope": "global"}).json()
    command.downgrade(alembic_config(), "0016")
    command.upgrade(alembic_config(), "head")
    reset_engine()
    assert api.get(f"/api/memory/{created['id']}").json()["content"] == "Keep me"
    assert api.get("/api/memory/embeddings/setup").json()["configured"] is False
