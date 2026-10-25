"""Managed CPU setup uses explicit, source-bound ordinary Runs and owned children."""

import asyncio
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app import embedding_models as models
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.embeddings import vector_identity
from app.engine import tick
from app.memory import upsert_memory
from app.models import MemoryEmbedding, MemoryEntry, Run, Setting
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def installed(monkeypatch):
    root = get_settings().data_dir
    files = {}
    folder = models.directory(root, create=True)
    for name in models.FILES:
        body = ("Synthetic fixture: " + name).encode()
        files[name] = {"remote": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        (folder / name).write_bytes(body)
    monkeypatch.setattr(models, "FILES", files)
    models.write_receipt(root)
    return root


@pytest.fixture
def cpu(installed, monkeypatch, tmp_path):
    script = tmp_path / "controlled_cpu_fixture.py"
    script.write_text("""import json,sys,time
from app.embedding_cpu import bind_parent
bind_parent(int(sys.argv[1]))
print(json.dumps({"ready":True,"device":"CPU","dimension":384}),flush=True)
for line in sys.stdin:
 body=json.loads(line)
 if body["text"]=="HOLD":time.sleep(120)
 vector=[0.0]*384;vector[1 if "Pear" in body["text"] else 0]=1.0
 print(json.dumps({"vector":vector,"chunks":1}),flush=True)
""")
    original = asyncio.create_subprocess_exec
    started = []

    async def launch(*argv, **kwargs):
        assert argv[0] == sys.executable and argv[1:3] == ("-m", "app.embedding_cpu")
        assert argv[-1] == str(os.getpid()) and kwargs["start_new_session"]
        assert kwargs["env"]["OMP_NUM_THREADS"] == "2"
        assert "AI_STATION_LLM_API_KEY" not in kwargs["env"]
        process = await original(sys.executable, str(script), str(os.getpid()), **kwargs)
        started.append(process.pid)
        return process

    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "test-private-key-not-for-cpu")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    return started


def drain():
    for _ in range(12):
        with session_factory()() as session:
            if tick(session, "memory-cpu-fixture") is None:
                return
    raise AssertionError("Embedding Run queue did not finish")


def prepare(client, **body):
    setup = client.get("/api/memory/embeddings/setup").json()
    return client.post(
        "/api/memory/embeddings/prepare", json={"expected_revision": setup["revision"], **body}
    )


def test_no_model_is_downloaded_on_status_index_search_or_unconfirmed_preparation(monkeypatch):
    requests = []

    async def forbidden(*args, **kwargs):
        requests.append(True)
        raise AssertionError("Implicit model download")

    monkeypatch.setattr("app.embedding_download.download_file", forbidden)
    client = TestClient(app)
    setup = client.get("/api/memory/embeddings/setup").json()
    assert not setup["configured"] and not setup["local_model"]["installed"]
    assert setup["local_model"]["size_bytes"] > 100000000
    assert prepare(client).status_code == 422
    assert client.post("/api/memory/embeddings/index").status_code == 409
    assert client.post("/api/memory/embeddings/search", json={"query": "hello"}).status_code == 409
    assert not requests


def test_verified_cpu_setup_probes_and_indexes_with_no_endpoint_or_gpu(cpu):
    client = TestClient(app)
    with session_factory()() as session:
        upsert_memory(session, scope="global", content="Apples and gardening")
        upsert_memory(session, scope="global", content="Pear harvest")
        session.commit()
    queued = prepare(client)
    assert queued.status_code == 202, queued.text
    assert queued.json()["effective_permissions"] == ["manage_models"]
    drain()
    current = client.get("/api/memory/embeddings/setup").json()
    assert current["configured"] and current["backend"] == "local_cpu" and current["endpoint"] == ""
    assert current["dimension"] == 384 and current["indexed_count"] == current["memory_count"] == 2
    assert current["prepare_run"]["status"] == current["index_run"]["status"] == "succeeded"
    assert current["index_run"]["task_id"] == queued.json()["task_id"]
    assert len(cpu) == 2 and all(not Path(f"/proc/{pid}").exists() for pid in cpu)
    result = client.post("/api/memory/embeddings/search", json={"query": "Apples"})
    assert result.status_code == 202
    drain()
    run = client.get("/api/runs/" + result.json()["id"]).json()
    assert run["status"] == "succeeded" and run["metadata"]["results"][0]["content"] == "Apples and gardening"
    assert run["metadata"]["cpu_process_confirmed_gone"] is True
    with session_factory()() as session:
        setting = session.get(Setting, "memory_embeddings")
        row = session.scalar(select(MemoryEmbedding))
        assert row.model == vector_identity(setting.value)


