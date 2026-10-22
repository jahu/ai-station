"""Opt-in CPU-only API -> durable worker -> private native socket -> Chromium."""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_BROWSER_TESTS") != "1", reason="Opt-in actual offline preview worker/container"
)


def test_real_preview_worker_socket_interaction_and_close(session, monkeypatch, tmp_path):
    from app.api import app
    from app.config import clear_settings_cache, get_settings
    from app.db import session_factory
    from app.engine import tick
    from app.models import Artifact, ResourceLock, Run
    from app.runner_client import RunnerClient
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from test_site_preview_provenance import built

    data_dir = get_settings().data_dir
    monkeypatch.setenv("AI_STATION_SITE_PREVIEW_ENABLED", "true")
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(data_dir))
    monkeypatch.setenv(
        "AI_STATION_SITE_PREVIEW_IMAGE",
        os.getenv("AI_STATION_PREVIEW_TEST_IMAGE", "ai-station-site-preview:development"),
    )
    monkeypatch.setenv("AI_STATION_CANCEL_GRACE_SECONDS", "0.2")
    result = {}
    worker_errors = []
    parent_id = None
    worker = None
    with tempfile.TemporaryDirectory(prefix="ais-preview-") as runtime:
        socket = Path(runtime) / "runner.sock"
        monkeypatch.setenv("AI_STATION_RUNNER_SOCKET", str(socket))
        clear_settings_cache()
        with (tmp_path / "native.log").open("wb") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "ai_station_runner.app:app",
                    "--uds",
                    str(socket),
                    "--log-level",
                    "warning",
                ],
                cwd=runtime,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "host-runner")},
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 20
                while not socket.exists():
                    assert child.poll() is None, (tmp_path / "native.log").read_text()
                    assert time.monotonic() < deadline, "Native socket did not start"
                    time.sleep(0.05)
                peer = RunnerClient()
                caps = peer.request("GET", "/v1/site-preview/capabilities")
                assert caps["available"] and caps["protocol"] == 2, caps
                source, archive = built(
                    session,
                    {
                        "index.html": "<html><title>Count: 0</title><button style=\"position:absolute;left:20px;top:20px;width:180px;height:60px\" onclick=\"this.textContent='Count: 1';document.title='Count: 1'\">Count: 0</button></html>"
                    },
                )
                source_id, artifact_id = source.id, archive.id
                session.commit()
                with TestClient(app) as client:
                    opened = client.post(
                        "/api/site-previews",
                        json={
                            "client_request_id": str(uuid4()),
                            "source_run_id": source_id,
                            "artifact_id": artifact_id,
                            "maximum_runtime": 45,
                        },
                    )
                    assert opened.status_code == 202, opened.text
                    parent_id = opened.json()["id"]

                    def work():
                        try:
                            with session_factory()() as current:
                                result["worker_run_id"] = tick(current, "real-preview-worker")
                        except BaseException as error:
                            worker_errors.append(error)

                    worker = threading.Thread(target=work)
                    worker.start()
                    deadline = time.monotonic() + 25
                    while True:
                        parent = client.get(f"/api/site-previews/{parent_id}").json()
                        frame = parent.get("metadata", {}).get("frame")
                        if frame:
                            break
                        assert parent["status"] not in {"failed", "interrupted", "canceled"}, parent
                        assert time.monotonic() < deadline, parent
                        time.sleep(0.1)
                    assert frame["title"] == "Count: 0"
                    assert client.get(f"/api/artifacts/{frame['artifact_id']}/file").content.startswith(
                        b"\x89PNG"
                    )
                    action = {
                        "client_request_id": str(uuid4()),
                        "expected_revision": 0,
                        "action": {"kind": "click", "x": 70, "y": 40},
                    }
                    posted = client.post(f"/api/site-previews/{parent_id}/actions", json=action)
                    assert posted.status_code == 202, posted.text
                    action_id = posted.json()["id"]
                    assert tick(session, "real-interaction-worker") == action_id
                    session.expire_all()
                    applied = session.get(Run, action_id)
                    assert applied.status == "succeeded", (applied.error_message, applied.metadata_json)
                    artifact = session.get(Artifact, applied.metadata_json["frame_artifact_id"])
                    assert artifact.parent_artifact_ids == [artifact_id]
                    session.commit()
                    parent = client.get(f"/api/site-previews/{parent_id}").json()
                    assert parent["metadata"]["frame"]["title"] == "Count: 1"
                    assert parent["metadata"]["frame"]["revision"] == 1
                    assert (
                        client.post(f"/api/site-previews/{parent_id}/actions", json=action).json()["id"]
                        == action_id
                    )
                    closed = client.post(
                        f"/api/site-previews/{parent_id}/close", json={"client_request_id": str(uuid4())}
                    )
                    assert closed.status_code == 202, closed.text
                    tick(session, "real-close-worker")
                    worker.join(timeout=25)
                    assert not worker.is_alive() and not worker_errors, worker_errors
                    session.expire_all()
                    assert session.get(Run, closed.json()["id"]).status == "succeeded"
                    parent = session.get(Run, parent_id)
                    assert parent.status == "canceled" and parent.metadata_json["closed_at"]
                    assert not session.scalar(
                        select(ResourceLock).where(
                            ResourceLock.run_id == parent_id, ResourceLock.released_at.is_(None)
                        )
                    )
                    session.commit()
                    assert not peer.inspect_process(parent_id)["alive"]
                    assert result["worker_run_id"] == parent_id
            finally:
                session.rollback()
                if parent_id:
                    try:
                        RunnerClient().request("POST", f"/v1/runs/site-preview/{parent_id}/close", {})
                    except Exception:
                        pass
                if worker:
                    worker.join(timeout=15)
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=15)
