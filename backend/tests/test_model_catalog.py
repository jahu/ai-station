import json

from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import ModelFile, Run, RuntimeInstance, Task
from app.providers import ProviderError
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def files():
    with session_factory()() as session:
        result = []
        for name, availability in [
            ("coder.gguf", "present"),
            ("missing.gguf", "missing"),
            ("mmproj.gguf", "present"),
        ]:
            row = ModelFile(
                host_path="/configured/models/" + name,
                filename=name,
                category="llm",
                format="gguf",
                availability=availability,
            )
            session.add(row)
            session.flush()
            result.append(row.id)
        session.commit()
        return result


def test_catalog_is_metadata_only_and_includes_unloaded_missing_and_server_choices(monkeypatch):
    ids = files()

    def forbidden(*args, **kwargs):
        raise AssertionError("Default catalog must not contact any model server")

    monkeypatch.setattr(LocalChatProvider, "models", forbidden)
    with TestClient(app) as client:
        first = client.get("/api/chat/model-catalog")
        assert first.status_code == 200, first.text
        payload = first.json()
        choices = {m["model_key"]: m for m in payload["models"]}
        assert choices["llamacpp:" + ids[0]]["availability"] == "loads_when_needed"
        assert choices["llamacpp:" + ids[1]]["availability"] == "unavailable"
        assert "missing" in choices["llamacpp:" + ids[1]]["unavailable_reason"]
        assert "llamacpp:" + ids[2] not in choices
        assert all(not m["reasoning_capability"]["verified"] for m in choices.values())
        assert (
            client.get("/api/chat/model-catalog").json()["providers"][0]["config_version"]
            == payload["providers"][0]["config_version"]
        )
        assert "/configured/models" not in first.text
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 0
        assert session.scalar(select(func.count()).select_from(Task)) == 0
        assert session.scalar(select(func.count()).select_from(RuntimeInstance)) == 0


def test_catalog_discovers_only_explicit_provider_and_redacts_secrets(monkeypatch):
    monkeypatch.setenv("CATALOG_KEY", "sk-private-catalog-key")
    discovered = []
    monkeypatch.setattr(
        "app.chat_providers.discover_models",
        lambda endpoint, **kwargs: discovered.append(endpoint) or ["cloud-model", "cloud-model"],
    )
    with TestClient(app) as client:
        client.post(
            "/api/chat/providers",
            json={
                "key": "cloud",
                "name": "Cloud",
                "location": "external",
                "endpoint": "https://models.example.test/v1",
                "secret_ref": "env:CATALOG_KEY",
                "default_model": "configured",
            },
        ).raise_for_status()
        base = client.get("/api/chat/model-catalog").json()
        assert discovered == []
        assert next(m for m in base["models"] if m["provider_key"] == "cloud")["availability"] == "configured"
        found = client.get("/api/chat/model-catalog", params={"discover_provider": "cloud"})
        assert discovered == ["https://models.example.test/v1"]
        assert "sk-private-catalog-key" not in found.text and "CATALOG_KEY" not in found.text
        models = [m for m in found.json()["models"] if m["provider_key"] == "cloud"]
        assert {m["model_key"] for m in models} == {"cloud-model", "configured"}
        assert all(m["location"] == "external" for m in models)
        assert next(m for m in models if m["model_key"] == "configured")["availability"] == "configured"
        assert len({m["model_ref"] for m in models}) == len(models)
        assert client.get("/api/chat/model-catalog?discover_provider=unknown").status_code == 404


def test_offline_endpoint_does_not_hide_owned_ggufs(monkeypatch):
    ids = files()

    def offline(*args):
        raise ProviderError("Fixture endpoint offline")

    monkeypatch.setattr(LocalChatProvider, "models", offline)
    with TestClient(app) as client:
        response = client.get("/api/chat/model-catalog", params={"discover_provider": LocalChatProvider.key})
        assert response.status_code == 200
        assert (
            next(m for m in response.json()["models"] if m["model_key"] == "llamacpp:" + ids[0])[
                "availability"
            ]
            == "loads_when_needed"
        )
        assert response.json()["providers"][0]["error"] == "Fixture endpoint offline"
        assert "secret_ref" not in json.dumps(response.json())


def test_catalog_preserves_owned_runtime_inspection_gate_and_known_context():
    model_id = files()[0]
    with session_factory()() as session:
        instance = RuntimeInstance(
            runtime_key="llama.cpp",
            name="Owned fixture",
            ownership="managed",
            status="unknown",
            metadata_json={"model_file_id": model_id, "n_ctx_train": 131072},
        )
        session.add(instance)
        session.flush()
        instance_id = instance.id
        session.commit()
    with TestClient(app) as client:
        choice = next(
            m
            for m in client.get("/api/chat/model-catalog").json()["models"]
            if m["model_key"] == "llamacpp:" + model_id
        )
        assert choice["availability"] == "needs_inspection" and choice["unavailable_reason"]
        with session_factory()() as session:
            session.get(RuntimeInstance, instance_id).status = "ready"
            session.commit()
        choice = next(
            m
            for m in client.get("/api/chat/model-catalog").json()["models"]
            if m["model_key"] == "llamacpp:" + model_id
        )
        assert choice["availability"] == "ready" and choice["context_limit"] == 131072
