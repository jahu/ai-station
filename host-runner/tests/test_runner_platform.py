"""The normal typed Runner selects native ownership without enabling other adapters."""

import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from ai_station_runner import app as host
from ai_station_runner import runner_platform as native
from ai_station_runner.darwin_processes import DarwinProcessManager
from ai_station_runner.processes import ProcessManager
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from test_darwin_processes import candidate_kernel as candidate_kernel


@pytest.mark.parametrize("platform,kind", [("linux", ProcessManager), ("darwin", DarwinProcessManager)])
def test_factory_selects_the_actual_platform_without_changing_its_journal(
    tmp_path, monkeypatch, platform, kind
):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform=platform))
    manager = native.create_process_manager(tmp_path, grace_seconds=0.125)
    assert type(manager) is kind
    assert manager.grace_seconds == 0.125
    assert manager.path == tmp_path / "runtime/processes.json"
    assert manager._load() == {}


@pytest.mark.parametrize("platform", ["win32", "freebsd14", "unknown"])
def test_unknown_platform_cannot_create_storage_or_recover_a_process(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform=platform))
    root = tmp_path / "not-created"
    with pytest.raises(RuntimeError, match="qualified Linux or macOS"):
        native.create_process_manager(root)
    assert not root.exists()


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        host_data_dir=lambda: tmp_path, cancel_grace_seconds=0.05, runner_id="platform-fixture"
    )
    host.reset_manager()
    monkeypatch.setattr(host, "get_settings", lambda: settings)
    with TestClient(host.app) as value:
        yield value
    if host._manager is not None:
        host._manager.shutdown()
    host.reset_manager()


# Every currently registered operation outside the native allowlist must refuse
# before handler execution or request-body parsing. This also covers included
# routers, not just routes defined in app.py.
_UNQUALIFIED = [
    (method, route.path)
    for route in host.app.routes
    if hasattr(route, "dependant")
    for method in sorted(route.methods)
    if (method, route.path) not in native._DARWIN_OPERATIONS
]


@pytest.mark.parametrize("method,path", _UNQUALIFIED)
def test_unqualified_mac_operation_cannot_reach_its_handler(client, monkeypatch, method, path):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    # Also exercise UUID-bearing included routes; no body, image/runtime setup,
    # Docker access or configured credentials may be needed to deny dispatch.
    for key in ("run_id", "instance_id", "operation_id", "environment_id"):
        path = path.replace("{" + key + "}", str(uuid4()))
    response = client.request(method, path, json={})
    assert response.status_code == 503, response.text
    assert "not yet qualified" in response.json()["detail"]
    assert host._manager is None


def test_late_included_routes_do_not_implicitly_gain_mac_execution(monkeypatch):
    application = FastAPI(dependencies=[Depends(native.require_qualified_operation)])
    router = APIRouter()

    @router.post("/v1/process/{run_id}/new-operation")
    def unqualified(run_id: str):
        raise AssertionError("An unknown adapter executed")

    application.include_router(router)
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    with TestClient(application) as client:
        assert client.post(f"/v1/process/{uuid4()}/new-operation").status_code == 503


def test_linux_retains_current_capabilities_and_health_routes(client, monkeypatch):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(host, "speech_capabilities", lambda: {"available": True, "fixture": "linux"})
    assert client.get("/v1/audio/capabilities").json() == {"available": True, "fixture": "linux"}
    assert client.get("/health").json()["runner_id"] == "platform-fixture"


@pytest.mark.parametrize("platform", ["darwin", "unknown"])
def test_platform_policy_cannot_be_overridden_by_http_fields(client, monkeypatch, platform):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform=platform))
    response = client.post(
        "/v1/llama/load?platform=linux",
        json={"platform": "linux", "runtime_profile": "llamacpp-cpu-linux-amd64-v1"},
        headers={"X-Platform": "linux"},
    )
    assert response.status_code == 503
    assert host._manager is None


