import hashlib
import json
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import browser_runs as browser
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from fastapi.testclient import TestClient

IMAGE = "sha256:" + "a" * 64
CID = "b" * 64


@pytest.fixture(autouse=True)
def isolated_browser(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv("AI_STATION_BROWSER_IMAGE", "ai-station-browser:test")
    clear_settings_cache()
    yield
    clear_settings_cache()


def request():
    return browser.BrowserRequest(
        run_id=uuid4(), urls=["https://www.example.com/"], permissions=["browser", "network_read"]
    )


def reserve(body):
    root = browser.directory(str(body.run_id))
    root.mkdir(parents=True)
    saved = {
        "request": body.model_dump(mode="json"),
        "digest": hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
        "image": IMAGE,
    }
    browser.save(root / "request.json", saved)
    return root, saved


def container(saved, index=0):
    name, labels = browser.container_identity(saved, index)
    return {"Id": CID, "Image": IMAGE, "Config": {"Labels": labels}, "Name": name}


def test_native_api_rejects_private_urls_extra_keys_and_missing_permissions(monkeypatch):
    from ai_station_runner.app import app

    api = TestClient(app)
    payload = request().model_dump(mode="json")
    for urls in (
        ["http://127.0.0.1/"],
        ["https://user:secret@example.com/"],
        ["https://example.com:8443/"],
        ["https://example.com/"] * 2,
    ):
        assert api.post("/v1/runs/browser", json={**payload, "urls": urls}).status_code == 422
    assert api.post("/v1/runs/browser", json={**payload, "command": "evil"}).status_code == 422
    assert api.post("/v1/runs/browser", json={**payload, "permissions": ["network_read"]}).status_code == 403


def test_capabilities_require_installed_protocol_and_fixed_entrypoint(monkeypatch):
    image = {
        "Id": IMAGE,
        "Config": {
            "Entrypoint": browser.ENTRYPOINT,
            "User": "1000:1000",
            "Labels": {"ai-station.browser.protocol": "1"},
        },
    }
    monkeypatch.setattr(browser, "docker", lambda *a, **k: json.dumps(image))
    assert browser.capabilities()["available"] is True
    image["Config"]["Entrypoint"] = ["sh"]
    assert browser.capabilities()["available"] is False
    image["Config"]["Entrypoint"] = browser.ENTRYPOINT
    image["Config"]["User"] = "root"
    assert browser.capabilities()["available"] is False


def test_start_is_idempotent_and_never_replays_a_lost_dispatch(monkeypatch):
    body = request()
    calls = []

    class Manager:
        def inspect(self, run_id):
            if not calls:
                raise ProcessNotOwned(run_id)
            return {"executor": "browser", "pid": 12}

        def start(self, **kwargs):
            calls.append(kwargs)
            return {"executor": "browser", "pid": 12}

    monkeypatch.setattr(browser, "capabilities", lambda: {"available": True, "image_id": IMAGE})
    manager = Manager()
    assert browser.start_browser(manager, body)["pid"] == 12
    assert browser.start_browser(manager, body)["pid"] == 12 and len(calls) == 1
    assert calls[0]["argv"][1:3] == ["-m", "ai_station_runner.browser_job"]
    changed = body.model_copy(update={"urls": ["https://other.example/"]})
    with pytest.raises(ValueError, match="another"):
        browser.start_browser(manager, changed)
    calls.clear()
    with pytest.raises(ProcessNotOwned):
        browser.start_browser(manager, body)
    assert not calls


@pytest.mark.parametrize("tamper", ["id", "label", "image"])
def test_cleanup_never_removes_another_container(monkeypatch, tamper):
    body = request()
    root, saved = reserve(body)
    browser.save(root / "container-0.json", {"state": "created", "id": CID})
    item = container(saved)
    if tamper == "id":
        item["Id"] = "c" * 64
    if tamper == "image":
        item["Image"] = "sha256:" + "c" * 64
    if tamper == "label":
        item["Config"]["Labels"]["ai-station.browser.owner"] = str(uuid4())
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return json.dumps(item)

    monkeypatch.setattr(browser, "docker", docker)
    with pytest.raises(ValueError, match="ownership"):
        browser.cancel_browser(str(body.run_id))
    assert all(args[0] != "rm" for args in calls)
    assert (root / "cancel.json").exists()


def test_cleanup_removes_only_confirmed_id_and_survives_restart(monkeypatch):
    body = request()
    root, saved = reserve(body)
    browser.save(root / "container-0.json", {"state": "created", "id": CID})
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return json.dumps(container(saved)) if args[0] == "inspect" else ""

    monkeypatch.setattr(browser, "docker", docker)
    assert browser.cancel_browser(str(body.run_id))
    assert ["rm", "--force", CID] in calls
    calls.clear()
    assert browser.stop_containers(str(body.run_id)) and not calls


def test_lost_container_create_is_unknown_and_never_success(monkeypatch):
    body = request()
    root, _ = reserve(body)
    browser.save(root / "container-0.json", {"state": "creating", "id": None})
    monkeypatch.setattr(browser, "docker", lambda *a, **k: None)
    assert browser.stop_containers(str(body.run_id)) is False
    manager = ProcessManager(root.parent.parent.parent, grace_seconds=0.01)
    manager.start(run_id=str(body.run_id), argv=[sys.executable, "-c", "pass"], cwd=root, executor="browser")
    deadline = time.monotonic() + 5
    while manager.inspect(str(body.run_id))["alive"]:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    inspected = manager.inspect(str(body.run_id))
    assert inspected["status"] == "interrupted" and inspected["cleanup_confirmed"] is False
    with pytest.raises(ValueError, match="confirmed"):
        browser.browser_report(manager, str(body.run_id))


def test_cancel_stops_owned_group_and_container(monkeypatch):
    body = request()
    root, saved = reserve(body)
    browser.save(root / "container-0.json", {"state": "created", "id": CID})
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return json.dumps(container(saved)) if args[0] == "inspect" else ""

    monkeypatch.setattr(browser, "docker", docker)
    manager = ProcessManager(root.parent.parent.parent, grace_seconds=0.01)
    manager.start(
        run_id=str(body.run_id),
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=root,
        executor="browser",
    )
    result = manager.cancel(str(body.run_id))
    assert not result["alive"] and result["status"] == "canceled"
    assert ["rm", "--force", CID] in calls
