"""Existing typed llama routes reuse native ownership, identity and completion."""

import hashlib
import json
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import app as host
from ai_station_runner import llama_runtime as llama
from ai_station_runner import native_llama_api as api
from ai_station_runner import runner_platform
from fastapi.testclient import TestClient
from test_darwin_llama import rig as rig
from test_darwin_llama import wait


@pytest.fixture
def client(rig, monkeypatch):
    root = rig["root"]
    settings = SimpleNamespace(host_data_dir=lambda: root, runner_id="native-api-fixture")
    monkeypatch.setattr(api, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(llama, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(runner_platform, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr("ai_station_runner.native_llama_api.get_settings", lambda: settings)
    monkeypatch.setattr(api, "manager", lambda: rig["owner"])
    monkeypatch.setattr(
        api.Environment,
        "resolve_id",
        lambda self, root, identity: (
            {
                "observation": {
                    "operation_id": str(rig["body"].bundle_operation_id),
                    "manifest_sha256": rig["body"].bundle_manifest_sha256,
                }
            }
            if identity == "b" * 64
            else (_ for _ in ()).throw(ValueError("PRIVATE_SDK_PATH"))
        ),
    )
    body = rig["body"].model_dump(
        mode="json",
        exclude={
            "bundle_operation_id",
            "bundle_manifest_sha256",
            "architecture",
            "compute",
            "metal_registry_id",
        },
    )
    body.update(
        runtime_profile="llamacpp-native-darwin-arm64-b12032-v2",
        environment_id="b" * 64,
        app_owned=True,
        gpus=[],
        cache_type="q8_0",
    )
    with TestClient(host.app) as value:
        yield value, body


def test_typed_load_duplicate_stream_identity_stop_and_private_logs(client, rig):
    client, body = client
    identity = body["instance_id"]
    first = client.post("/v1/llama/load", json=body)
    assert first.status_code == 200, first.text
    ready = wait(rig["owner"], identity, "ready")
    assert client.get("/v1/llama/" + identity).json()["pid"] == ready["pid"]
    assert client.post("/v1/llama/load", json=body).json()["pid"] == ready["pid"]
    other_id = str(uuid4())
    processes = rig["owner"].processes
    processes.start(
        run_id=other_id,
        executor="short_job",
        cwd=rig["root"],
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
    )
    processes.shutdown(preserve_executors=frozenset({"llama_native"}))
    assert not processes.inspect(other_id)["alive"]
    assert processes.inspect(body["run_id"])["alive"]
    assert client.post("/v1/llama/load", json={**body, "context_size": 8192}).status_code == 409
    assert client.post("/v1/llama/load", json={**body, "permissions": []}).status_code == 403
    assert client.post("/v1/llama/load", json={**body, "environment_id": "c" * 64}).status_code == 409
    request = dict(
        model=identity,
        messages=[dict(role="user", content="PRIVATE_PROMPT")],
        temperature=0,
        max_tokens=64,
        stream=True,
    )
    for kind in ("chat", "coding"):
        response = client.post(f"/v1/llama/{identity}/{kind}/completions", json=request)
        assert response.status_code == 200 and "FAKE_NATIVE_OK" in response.text
    wrong = client.post(f"/v1/llama/{identity}/chat/completions", json={**request, "model": str(uuid4())})
    assert wrong.status_code == 409
    assert client.post(f"/v1/llama/{identity}/stop", json={"permissions": []}).status_code == 403
    stopped = client.post(f"/v1/llama/{identity}/stop", json={"permissions": ["manage_models"]})
    assert stopped.status_code == 200
    assert wait(rig["owner"], identity, "stopped")["alive"] is False
    assert client.post("/v1/llama/load", json=body).json()["status"] == "stopped"
    assert client.post(f"/v1/llama/{identity}/chat/completions", json=request).status_code == 409
    process = rig["owner"].processes.inspect(body["run_id"])
    assert process["logs_suppressed"] is True
    assert process["stdout"] == process["stderr_tail"] == ""
    assert str(rig["body"].bundle_operation_id) not in json.dumps(ready)


def test_typed_stop_before_dispatch_and_unknown_identity(client, rig):
    client, body = client
    identity = str(uuid4())
    assert client.get("/v1/llama/" + identity).status_code == 404
    assert (
        client.post(f"/v1/llama/{identity}/stop", json={"permissions": ["manage_models"]}).status_code == 200
    )
    result = client.post("/v1/llama/load", json={**body, "instance_id": identity})
    assert result.status_code == 200 and result.json()["status"] == "stopped"
    assert not rig["owner"].processes._live


@pytest.mark.parametrize(
    "change",
    [
        {"gpus": [0]},
        {"app_owned": False},
        {"model_path": "/private/secret.gguf"},
        {"bundle_operation_id": str(uuid4())},
        {"command": "anything"},
        {"compute": "metal"},
        {"cache_type": "f16"},
        {"startup_deadline_at": "2026-01-01T00:00:00"},
    ],
)
def test_caller_cannot_choose_binary_argv_private_sdk_or_unqualified_devices(client, rig, change):
    client, body = client
    result = client.post("/v1/llama/load", json={**body, **change})
    assert result.status_code == 422 and not rig["owner"].processes._live


def test_platform_profiles_never_fall_back_to_container_or_native_execution(client, rig, monkeypatch):
    client, body = client
    legacy = {
        k: v
        for k, v in body.items()
        if k not in {"runtime_profile", "environment_id", "startup_deadline_at", "ram_mib"}
    }
    assert client.post("/v1/llama/load", json=legacy).status_code == 503
    monkeypatch.setattr(api, "sys", SimpleNamespace(platform="linux"))
    assert client.post("/v1/llama/load", json=body).status_code == 503
    assert not rig["owner"].processes._live


def test_unknown_native_ownership_errors_are_private(client, rig, monkeypatch):
    client, body = client

    def uncertain(*args):
        raise ValueError("PRIVATE_PROCESS_PATH")

    monkeypatch.setattr(rig["owner"], "inspect", uncertain)
    result = client.get("/v1/llama/" + body["instance_id"])
    assert result.status_code == 409 and "PRIVATE_PROCESS_PATH" not in result.text


def test_native_singleton_reuses_normal_app_process_manager(tmp_path, monkeypatch):
    owner = object()
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(api, "SOCKET_PARENT", tmp_path)
    monkeypatch.setattr(api, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(host, "manager", lambda: owner)
    monkeypatch.setattr(
        "ai_station_runner.native_llama_api.get_settings", lambda: SimpleNamespace(host_data_dir=lambda: root)
    )
    instances = []

    class Native:
        def __init__(self, root, sockets, *, processes):
            assert processes is owner
            self.root, self.processes, self.sockets = root, processes, sockets
            self.closed = False
            instances.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(api, "NativeLlamaManager", Native)
    api.close()
    try:
        first = api.manager()
        assert api.manager() is first and len(instances) == 1
        assert first.sockets.parent == tmp_path and first.sockets.parent != root
        api.close()
        assert first.closed
        assert api.manager() is not first and len(instances) == 2
    finally:
        api.close()


@pytest.mark.parametrize("change", ["symlink", "public", "unknown", "marker"])
def test_socket_storage_does_not_adopt_changed_or_unrecognized_roots(tmp_path, monkeypatch, change):
    monkeypatch.setattr(api, "SOCKET_PARENT", tmp_path)
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    expected = tmp_path / f"ais-m-{os.geteuid()}-{hashlib.sha256(os.fsencode(root)).hexdigest()[:20]}"
    if change == "symlink":
        expected.symlink_to(root)
    else:
        expected.mkdir(mode=0o777 if change == "public" else 0o700)
        if change == "public":
            expected.chmod(0o777)
        elif change == "unknown":
            (expected / "unknown").write_text("keep")
        else:
            (expected / "owner.json").write_text("{}")
    with pytest.raises(ValueError):
        api.socket_storage(root)