def test_normal_mac_runner_reattaches_and_http_stops_only_its_owned_process(
    client, tmp_path, monkeypatch, candidate_kernel
):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    owner = host.manager()
    assert type(owner) is DarwinProcessManager
    assert host.manager() is owner
    identity = str(uuid4())
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        started = owner.start(
            run_id=identity,
            argv=[sys.executable, "-c", "import time;time.sleep(30)"],
            cwd=tmp_path,
            executor="platform-fixture",
        )
        host.reset_manager()
        recovered = host.manager()
        assert recovered is not owner and type(recovered) is DarwinProcessManager
        observed = client.get("/v1/process/" + identity)
        assert observed.status_code == 200
        assert observed.json()["pid"] == started["pid"] and observed.json()["alive"]
        assert observed.json()["native_identity"]["uid"] == os.geteuid()
        missing = str(uuid4())
        assert client.get("/v1/process/" + missing).status_code == 404
        assert client.post("/v1/process/cancel", json={"run_id": missing}).status_code == 404
        canceled = client.post("/v1/process/cancel", json={"run_id": identity})
        assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
        assert not canceled.json()["alive"] and unrelated.poll() is None
        assert client.get("/v1/process/" + identity).json()["status"] == "canceled"
    finally:
        owner.shutdown()
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_mac_health_and_readonly_hardware_do_not_construct_process_storage(client, tmp_path, monkeypatch):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(host, "collect", lambda root: {"fixture_root_matches": root == tmp_path})
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/v1/hardware").json() == {"fixture_root_matches": True}
    assert host._manager is None and not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_mac_generic_process_routes_cannot_delegate_a_linux_image_container(client, monkeypatch, method):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(host, "sys", SimpleNamespace(platform="darwin"))

    def forbidden(_):
        raise AssertionError("Mac inspection reached a Linux image adapter")

    monkeypatch.setattr(host.managed_image_job, "owns", forbidden)
    monkeypatch.setattr(
        host,
        "manager",
        lambda: SimpleNamespace(
            inspect=lambda *a, **k: {"status": "canceled"}, cancel=lambda *a, **k: {"status": "canceled"}
        ),
    )
    identity = str(uuid4())
    response = (
        client.get("/v1/process/" + identity)
        if method == "GET"
        else client.post("/v1/process/cancel", json={"run_id": identity})
    )
    assert response.status_code == 200 and response.json()["status"] == "canceled"


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("error", [OSError, ValueError])
def test_native_identity_uncertainty_requires_inspection_without_exposing_private_errors(
    client, monkeypatch, method, error
):
    monkeypatch.setattr(native, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(host.managed_image_job, "owns", lambda _: False)

    def uncertain(*args, **kwargs):
        raise error("PRIVATE_NATIVE_IDENTITY_PATH")

    monkeypatch.setattr(host, "manager", lambda: SimpleNamespace(inspect=uncertain, cancel=uncertain))
    identity = str(uuid4())
    response = (
        client.get("/v1/process/" + identity)
        if method == "GET"
        else client.post("/v1/process/cancel", json={"run_id": identity})
    )
    assert response.status_code == 409 and "inspection" in response.json()["detail"]
    assert "PRIVATE_NATIVE_IDENTITY_PATH" not in response.text


@pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"}
    or (sys.platform == "darwin" and os.getenv("AI_STATION_REAL_MAC_PROCESS_TESTS") != "1"),
    reason="Actual Mac Runner execution requires explicit native qualification",
)
def test_actual_runner_main_private_socket_recovers_and_stops_native_owned_work():
    # macOS pytest/temp roots may exceed sockaddr_un. Production will supply its
    # own short private runtime root; this experiment never uses a /proc alias.
    with tempfile.TemporaryDirectory(
        prefix="ais-run-", dir="/private/tmp" if sys.platform == "darwin" else None
    ) as temporary:
        root = Path(temporary).resolve()
        data = root / "data"
        socket = root / "uds/runner.sock"
        package = Path(__file__).resolve().parents[1]
        bootstrap = (
            f"import sys;sys.path.insert(0,{str(package)!r});from ai_station_runner.main import main;main()"
        )
        argv = [sys.executable, "-IB", "-c", bootstrap]
        env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "AI_STATION_DATA_HOST_PATH": str(data),
            "AI_STATION_RUNNER_SOCKET": str(socket),
        }
        owner = native.create_process_manager(data, grace_seconds=0.05)
        identity = str(uuid4())
        unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
        server = None
        try:
            started = owner.start(
                run_id=identity,
                argv=[sys.executable, "-IB", "-c", "import time;time.sleep(60)"],
                cwd=root,
                executor="platform-fixture",
            )
            server = subprocess.Popen(
                argv, cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            deadline = time.monotonic() + 20
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(socket)),
                base_url="http://runner",
                timeout=5,
                trust_env=False,
            ) as client:
                while True:
                    assert server.poll() is None, "Normal Runner exited before readiness"
                    try:
                        ready = client.get("/health")
                        if ready.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, "Normal Runner readiness timed out"
                    time.sleep(0.05)
                assert ready.json()["data_dir"] == str(data)
                assert stat.S_IMODE(socket.stat().st_mode) == 0o600
                assert stat.S_IMODE(socket.parent.stat().st_mode) == 0o700
                duplicate = subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=20)
                assert duplicate.returncode != 0
                assert b"already owns" in duplicate.stderr
                found = client.get("/v1/process/" + identity)
                assert found.status_code == 200 and found.json()["pid"] == started["pid"]
                assert found.json()["alive"]
                assert client.post("/v1/process/cancel", json={"run_id": str(uuid4())}).status_code == 404
                stopped = client.post("/v1/process/cancel", json={"run_id": identity})
                assert stopped.status_code == 200 and not stopped.json()["alive"]
                assert stopped.json()["status"] == "canceled" and unrelated.poll() is None
                if sys.platform == "darwin":
                    assert client.post("/v1/llama/load", json={}).status_code == 503
                assert client.get("/health").status_code == 200
            server.terminate()
            assert server.wait(timeout=15) == 0
            assert not socket.exists()
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                server.wait(timeout=15)
            owner.shutdown()
            unrelated.terminate()
            unrelated.wait(timeout=5)