def test_prepare_requires_exact_revision_and_does_not_replace_advanced_settings(cpu):
    client = TestClient(app)
    queued = prepare(client)
    assert queued.status_code == 202
    changed = client.put(
        "/api/memory/embeddings/setup", json={"endpoint": "http://localhost:8080/v1", "model": "other"}
    )
    assert changed.status_code == 200
    assert prepare(client, expected_revision=0).status_code == 409
    drain()
    result = client.get("/api/runs/" + queued.json()["id"]).json()
    assert result["status"] == "failed"
    assert client.get("/api/memory/embeddings/setup").json()["model"] == "other"
    assert not cpu


def test_queued_index_from_another_setup_cannot_publish_vectors(cpu):
    client = TestClient(app)
    assert prepare(client).status_code == 202
    with session_factory()() as session:
        tick(session, "prepare-only")
    cleared = client.put("/api/memory/embeddings/setup", json={"clear": True})
    assert cleared.status_code == 200
    drain()
    with session_factory()() as session:
        assert not list(session.scalars(select(MemoryEmbedding)))
        index = session.scalar(select(Run).where(Run.capability == "memory.embed.index"))
        assert index.status == "failed"


def test_stop_running_cpu_search_kills_only_its_owned_child_and_retains_memory(cpu):
    client = TestClient(app)
    assert prepare(client).status_code == 202
    drain()
    with session_factory()() as session:
        entry = upsert_memory(session, scope="global", content="Preserve this memory")
        entry_id = entry.id
        session.commit()
    count_before = len(cpu)
    queued = client.post("/api/memory/embeddings/search", json={"query": "HOLD"}).json()

    def execute():
        with session_factory()() as session:
            return tick(session, "cancel-cpu-search")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        deadline = time.monotonic() + 8
        while len(cpu) == count_before:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with session_factory()() as session:
            request_cancel(session, session.get(Run, queued["id"]))
            session.commit()
        assert future.result(timeout=5) == queued["id"]
    final = client.get("/api/runs/" + queued["id"]).json()
    assert final["status"] == "canceled" and final["metadata"]["cpu_process_confirmed_gone"]
    assert not Path(f"/proc/{cpu[-1]}").exists()
    assert client.get("/api/memory/" + entry_id).status_code == 200
    assert client.get("/api/artifacts?run_id=" + queued["id"]).json() == []


def test_cached_model_paths_reject_symlink_escape(installed, tmp_path):
    path = models.model_file(installed, "tokenizer.json")
    path.unlink()
    external = tmp_path / "external-tokenizer"
    external.write_text("Unrelated original")
    path.symlink_to(external)
    assert not models.installation(installed)["installed"]
    with pytest.raises(ValueError):
        models.verify_file(installed, "tokenizer.json")
    assert external.read_text() == "Unrelated original"


def test_cache_changes_invalidate_readiness_and_cannot_be_hidden_by_same_size(installed):
    path = models.model_file(installed, "tokenizer.json")
    before = path.read_bytes()
    path.write_bytes(b"x" * len(before))
    assert not models.installation(installed)["installed"]
    with pytest.raises(ValueError, match="verification"):
        models.verify_file(installed, "tokenizer.json")


