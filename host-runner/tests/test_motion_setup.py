"""Metadata activation never downloads/runs Docker images or reads arbitrary files."""

import copy
import json
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import motion_image, motion_runtime
from ai_station_runner import motion_setup as native
from ai_station_runner.config import Settings, clear_settings_cache
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def activation(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_MOTION_IMAGE", "")
    clear_settings_cache()
    monkeypatch.setattr(native, "QUALIFIED", True)
    monkeypatch.setattr(native, "available", lambda: True)
    monkeypatch.setattr(native, "platform_supported", lambda: True)
    state = {
        "present": True,
        "calls": [],
        "connection": {"host": "unix:///fixture.sock", "daemon_id": "fixture-daemon"},
    }
    state["image"] = {
        "Id": "sha256:" + "b" * 64,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Entrypoint": motion_image.ENTRYPOINT,
            "User": "1000:1000",
            "Cmd": [],
            "Labels": {"ai-station.motion.protocol": "1", "ai-station.motion.recipe": motion_image.recipe()},
        },
    }

    def docker(args, **kwargs):
        state["calls"].append(args)
        assert args[:2] in (["image", "ls"], ["image", "inspect"]), (
            "No install/container/Docker mutation is permitted in activation"
        )
        if args[1] == "ls":
            return state["image"]["Id"] if state["present"] else ""
        return json.dumps(state["image"]) if state["present"] else ""

    for module in (native, motion_image):
        monkeypatch.setattr(module, "docker", docker)
        monkeypatch.setattr(module, "connection", lambda: copy.deepcopy(state["connection"]))
    application = FastAPI()
    application.include_router(native.router)
    with TestClient(application) as client:
        yield SimpleNamespace(client=client, state=state, root=tmp_path)
    clear_settings_cache()


def request():
    return {
        "run_id": str(uuid4()),
        "profile": native.PROFILE,
        "manifest_sha256": native.fingerprint(native.recipe()),
        "deadline_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "permissions": ["manage_models", "network_read", "workspace_write"],
    }


def test_activate_existing_image_and_replay_receipt_without_republishing(activation):
    a = activation
    catalog = a.client.get("/v1/setup/motion").json()
    assert catalog["installation_available"] and not catalog["usable_image"]
    body = request()
    response = a.client.post("/v1/setup/motion/prepare", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded" and response.json()["alive"] is False
    path = a.root / "runtime/motion/selection.json"
    before = path.stat().st_mtime_ns
    assert a.client.post("/v1/setup/motion/prepare", json=body).json() == response.json()
    assert path.stat().st_mtime_ns == before
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["status"] == "succeeded"
    assert a.client.get("/v1/setup/motion").json()["usable_image"]
    assert (
        a.client.post(
            "/v1/setup/motion/prepare",
            json={**body, "deadline_at": (datetime.now(UTC) + timedelta(minutes=11)).isoformat()},
        ).status_code
        == 409
    )


def test_cancel_before_send_fences_publication_and_late_stop_keeps_shared_preparation(activation):
    a = activation
    body = request()
    cancel = {"profile": native.PROFILE, "permissions": body["permissions"]}
    assert (
        a.client.post("/v1/setup/motion/" + body["run_id"] + "/cancel", json=cancel).json()["status"]
        == "canceled"
    )
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "canceled"
    assert not (a.root / "runtime/motion/selection.json").exists()
    body = request()
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "succeeded"
    assert (
        a.client.post("/v1/setup/motion/" + body["run_id"] + "/cancel", json=cancel).json()["status"]
        == "canceled"
    )
    assert a.client.get("/v1/setup/motion").json()["usable_image"]


def test_lost_selection_acknowledgement_is_observed_without_replay(activation, monkeypatch):
    a = activation
    original = native.atomic_json
    writes = []

    def lost(folder, name, value):
        original(folder, name, value)
        if name == "selection.json":
            writes.append(name)
            raise OSError("Synthetic lost acknowledgement after atomic publication")

    monkeypatch.setattr(native, "atomic_json", lost)
    body = request()
    response = a.client.post("/v1/setup/motion/prepare", json=body)
    assert response.status_code == 200 and response.json()["status"] == "succeeded"
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "succeeded"
    assert writes == ["selection.json"]


def test_interrupted_selection_is_not_automatically_reexecuted(activation, monkeypatch):
    a = activation
    original = native.atomic_json

    def lost(folder, name, value):
        if name == "selection.json":
            raise OSError("Synthetic crash before atomic publication")
        original(folder, name, value)

    monkeypatch.setattr(native, "atomic_json", lost)
    body = request()
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "interrupted"
    monkeypatch.setattr(native, "atomic_json", original)
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "interrupted"
    assert not (a.root / "runtime/motion/selection.json").exists()


@pytest.mark.parametrize("change", ["image_gone", "daemon_changed", "recipe_changed"])
def test_changed_native_identity_cannot_reconcile_success(activation, monkeypatch, change):
    a = activation
    body = request()
    assert a.client.post("/v1/setup/motion/prepare", json=body).json()["status"] == "succeeded"
    if change == "image_gone":
        a.state["present"] = False
    elif change == "daemon_changed":
        a.state["connection"]["daemon_id"] = "another-daemon"
    else:
        previous = native.recipe()
        monkeypatch.setattr(native, "recipe", lambda: {**previous, "activation_sha256": "c" * 64})
    assert a.client.get("/v1/setup/motion/" + body["run_id"]).json()["status"] == "interrupted"


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"command": ["id"]}, 422),
        ({"image": "untrusted/image"}, 422),
        ({"permissions": ["workspace_write"]}, 403),
        ({"run_id": "../../elsewhere"}, 422),
        ({"manifest_sha256": "0" * 64}, 409),
    ],
)
def test_typed_metadata_boundary_rejects_unreviewed_authority(activation, changes, status):
    assert (
        activation.client.post("/v1/setup/motion/prepare", json={**request(), **changes}).status_code
        == status
    )
    assert not (activation.root / "runtime/motion/selection.json").exists()


def test_missing_or_wrong_architecture_image_never_enables_fresh_installation(activation):
    a = activation
    a.state["image"]["Architecture"] = "arm64"
    assert a.client.get("/v1/setup/motion").json()["installation_available"] is False
    assert a.client.post("/v1/setup/motion/prepare", json=request()).status_code == 409
    a.state["present"] = False
    assert a.client.get("/v1/setup/motion").json()["installation_available"] is False


def test_selection_parent_symlink_cannot_create_or_write_outside_storage(activation, tmp_path):
    a = activation
    outside = tmp_path / "outside"
    outside.mkdir()
    (a.root / "runtime").mkdir(exist_ok=True)
    (a.root / "runtime/motion").symlink_to(outside, target_is_directory=True)
    response = a.client.post("/v1/setup/motion/prepare", json=request())
    assert response.status_code == 200 and response.json()["status"] == "interrupted"
    assert list(outside.iterdir()) == []


def test_new_selection_invalidates_a_cached_missing_renderer(activation, monkeypatch):
    def submit(fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    monkeypatch.setattr(motion_runtime, "_pool", SimpleNamespace(submit=submit))
    monkeypatch.setattr(motion_runtime, "_probe", None)
    monkeypatch.setattr(motion_runtime, "available", lambda: True)
    assert motion_runtime.capabilities()["available"] is False
    assert activation.client.post("/v1/setup/motion/prepare", json=request()).json()["status"] == "succeeded"
    assert motion_runtime.capabilities()["available"] is True
