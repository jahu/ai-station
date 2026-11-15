import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import live_api, runner_platform
from ai_station_runner.live_contract import LiveRequest
from ai_station_runner.processes import ProcessManager
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def native(tmp_path, monkeypatch):
    (tmp_path / "runtime").mkdir(mode=0o700)
    monkeypatch.setattr(live_api, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: tmp_path))
    monkeypatch.setattr(live_api.runtime_install, "get_settings", live_api.get_settings)
    monkeypatch.setattr(live_api, "scope_prefix", lambda *args: [])
    ready = {
        "available": True,
        "eligible_gpu_indices": [3, 7],
        "managed_runtime": {
            "profile": "live-identity-linux-x86-64-python312-v1",
            "manifest_sha256": "a" * 64,
            "environment_id": "b" * 64,
        },
    }
    monkeypatch.setattr(live_api, "capabilities", lambda: ready)
    manager = ProcessManager(tmp_path, grace_seconds=0.05)
    original = manager.start
    launches = []

    def fake_inference(**kwargs):
        launches.append(kwargs)
        return original(**{**kwargs, "argv": [sys.executable, "-c", "import time;time.sleep(30)"]})

    monkeypatch.setattr(manager, "start", fake_inference)
    body = LiveRequest(
        run_id=uuid4(),
        managed_runtime=ready["managed_runtime"],
        image={"relative_path": "artifacts/face.jpg", "size_bytes": 3, "sha256": "c" * 64},
        gpus=[3],
        seed=42,
        deadline_at=time.time() + 60,
        permissions=["filesystem_read", "workspace_write"],
    )
    yield manager, body, launches
    manager.shutdown()


def test_lost_start_reply_adopts_same_owned_process_and_immutable_request(native):
    manager, body, launches = native
    first = live_api.start(manager, body)
    second = live_api.start(manager, body)
    assert second["pid"] == first["pid"] and len(launches) == 1
    assert launches[0]["executor"] == "live_identity"
    assert "ai_station_runner.live_job" in launches[0]["argv"]
    assert not {"HF_TOKEN", "OPENAI_API_KEY"} & launches[0]["env"].keys()
    with pytest.raises(HTTPException) as changed:
        live_api.start(manager, body.model_copy(update={"seed": 43}))
    assert changed.value.status_code == 409 and len(launches) == 1
    stopped = live_api.cancel(manager, body.run_id)
    assert stopped["status"] == "canceled" and not stopped["alive"]
    with pytest.raises(HTTPException):
        live_api.start(manager, body)


def test_stop_before_dispatch_fences_a_late_start(native):
    manager, body, launches = native
    result = live_api.cancel(manager, body.run_id)
    assert result["status"] == "canceled"
    with pytest.raises(HTTPException) as stopped:
        live_api.start(manager, body)
    assert stopped.value.status_code == 409 and launches == []


def test_live_stop_cannot_signal_a_different_executor(native):
    manager, body, launches = native
    manager.start(run_id=str(body.run_id), executor="unrelated", argv=["ignored"], cwd=manager.data_dir)
    with pytest.raises(HTTPException) as error:
        live_api.cancel(manager, body.run_id)
    assert error.value.status_code == 409
    assert manager.inspect(str(body.run_id))["alive"]


@pytest.mark.parametrize("platform", ["linux", "darwin", "unknown"])
def test_platform_dependency_supports_duplex_connections_without_bypassing_admission(monkeypatch, platform):
    app = FastAPI(dependencies=[Depends(runner_platform.require_qualified_operation)])

    @app.websocket("/v1/live/{identity}/stream")
    async def live(websocket: WebSocket, identity: str):
        await websocket.accept()
        await websocket.send_text("admitted")
        await websocket.close()

    monkeypatch.setattr(runner_platform, "sys", SimpleNamespace(platform=platform))
    with TestClient(app) as client:
        if platform == "linux":
            with client.websocket_connect("/v1/live/test/stream") as connection:
                assert connection.receive_text() == "admitted"
        else:
            with pytest.raises(WebSocketDisconnect) as blocked:
                with client.websocket_connect("/v1/live/test/stream"):
                    pytest.fail("Unqualified platform reached live transport")
            assert blocked.value.code == 1008