@pytest.mark.parametrize("change", ["content", "disable", "delete"])
def test_index_rechecks_live_memory_after_inference_before_storing(monkeypatch, change):
    client = TestClient(app)
    assert (
        client.put(
            "/api/memory/embeddings/setup",
            json={"endpoint": "http://localhost:8080/v1", "model": "synthetic"},
        ).status_code
        == 200
    )
    with session_factory()() as session:
        row = upsert_memory(session, scope="global", content="Original input")
        key = row.id
        session.commit()

    async def embed(*args):
        with session_factory()() as session:
            row = session.get(MemoryEntry, key)
            if change == "delete":
                session.delete(row)
            elif change == "disable":
                row.enabled = False
            else:
                row.content = "New content while inference was running"
            session.commit()
        return [1.0] + [0.0] * 7

    monkeypatch.setattr("app.embeddings.embed_text", embed)
    queued = client.post("/api/memory/embeddings/index").json()
    drain()
    result = client.get("/api/runs/" + queued["id"]).json()
    assert result["status"] == "succeeded" and result["metadata"]["changed_during_index"] == 1
    with session_factory()() as session:
        assert session.get(MemoryEmbedding, key) is None


def test_endpoint_identity_and_scope_filters_never_reuse_unrelated_vectors(monkeypatch):
    from app.models import Agent

    async def embed(*args):
        return [1.0] + [0.0] * 7

    monkeypatch.setattr("app.embeddings.embed_text", embed)
    client = TestClient(app)
    assert (
        client.put(
            "/api/memory/embeddings/setup",
            json={"endpoint": "http://localhost:8080/v1", "model": "same-name"},
        ).status_code
        == 200
    )
    with session_factory()() as session:
        agent = Agent(name="Private scope", goal="Scope fixture", model="fake-local")
        session.add(agent)
        session.flush()
        upsert_memory(session, scope="global", content="Global fact")
        upsert_memory(session, scope="agent", scope_id=agent.id, content="Agent fact")
        session.commit()
    assert client.post("/api/memory/embeddings/index").status_code == 202
    drain()
    queued = client.post("/api/memory/embeddings/search", json={"query": "fact", "scope": "global"}).json()
    drain()
    result = client.get("/api/runs/" + queued["id"]).json()
    assert [r["content"] for r in result["metadata"]["results"]] == ["Global fact"]
    assert (
        client.put(
            "/api/memory/embeddings/setup",
            json={"endpoint": "http://localhost:9090/v1", "model": "same-name"},
        ).status_code
        == 200
    )
    assert client.get("/api/memory/embeddings/setup").json()["indexed_count"] == 0
    queued = client.post("/api/memory/embeddings/search", json={"query": "fact"}).json()
    drain()
    assert client.get("/api/runs/" + queued["id"]).json()["metadata"]["results"] == []


def test_cpu_model_is_not_started_when_every_vector_is_already_current(cpu):
    client = TestClient(app)
    with session_factory()() as session:
        upsert_memory(session, scope="global", content="Already indexed")
        session.commit()
    assert prepare(client).status_code == 202
    drain()
    count = len(cpu)
    assert client.post("/api/memory/embeddings/index").status_code == 202
    drain()
    assert len(cpu) == count


def test_recovery_interrupts_a_stale_cpu_run_without_reexecuting_it(cpu):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.db import utcnow
    from app.recovery import recover_stale

    client = TestClient(app)
    assert prepare(client).status_code == 202
    drain()
    queued = client.post("/api/memory/embeddings/search", json={"query": "Inspect, do not replay"}).json()
    count = len(cpu)
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.status = "running"
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert recover_stale(session, SimpleNamespace(inspect_process=lambda _: {"alive": False})) == [run.id]
        session.commit()
        assert run.status == "interrupted"
    drain()
    assert len(cpu) == count
    assert client.get("/api/runs/" + queued["id"]).json()["status"] == "interrupted"
