"""Guided CPU memory setup exposes public sources, never foreign activity."""

from app import embedding_models
from app.api import app
from app.config import get_settings
from fastapi.testclient import TestClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def test_memory_catalog_exposes_fixed_sources_and_storage_without_preparing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reading setup must not download or load a model")

    monkeypatch.setattr("app.embedding_download.download_file", forbidden)
    result = TestClient(app).get("/api/memory/embeddings/setup")
    assert result.status_code == 200
    body = result.json()
    assert body["can_prepare"] and body["prepare_run"] is None
    local = body["local_model"]
    assert local["device"] == "CPU" and local["license"] == "MIT"
    assert local["source_url"].endswith("/tree/" + embedding_models.REVISION)
    assert len(local["files"]) == 2
    assert sum(f["size_bytes"] for f in local["files"]) == local["size_bytes"]
    for item in local["files"]:
        assert "/resolve/" + embedding_models.REVISION + "/" in item["url"]
        assert item["sha256"] == embedding_models.FILES[item["filename"]]["sha256"]
    assert local["storage"]["cached_bytes_estimate"] == 0
    assert local["storage"]["required_bytes"] > local["size_bytes"]


def test_cached_memory_bytes_are_only_an_estimate_until_existing_prepare_verifies(monkeypatch):
    root = get_settings().data_dir
    folder = embedding_models.directory(root, create=True)
    specs = {"model_quantized.onnx": {"size": 4, "sha256": "a" * 64, "remote": "model.onnx"}}
    monkeypatch.setattr(embedding_models, "FILES", specs)
    (folder / "model_quantized.onnx").write_bytes(b"fake")
    status = TestClient(app).get("/api/memory/embeddings/setup").json()["local_model"]
    assert status["storage"]["cached_bytes_estimate"] == 4
    assert not status["installed"]
    assert status["storage"]["required_bytes"] >= 4 + 64 * 1024**2


def test_memory_storage_estimate_does_not_follow_a_model_symlink(tmp_path, monkeypatch):
    root = get_settings().data_dir
    folder = embedding_models.directory(root, create=True)
    external = tmp_path / "outside-model"
    external.write_bytes(b"private")
    monkeypatch.setattr(embedding_models, "FILES", {"model_quantized.onnx": {"size": 7}})
    (folder / "model_quantized.onnx").symlink_to(external)
    assert embedding_models.storage(root)["cached_bytes_estimate"] == 0


def test_account_members_can_read_shared_memory_recipe_but_cannot_prepare(accounts):
    admin, alice, _ = accounts
    owner = admin.get("/api/memory/embeddings/setup").json()
    member = alice.get("/api/memory/embeddings/setup").json()
    assert owner["can_prepare"] is True and member["can_prepare"] is False
    assert member["local_model"]["files"] == owner["local_model"]["files"]
    assert member["prepare_run"] is None and member["health_run"] is None
    assert (
        alice.post(
            "/api/memory/embeddings/prepare", json={"expected_revision": member["revision"]}
        ).status_code
        == 403
    )
