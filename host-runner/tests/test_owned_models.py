"""Fixed app-data model references preserve the legacy native load contract."""

import hashlib
from uuid import uuid4

import pytest
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.llama_runtime import Load
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.owned_models import owned_model
from fastapi import HTTPException
from test_llama_runtime import runtime as runtime


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", "")
    clear_settings_cache()
    data = b"GGUF" + b"neutral synthetic model bytes"
    sha = hashlib.sha256(data).hexdigest()
    path = tmp_path / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    path.chmod(0o444)
    yield path, sha
    clear_settings_cache()


def test_owned_namespace_needs_no_external_model_roots_and_returns_no_host_path(stored):
    path, sha = stored
    assert owned_model("models/store/" + sha, sha) == path
    response = verify_model(
        VerifyModel(
            run_id=uuid4(),
            host_path="models/store/" + sha,
            app_owned=True,
            model_sha256=sha,
            size_bytes=path.stat().st_size,
            mtime=path.stat().st_mtime,
            permissions=["filesystem_read", "manage_models"],
        )
    )
    assert response["present"] and response["matches_observation"]
    assert response["host_path"] is None and response["relative_path"] == "models/store/" + sha
    assert response["sha256"] == sha and response["checksum_source"] == "verified_download"


@pytest.mark.parametrize(
    "path",
    [
        "../db/secrets",
        "/etc/passwd",
        "models/store/../db/secrets",
        "artifacts/" + "a" * 64,
        "models/store/" + "b" * 64,
    ],
)
def test_owned_references_cannot_select_another_storage_namespace(stored, path):
    _, sha = stored
    with pytest.raises((ValueError, HTTPException)):
        Load(
            instance_id=uuid4(),
            run_id=uuid4(),
            model_path=path,
            app_owned=True,
            model_sha256=sha,
            size_bytes=1,
            mtime=1,
            gpus=[],
            permissions=[],
        )


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_writable_model_is_rejected(stored, mode):
    path, sha = stored
    path.chmod(mode)
    with pytest.raises(HTTPException, match="unavailable or changed"):
        owned_model("models/store/" + sha, sha)


def test_symlink_and_hard_linked_models_are_not_adopted(stored):
    import os

    path, sha = stored
    other = path.parent / "other"
    os.link(path, other)
    with pytest.raises(HTTPException):
        owned_model("models/store/" + sha, sha)
    other.unlink()
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(HTTPException):
        owned_model("models/store/" + sha, sha)


def test_legacy_load_serialization_stays_identical_without_new_source_fields():
    original = {
        "instance_id": str(uuid4()),
        "run_id": str(uuid4()),
        "model_path": "/models/existing.gguf",
        "size_bytes": 100,
        "mtime": 1.0,
        "gpus": [7],
        "context_size": 4096,
        "cache_type": "f16",
        "projector": None,
        "permissions": ["filesystem_read", "manage_models"],
    }
    assert Load.model_validate(original).model_dump(mode="json") == original


def test_checksum_cannot_be_attached_to_an_unmarked_host_source():
    with pytest.raises(ValueError):
        VerifyModel(
            run_id=uuid4(),
            host_path="/models/a.gguf",
            model_sha256="a" * 64,
            size_bytes=1,
            mtime=1,
            permissions=[],
        )


def owned_load(runtime, monkeypatch):
    from ai_station_runner import llama_runtime

    root, original, state = runtime
    data = b"GGUFneutral-model"
    sha = hashlib.sha256(data).hexdigest()
    path = root / "models/store" / sha
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    path.chmod(0o444)
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", "")
    clear_settings_cache()
    body = llama_runtime.Load.model_validate(
        {
            **original.model_dump(mode="json"),
            "model_path": "models/store/" + sha,
            "app_owned": True,
            "model_sha256": sha,
            "size_bytes": len(data),
            "mtime": path.stat().st_mtime,
        }
    )
    return path, body, state


def test_owned_model_load_mounts_only_resolved_file_and_replays_immutable_request(runtime, monkeypatch):
    from ai_station_runner import llama_runtime

    path, body, state = owned_load(runtime, monkeypatch)
    assert llama_runtime.load(body)["alive"]
    assert llama_runtime.load(body)["alive"]
    creates = [call for call in state["calls"] if call[0] == "create"]
    assert len(creates) == 1
    assert any(str(path) in arg and "readonly" in arg for arg in creates[0])
    assert llama_runtime.manifest(body.instance_id)["request"]["model_path"].startswith("models/store/")
    assert not llama_runtime.manifest(body.instance_id)["request"]["model_path"].startswith("/")


def test_interrupted_before_create_rechecks_owned_source_before_retrying(runtime, monkeypatch):
    from ai_station_runner import llama_runtime

    path, body, state = owned_load(runtime, monkeypatch)
    original = llama_runtime.docker

    def fail(*args, **kwargs):
        if args[0] == "create":
            raise RuntimeError("Synthetic worker loss before container creation")
        return original(*args, **kwargs)

    monkeypatch.setattr(llama_runtime, "docker", fail)
    with pytest.raises(RuntimeError):
        llama_runtime.load(body)
    path.chmod(0o644)
    monkeypatch.setattr(llama_runtime, "docker", original)
    with pytest.raises(HTTPException, match="unavailable or changed"):
        llama_runtime.load(body)
    assert not any(call[0] == "create" for call in state["calls"])
