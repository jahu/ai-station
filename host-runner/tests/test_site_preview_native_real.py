"""Opt-in actual native API/process/container lifecycle; no GPU or network work."""

import hashlib
import io
import os
import signal
import subprocess
import sys
import time
import zipfile
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_BROWSER_TESTS") != "1", reason="Opt-in native offline preview lifecycle"
)


def test_actual_native_preview_actions_restart_inspection_and_owned_cancellation(tmp_path, monkeypatch):
    from ai_station_runner import site_preview_runs as native
    from ai_station_runner.app import app, manager, reset_manager
    from ai_station_runner.config import Settings, clear_settings_cache
    from ai_station_runner.processes import ProcessManager
    from fastapi.testclient import TestClient

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    monkeypatch.setenv(
        "AI_STATION_SITE_PREVIEW_IMAGE",
        os.getenv("AI_STATION_PREVIEW_TEST_IMAGE", "ai-station-site-preview:development"),
    )
    monkeypatch.setenv("AI_STATION_CANCEL_GRACE_SECONDS", "0.1")
    clear_settings_cache()
    reset_manager()
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "index.html",
            '<html><title>Loading</title><body><button id="counter" style="position:absolute;left:20px;top:20px;width:150px;height:50px">Count</button><button id="stall" style="position:absolute;left:220px;top:20px;width:120px;height:50px">Stall</button><input id="text" style="position:absolute;left:20px;top:90px;width:250px;height:30px"><script type="module" src="/app.js"></script></body></html>',
        )
        archive.writestr(
            "app.js",
            "let n=0;let input=document.getElementById('text');let update=()=>document.title='count='+n+';text='+input.value;document.getElementById('counter').onclick=()=>{n++;update()};document.getElementById('stall').onclick=()=>{while(true){}};input.oninput=update;update();fetch('http://127.0.0.1:8765/').catch(()=>{});",
        )
    blob = data.getvalue()
    aid = str(uuid4())
    clean = aid.replace("-", "")
    source = tmp_path / f"artifacts/{clean[:2]}/{clean[2:4]}/{aid}.zip"
    source.parent.mkdir(parents=True)
    source.write_bytes(blob)
    run_id = str(uuid4())
    body = {
        "run_id": run_id,
        "archive": {"artifact_id": aid, "sha256": hashlib.sha256(blob).hexdigest(), "size_bytes": len(blob)},
        "width": 800,
        "height": 600,
        "maximum_runtime": 60,
        "permissions": sorted(native.PERMISSIONS),
    }
    actions = []
    parents = [run_id]
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(90)"], start_new_session=True)
    client = TestClient(app)

    def wait_frame(revision, target=None):
        target = target or run_id
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            response = client.get(f"/v1/runs/site-preview/{target}/state")
            assert response.status_code == 200, response.text
            result = response.json()
            if result["frame"] and result["frame"]["revision"] >= revision:
                return result["frame"]
            record = manager().inspect(target)
            assert record["alive"] or record.get("completion_pending") or record.get("exit_code") == 0, (
                record.get("stderr_tail")
            )
            time.sleep(0.05)
        raise AssertionError("Preview frame did not arrive")

    def interact(kind, revision, **values):
        action_id = str(uuid4())
        actions.append(action_id)
        payload = {
            "run_id": action_id,
            "preview_run_id": run_id,
            "expected_revision": revision,
            "action": {"kind": kind, **values},
            "permissions": sorted(native.PERMISSIONS),
        }
        response = client.post("/v1/runs/site-preview-action", json=payload)
        assert response.status_code == 200, response.text
        return action_id, payload, response.json()

    def wait_action(action_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = client.get(f"/v1/runs/site-preview-action/{action_id}/report")
            if response.status_code == 200:
                return response.json()
            record = manager().inspect(action_id)
            assert record["alive"] or record.get("completion_pending") or record.get("exit_code") == 0, (
                record.get("stderr_tail")
            )
            time.sleep(0.05)
        raise AssertionError("Preview interaction did not complete")

    try:
        capability = client.get("/v1/site-preview/capabilities").json()
        assert capability["available"] and not capability["network"]
        response = client.post("/v1/runs/site-preview", json=body)
        assert response.status_code == 200, response.text
        parent = response.json()
        initial = wait_frame(0)
        assert initial["title"] == "count=0;text=" and initial["blocked_requests"] >= 1
        # A reconstructed manager reads the exact owned PID identity after a Runner restart.
        reconstructed = ProcessManager(tmp_path, grace_seconds=0.1)
        observed = reconstructed.inspect(run_id)
        assert observed["alive"] and observed["pid"] == parent["pid"]
        action_id, payload, record = interact("click", 0, x=30, y=30)
        clicked = wait_action(action_id)
        assert clicked["state"] == "frame" and clicked["frame"]["title"] == "count=1;text="
        duplicate = client.post("/v1/runs/site-preview-action", json=payload)
        assert duplicate.status_code == 200 and duplicate.json()["pid"] == record["pid"]
        assert client.get(f"/v1/runs/site-preview-action/{action_id}/report").json() == clicked
        stale = {**payload, "run_id": str(uuid4())}
        assert client.post("/v1/runs/site-preview-action", json=stale).status_code == 409
        action_id, _, _ = interact("click", 1, x=30, y=100)
        assert wait_action(action_id)["frame"]["revision"] == 2
        action_id, _, _ = interact("text", 2, text="<script>literal</script>")
        typed = wait_action(action_id)
        assert (
            typed["frame"]["title"] == "count=1;text=<script>literal</script>"
            and typed["frame"]["revision"] == 3
        )
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        assert source_hash == body["archive"]["sha256"]
        # Wedge only the isolated page, then kill only its action proxy. Inspection must
        # close the matching preview container instead of replaying uncertain input.
        action_id, _, record = interact("click", 3, x=230, y=30)
        deadline = time.monotonic() + 10
        while native.action_result(action_id)["state"] != "sent":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        owned = manager().inspect(action_id)
        assert owned["alive"] and owned["pid"] == record["pid"]
        os.killpg(owned["process_group_id"], signal.SIGKILL)
        deadline = time.monotonic() + 15
        while True:
            dead = manager().inspect(action_id)
            if not dead["alive"] and not dead.get("completion_pending"):
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert dead["cleanup_confirmed"] and native.path(run_id, "cancel.json").exists()
        assert unrelated.poll() is None
        assert native.inspect_container(native.load_request(run_id)) is None
        assert (
            native.action_result(action_id)["state"] == "sent"
        )  # Uncertain outcome stays inspectable, never replayed.
        deadline = time.monotonic() + 10
        while manager().inspect(run_id)["alive"]:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert manager().inspect(run_id)["cleanup_confirmed"]
        assert (
            client.post(
                "/v1/runs/site-preview-action",
                json={**payload, "run_id": str(uuid4()), "expected_revision": 3},
            ).status_code
            == 409
        )
        # A new explicit session can start after confirmed cleanup. Inspecting an
        # older uncertain action must never stop that newer owned container.
        next_id = str(uuid4())
        parents.append(next_id)
        opened = client.post("/v1/runs/site-preview", json={**body, "run_id": next_id})
        assert opened.status_code == 200, opened.text
        wait_frame(0, target=next_id)
        assert manager().inspect(action_id)["cleanup_confirmed"]
        assert manager().inspect(next_id)["alive"]
        closed = client.post(f"/v1/runs/site-preview/{next_id}/close")
        assert closed.status_code == 200 and closed.json()["cleanup_confirmed"], closed.text
        assert not manager().inspect(next_id)["alive"] and unrelated.poll() is None
    finally:
        for owned_id in actions + parents:
            try:
                manager().cancel(owned_id)
            except (KeyError, ValueError, OSError, RuntimeError):
                pass
        unrelated.terminate()
        unrelated.wait(timeout=10)
        reset_manager()
        clear_settings_cache()
