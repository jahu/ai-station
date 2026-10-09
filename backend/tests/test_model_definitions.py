import importlib
from uuid import uuid4

from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import ModelDefinition, ModelFile, Run
from app.runner_client import RunnerClient
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select


def test_compatibility_is_declared_not_a_successful_load():
    api = TestClient(app)
    payload = api.get("/api/models/compatibility").json()
    llama = next(item for item in payload["items"] if item["format"] == "gguf" and item["category"] == "llm")
    assert llama["runtime"] == "llama.cpp" and llama["operational"] is True
    assert "never downloads" in llama["summary"]
    image = next(
        item for item in payload["items"] if item["format"] == "safetensors" and item["category"] == "image"
    )
    assert image["operational"] is False
    assert "not a successful load" in payload["note"]


def test_discovery_does_not_invent_definitions(tmp_path, monkeypatch):
    module = importlib.import_module("ai_station_runner.app")
    root = tmp_path / "models/llm"
    root.mkdir(parents=True)
    (root / "Qwen-Q4_K_M.gguf").write_bytes(b"fixture")
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    module.reset_manager()
    monkeypatch.setattr(RunnerClient, "_client", lambda _: TestClient(module.app))
    api = TestClient(app)
    run = api.post("/api/models/discover", json={}).json()
    with session_factory()() as session:
        tick(session, "definition-test")
    assert api.get("/api/runs/" + run["id"]).json()["status"] == "succeeded"
    assert api.get("/api/models/definitions").json() == {"items": [], "total": 0}
    file_id = api.get("/api/models").json()["items"][0]["id"]
    assert api.get("/api/models/" + file_id).json()["definitions"] == []
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def _host(tmp_path, monkeypatch):
    module = importlib.import_module("ai_station_runner.app")
    root = tmp_path / "models/llm"
    root.mkdir(parents=True)
    source = root / "Qwen-Q4_K_M.gguf"
    source.write_bytes(b"fixture-weights")
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("AI_STATION_LLAMA_IMAGE", "ghcr.io/ggml-org/llama.cpp:server-cuda")
    clear_settings_cache()
    module.reset_manager()
    monkeypatch.setattr(RunnerClient, "_client", lambda _: TestClient(module.app))
    return module, source


def _scan(api):
    response = api.post("/api/models/discover", json={})
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "definition-test")
    return api.get("/api/models").json()["items"][0]


