import importlib
import os
from uuid import uuid4

import pytest
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.discovery_job import inventory
from app.api import app
from app.db import reset_engine, session_factory
from app.engine import tick
from app.models import ModelFile, Run
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def model_host(tmp_path, monkeypatch):
    module = importlib.import_module("ai_station_runner.app")
    root = tmp_path / "models/llm"
    root.mkdir(parents=True)
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    module.reset_manager()
    monkeypatch.setattr(RunnerClient, "_client", lambda _: TestClient(module.app))
    yield root, module
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def scan(api):
    response = api.post("/api/models/discover", json={})
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "model-test")
    return api.get("/api/runs/" + response.json()["id"]).json()


def test_managed_discovery_persistence_and_missing_observations(model_host):
    root, host = model_host
    source = root / "Qwen-Q4_K_M.gguf"
    source.write_bytes(b"fake model bytes")
    before = source.stat()
    api = TestClient(app)
    run = scan(api)
    assert run["status"] == "succeeded", run
    row = api.get("/api/models?category=llm&q=Qwen").json()["items"][0]
    assert row["availability"] == "present" and row["last_scan_run_id"] == run["id"]
    assert row["quantization"] == "Q4_K_M"
    assert source.read_bytes() == b"fake model bytes"
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert api.get("/api/artifacts?run_id=" + run["id"]).json()[0]["type"] == "json"
    duplicate = host.start_model_scan(
        host.ModelScanBody(run_id=run["id"], permissions=["filesystem_read", "manage_models"])
    )
    assert duplicate["pid"] == run["pid"]
    reset_engine()
    assert api.get("/api/models/" + row["id"]).json()["host_path"] == str(source)
    # The test, not AI Station, removes the fake fixture to simulate external change.
    source.unlink()
    assert scan(api)["status"] == "succeeded"
    missing = api.get("/api/models/" + row["id"]).json()
    assert missing["availability"] == "missing"
    assert missing["last_seen_at"] == row["last_seen_at"]
    root.rmdir()
    assert scan(api)["status"] == "succeeded"
    assert api.get("/api/models/" + row["id"]).json()["availability"] == "unknown"


def test_discovery_excludes_links_special_files_and_enforces_budget(tmp_path, monkeypatch):
    from ai_station_runner import discovery_job

    root = tmp_path / "image"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.gguf").write_bytes(b"private")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "link.gguf").symlink_to(outside / "private.gguf")
    os.mkfifo(root / "pipe.bin")
    (root / "juggernaut.safetensors").write_bytes(b"fixture")
    rows = inventory([root])["models"]
    assert [row["filename"] for row in rows] == ["juggernaut.safetensors"]
    assert rows[0]["category"] == "image"
    monkeypatch.setattr(discovery_job, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="budget"):
        inventory([root])


def test_discovery_rejects_client_paths_and_missing_permissions(model_host):
    _, host = model_host
    api = TestClient(app)
    assert api.post("/api/models/discover", json={"roots": ["/etc"]}).status_code == 422
    runner = TestClient(host.app)
    assert (
        runner.post("/v1/runs/model-scan", json={"run_id": str(uuid4()), "permissions": []}).status_code
        == 403
    )
    assert (
        runner.post(
            "/v1/runs/model-scan",
            json={
                "run_id": str(uuid4()),
                "permissions": ["filesystem_read", "manage_models"],
                "roots": ["/etc"],
            },
        ).status_code
        == 422
    )
    first = api.post("/api/models/discover", json={}).json()
    assert api.post("/api/models/discover", json={}).status_code == 409
    with session_factory()() as session:
        request_cancel(session, session.get(Run, first["id"]))
        session.commit()
    assert api.get("/api/runs/" + first["id"]).json()["status"] == "canceled"


def test_runner_outage_does_not_erase_inventory(model_host, monkeypatch):
    root, _ = model_host
    (root / "test.gguf").write_bytes(b"fixture")
    api = TestClient(app)
    assert scan(api)["status"] == "succeeded"
    row = api.get("/api/models").json()["items"][0]

    def unavailable(*args, **kwargs):
        raise RunnerUnavailable("offline")

    monkeypatch.setattr(RunnerClient, "request", unavailable)
    run = scan(api)
    assert run["status"] == "preparing"
    assert api.get("/api/models").json()["items"][0] == row
    with session_factory()() as session:
        assert session.scalar(select(ModelFile.id)) == row["id"]
        assert session.get(Run, run["id"]).metadata_json["dispatch_attempted"]


