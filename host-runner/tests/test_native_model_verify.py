"""Native inspection never grants host browsing, Docker or caller-chosen SDK paths."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import native_model_verify as verifier
from test_native_llama_api import client as client
from test_native_llama_api import rig as rig


@pytest.fixture
def coordinates(client, rig, monkeypatch):
    api, load = client
    monkeypatch.setattr(
        verifier, "platform", SimpleNamespace(system=lambda: "Darwin", machine=lambda: "arm64")
    )
    monkeypatch.setattr(verifier, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: rig["root"]))
    body = {
        key: load[key]
        for key in [
            "run_id",
            "app_owned",
            "model_sha256",
            "size_bytes",
            "mtime",
            "permissions",
            "runtime_profile",
            "environment_id",
            "context_size",
        ]
    }
    body.update(host_path=load["model_path"], check_context=True)
    return api, body


def test_native_owned_file_context_and_sdk_return_no_private_setup_coordinates(coordinates, rig):
    api, body = coordinates
    response = api.post("/v1/models/verify", json=body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["matches_observation"] and report["present"] and report["image"] is None
    assert report["cpu"]["ram_mib"] == rig["body"].ram_mib
    assert report["cpu"]["context_size"] == rig["body"].context_size
    assert report["native"]["environment_id"] == body["environment_id"]
    assert report["native"]["memory_enforcement"] == "admission_only"
    assert report["host_path"] is None and report["relative_path"] == body["host_path"]
    assert not any(
        value in json.dumps(report) for value in [str(rig["root"]), str(rig["body"].bundle_operation_id)]
    )
    assert not rig["owner"].processes._live


@pytest.mark.parametrize(
    "change,status",
    [
        ({"permissions": []}, 403),
        ({"environment_id": "c" * 64}, 409),
        ({"host_path": "/private/secret.gguf"}, 422),
        ({"app_owned": False}, 422),
        ({"check_context": False}, 422),
        ({"check_image": True}, 422),
        ({"environment_id": None}, 422),
        ({"context_size": 513}, 422),
        ({"command": "anything"}, 422),
        ({"operation_id": str(uuid4())}, 422),
    ],
)
def test_native_metadata_cannot_bypass_identity_or_permissions(coordinates, rig, change, status):
    api, body = coordinates
    response = api.post("/v1/models/verify", json={**body, **change})
    assert response.status_code == status, response.text
    assert "PRIVATE" not in response.text and not rig["owner"].processes._live


def test_native_metadata_detects_stale_observation_and_wrong_architecture(coordinates, rig, monkeypatch):
    api, body = coordinates
    response = api.post("/v1/models/verify", json={**body, "mtime": body["mtime"] + 10})
    assert response.status_code == 200 and not response.json()["matches_observation"]
    monkeypatch.setattr(verifier.platform, "machine", lambda: "x86_64")
    assert api.post("/v1/models/verify", json=body).status_code == 503
    assert not rig["owner"].processes._live


def test_legacy_linux_inspection_is_not_implicitly_enabled_on_mac(coordinates, monkeypatch):
    api, body = coordinates
    from ai_station_runner import model_verify

    monkeypatch.setattr(model_verify, "sys", SimpleNamespace(platform="darwin"))
    legacy = {k: v for k, v in body.items() if k not in {"runtime_profile", "environment_id", "context_size"}}
    assert api.post("/v1/models/verify", json=legacy).status_code == 503