def test_explicit_install_verifies_file_and_local_image_without_pull(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama

    module, source = _host(tmp_path, monkeypatch)
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return "sha256:" + "b" * 64
        raise AssertionError("unexpected docker " + str(args))

    monkeypatch.setattr(llama, "docker", docker)
    api = TestClient(app)
    row = _scan(api)
    created = api.post(
        "/api/models/definitions",
        json={
            "file_id": row["id"],
            "name": "Qwen 27B",
            "gpus": [0, 1],
            "context_size": 4096,
            "cache_type": "f16",
        },
    )
    assert created.status_code == 201, created.text
    definition = created.json()
    assert definition["status"] == "unverified"
    assert definition["preset"] == {"gpus": [0, 1], "context_size": 4096, "cache_type": "f16"}
    assert definition["compatibility"]["runtime"] == "llama.cpp"
    assert source.read_bytes() == b"fixture-weights"
    install = api.post(f"/api/models/definitions/{definition['id']}/install", json={})
    assert install.status_code == 202, install.text
    with session_factory()() as session:
        tick(session, "definition-test")
        stored = session.get(ModelDefinition, definition["id"])
        run = session.get(Run, install.json()["id"])
        assert stored.status == "registered"
        assert run.status == "succeeded"
        assert "were downloaded" in run.summary
    assert api.get("/api/artifacts?run_id=" + install.json()["id"]).json()[0]["type"] == "json"
    assert calls and all("pull" not in str(item).lower() for item in calls)
    duplicate = api.post(
        "/api/models/definitions",
        json={"file_id": row["id"], "name": "Other", "gpus": [], "context_size": 4096},
    )
    assert duplicate.status_code == 409
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def test_install_fails_closed_when_llama_image_is_missing(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama

    module, _source = _host(tmp_path, monkeypatch)
    monkeypatch.setattr(llama, "docker", lambda *args, **kwargs: None)
    api = TestClient(app)
    row = _scan(api)
    definition = api.post(
        "/api/models/definitions",
        json={"file_id": row["id"], "name": "Qwen", "gpus": [], "context_size": 4096},
    ).json()
    run = api.post(f"/api/models/definitions/{definition['id']}/install", json={}).json()
    with session_factory()() as session:
        tick(session, "definition-test")
        assert session.get(Run, run["id"]).status == "failed"
        assert session.get(ModelDefinition, definition["id"]).status == "failed"
        assert "never pulled" in session.get(Run, run["id"]).error_message
    load = api.post(f"/api/models/definitions/{definition['id']}/load", json={})
    assert load.status_code == 409
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def test_install_rejects_changed_or_missing_files_and_can_be_canceled(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama

    module, source = _host(tmp_path, monkeypatch)
    monkeypatch.setattr(llama, "docker", lambda *args, **kwargs: "sha256:" + "c" * 64)
    api = TestClient(app)
    row = _scan(api)
    definition = api.post(
        "/api/models/definitions",
        json={"file_id": row["id"], "name": "Qwen", "gpus": [2], "context_size": 8192},
    ).json()
    source.write_bytes(b"changed-weights")
    run = api.post(f"/api/models/definitions/{definition['id']}/install", json={}).json()
    with session_factory()() as session:
        tick(session, "definition-test")
        assert session.get(Run, run["id"]).status == "failed"
        assert "scan it again" in session.get(Run, run["id"]).error_message
        assert session.get(ModelDefinition, definition["id"]).status == "failed"
    source.write_bytes(b"fixture-weights")
    queued = api.post(f"/api/models/definitions/{definition['id']}/install", json={}).json()
    with session_factory()() as session:
        request_cancel(session, session.get(Run, queued["id"]))
        session.commit()
        tick(session, "definition-test")
        assert session.get(Run, queued["id"]).status == "canceled"
        assert session.get(ModelDefinition, definition["id"]).status == "failed"
    assert api.post("/api/models/definitions", json={"roots": ["/etc"]}).status_code == 422
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def test_load_uses_saved_preset_only_after_registration(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama
    from app.llama import instances

    module, _source = _host(tmp_path, monkeypatch)
    monkeypatch.setattr(llama, "docker", lambda *args, **kwargs: "sha256:" + "d" * 64)
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"gpus": [{"index": 2}, {"index": 7}]})
    records = {}
    monkeypatch.setattr(
        RunnerClient,
        "load_llama",
        lambda _, body: records.setdefault(body["instance_id"], {"status": "ready", "alive": True, **body}),
    )
    monkeypatch.setattr(RunnerClient, "inspect_llama", lambda _, identity: records[identity])
    api = TestClient(app)
    row = _scan(api)
    definition = api.post(
        "/api/models/definitions",
        json={
            "file_id": row["id"],
            "name": "Qwen",
            "gpus": [2, 7],
            "context_size": 4096,
            "cache_type": "f16",
        },
    ).json()
    assert api.post(f"/api/models/definitions/{definition['id']}/load", json={}).status_code == 409
    install = api.post(f"/api/models/definitions/{definition['id']}/install", json={}).json()
    with session_factory()() as session:
        tick(session, "definition-test")
        assert session.get(Run, install["id"]).status == "succeeded"
    load = api.post(f"/api/models/definitions/{definition['id']}/load", json={})
    assert load.status_code == 202, load.text
    with session_factory()() as session:
        tick(session, "definition-test")
        instance = instances(session)[0]
        assert instance.metadata_json["gpus"] == [2, 7]
        assert instance.metadata_json["definition_id"] == definition["id"]
        assert instance.status == "ready"
    patched = api.patch(
        f"/api/models/definitions/{definition['id']}", json={"name": "Qwen chat", "context_size": 8192}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Qwen chat"
    assert patched.json()["preset"]["context_size"] == 8192
    assert api.delete(f"/api/models/definitions/{definition['id']}").status_code == 204
    assert api.get("/api/models/definitions").json()["total"] == 0
    with session_factory()() as session:
        assert session.scalar(select(ModelFile.id).where(ModelFile.id == row["id"]))
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def test_non_llama_files_install_without_image_and_cannot_load(tmp_path, monkeypatch):
    module = importlib.import_module("ai_station_runner.app")
    root = tmp_path / "models/image"
    root.mkdir(parents=True)
    (root / "juggernaut.safetensors").write_bytes(b"image-weights")
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    module.reset_manager()
    monkeypatch.setattr(RunnerClient, "_client", lambda _: TestClient(module.app))
    api = TestClient(app)
    row = _scan(api)
    definition = api.post(
        "/api/models/definitions",
        json={"file_id": row["id"], "name": "Juggernaut", "gpus": [], "context_size": 4096},
    ).json()
    assert definition["compatibility"]["operational"] is False
    run = api.post(f"/api/models/definitions/{definition['id']}/install", json={}).json()
    with session_factory()() as session:
        tick(session, "definition-test")
        assert session.get(Run, run["id"]).status == "succeeded"
        assert session.get(ModelDefinition, definition["id"]).status == "registered"
    assert api.post(f"/api/models/definitions/{definition['id']}/load", json={}).status_code == 422
    module.manager().shutdown()
    module.reset_manager()
    clear_settings_cache()


def test_runner_verify_rejects_escape_symlinks_and_extra_fields(tmp_path, monkeypatch):
    from ai_station_runner import llama_runtime as llama
    from ai_station_runner.app import app as runner_app

    root = tmp_path / "models/llm"
    root.mkdir(parents=True)
    model = root / "local.gguf"
    model.write_bytes(b"weights")
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"secret")
    (root / "link.gguf").symlink_to(outside)
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", str(root))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        return "sha256:" + "e" * 64

    monkeypatch.setattr(llama, "docker", docker)
    runner = TestClient(runner_app)
    body = {
        "run_id": str(uuid4()),
        "host_path": str(model),
        "size_bytes": model.stat().st_size,
        "mtime": model.stat().st_mtime,
        "check_image": True,
        "permissions": ["filesystem_read", "manage_models"],
    }
    ok = runner.post("/v1/models/verify", json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["present"] is True and ok.json()["image"]["present"] is True
    assert all(args[0:2] == ("image", "inspect") for args in calls)
    assert runner.post("/v1/models/verify", json={**body, "permissions": []}).status_code == 403
    assert runner.post("/v1/models/verify", json={**body, "host_path": str(outside)}).status_code == 422
    linked = runner.post("/v1/models/verify", json={**body, "host_path": str(root / "link.gguf")})
    assert linked.status_code == 200
    assert linked.json()["symlink"] is True
    assert runner.post("/v1/models/verify", json={**body, "pull": True}).status_code == 422
    clear_settings_cache()