def test_cancel_running_scan_preserves_previous_registry(model_host, monkeypatch):
    import sys

    root, host = model_host
    (root / "existing.gguf").write_bytes(b"fixture")
    api = TestClient(app)
    assert scan(api)["status"] == "succeeded"
    before = api.get("/api/models").json()["items"]
    real_start = host.manager().start

    def slow_start(**kwargs):
        return real_start(**{**kwargs, "argv": [sys.executable, "-c", "import time; time.sleep(60)"]})

    monkeypatch.setattr(host.manager(), "start", slow_start)
    request = RunnerClient.request

    def cancel_after_start(self, method, path, json=None):
        result = request(self, method, path, json)
        if path == "/v1/runs/model-scan":
            with session_factory()() as session:
                request_cancel(session, session.get(Run, json["run_id"]))
                session.commit()
        return result

    monkeypatch.setattr(RunnerClient, "request", cancel_after_start)
    run = scan(api)
    assert run["status"] == "canceled"
    assert not host.manager().inspect(run["id"])["alive"]
    assert api.get("/api/models").json()["items"] == before


def test_output_symlink_rejected_and_executor_ownership(model_host, tmp_path):
    import sys

    root, host = model_host
    (root / "test.gguf").write_bytes(b"fixture")
    data = tmp_path / "data"
    redirected = data / "private"
    redirected.mkdir()
    (data / "artifacts").rmdir()  # Empty directory created by this test fixture.
    (data / "artifacts").symlink_to(redirected, target_is_directory=True)
    api = TestClient(app)
    assert scan(api)["status"] == "failed"
    assert list(redirected.iterdir()) == []
    run_id = str(uuid4())
    host.manager().start(run_id=run_id, argv=[sys.executable, "-c", "pass"], cwd=data, executor="other")
    response = TestClient(host.app).post(
        "/v1/runs/model-scan", json={"run_id": run_id, "permissions": ["filesystem_read", "manage_models"]}
    )
    assert response.status_code == 409


def test_observation_migration_preserves_existing_model_metadata():
    from alembic import command
    from app.db import alembic_config

    with session_factory()() as session:
        row = ModelFile(host_path="/models/old.gguf", filename="old.gguf", size_bytes=123)
        session.add(row)
        session.commit()
        file_id = row.id
    command.downgrade(alembic_config(), "0001")
    command.upgrade(alembic_config(), "head")
    reset_engine()
    with session_factory()() as session:
        restored = session.get(ModelFile, file_id)
        assert restored.filename == "old.gguf" and restored.size_bytes == 123
        assert restored.availability == "unknown" and restored.last_seen_at is None


@pytest.mark.asyncio
async def test_sse_database_wait_does_not_block_http_event_loop(monkeypatch):
    import asyncio
    import threading
    from uuid import UUID

    module = importlib.import_module("app.api")
    waiting, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def blocked_read(*args):
        assert threading.get_ident() != loop_thread
        waiting.set()
        assert release.wait(3)
        return [], True

    monkeypatch.setattr(module, "read_event_batch", blocked_read)
    with session_factory()() as session:
        from app.runs import create_run, create_task

        task = create_task(session, title="SSE probe", prompt="", capability="test")
        run = create_run(session, task, run_type="test", capability="test", executor_type="fake")
        session.commit()
        response = module.stream(UUID(run.id), session, after=0, last_event_id=None)
        pending = asyncio.create_task(anext(response.body_iterator))
        try:
            for _ in range(100):
                if waiting.is_set():
                    break
                await asyncio.sleep(0.01)
            assert waiting.is_set()
            # This coroutine still runs while a database reader is blocked.
            release.set()
            assert await pending == "event: end\ndata: {}\n\n"
        finally:
            release.set()
            await response.body_iterator.aclose()
