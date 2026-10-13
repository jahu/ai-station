import io
import sys
import threading
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner import video as host_video
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.recovery import recover_stale
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.write_text(f"""#!{sys.executable}
import json, os, pathlib, sys, time
config=json.loads(pathlib.Path(sys.argv[-1]).read_text())
assert os.environ['HF_HUB_OFFLINE']=='1'
assert os.environ['CUDA_VISIBLE_DEVICES']=='7'
assert 'AI_STATION_LLM_API_KEY' not in os.environ
assert os.environ['TORCH_HOME'].startswith(config['work'])
if config['request']['prompt']=='wait':time.sleep(60)
if config['request']['prompt']=='fail':sys.exit(3)
pathlib.Path(config['output']).write_bytes(b'fake-video')
print('video completed',flush=True)
""")
    python.chmod(0o700)
    (tmp_path / "nodes.py").touch()
    for key in ("model", "text", "vae"):
        (tmp_path / f"{key}.safetensors").touch()
    for key, value in {
        "VIDEO_PYTHON": python,
        "COMFY_DIR": tmp_path,
        "WAN_MODEL": tmp_path / "model.safetensors",
        "WAN_TEXT_ENCODER": tmp_path / "text.safetensors",
        "WAN_VAE": tmp_path / "vae.safetensors",
    }.items():
        monkeypatch.setenv("AI_STATION_" + key, str(value))
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "must-not-leak")
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    host_app.reset_manager()

    def hardware(_):
        return {"gpus": [{"index": 7}]}

    monkeypatch.setattr(host_app, "collect", hardware)
    monkeypatch.setattr(host_video, "collect", hardware)
    with TestClient(host_app.app) as host:

        def request(self, method, path, json=None):
            r = host.request(method, path, json=json)
            if r.status_code >= 400:
                raise RunnerError(r.status_code, r.text)
            return r.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield host
    host_app.manager().shutdown()
    host_app.reset_manager()
    clear_settings_cache()


def image(api):
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(data, "PNG")
    r = api.post("/api/images/uploads", files={"file": ("source.png", data.getvalue(), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


def test_text_and_image_video_lifecycle_artifacts_restart(bridge):
    api = TestClient(app)
    source = image(api)
    for source_id in (None, source["id"]):
        r = api.post("/api/video/runs", json={"prompt": "A tree in the wind", "image_artifact_id": source_id})
        assert r.status_code == 202, r.text
        run = r.json()
        assert run["status"] == "queued" and run["retry_class"] == "inspect"
        with session_factory()() as s:
            tick(s, "video-test")
            assert s.get(Run, run["id"]).status == "succeeded"
            assert not active_locks(s)
        artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a["type"] == "video" and a["parent_artifact_ids"] == ([source_id] if source_id else [])
        assert api.get("/api/artifacts/" + a["id"] + "/file").content == b"fake-video"
        assert "stdout" in api.get("/api/runs/" + run["id"] + "/stream").text
        from app.db import reset_engine

        reset_engine()
        assert api.get("/api/runs/" + run["id"]).json()["status"] == "succeeded"


@pytest.mark.parametrize(
    "payload",
    [
        {"frames": 48},
        {"width": 513},
        {"width": 1280, "height": 1280},
        {"steps": 41},
        {"cfg": 11},
        {"seed": -1},
        {"graph": {}},
        {"image_artifact_id": str(uuid4())},
    ],
)
def test_video_rejects_invalid_requests_without_launching(bridge, payload):
    api = TestClient(app)
    assert api.post("/api/video/runs", json={"prompt": "Scene", **payload}).status_code == 422
    with session_factory()() as s:
        assert not list(s.scalars(select(Run)))


def test_unavailable_profile_is_honest(monkeypatch):
    monkeypatch.setattr(
        RunnerClient, "request", lambda *a, **k: {"available": False, "reason": "Missing setup"}
    )
    api = TestClient(app)
    assert not api.get("/api/video/capabilities").json()["available"]
    assert api.post("/api/video/runs", json={"prompt": "Scene"}).status_code == 409


def test_native_permissions_paths_and_fixed_argv(bridge):
    run_id = str(uuid4())
    base = {
        "run_id": run_id,
        "prompt": "Scene",
        "gpu": 7,
        "permissions": ["filesystem_read", "workspace_write"],
    }
    assert bridge.post("/v1/runs/video", json={**base, "permissions": []}).status_code == 403
    assert (
        bridge.post("/v1/runs/video", json={**base, "image_relative": "../../secret.png"}).status_code == 403
    )
    assert bridge.post("/v1/runs/video", json={**base, "gpu": 8}).status_code == 422
    assert bridge.post("/v1/runs/video", json={**base, "command": "whatever"}).status_code == 422
    assert bridge.post("/v1/runs/video", json=base).status_code == 200
    assert bridge.post("/v1/runs/video", json=base).status_code == 409
    assert bridge.get("/v1/process/" + run_id).json()["executor"] == "wan_video"


def test_cancellation_and_stale_lease_never_replay(bridge):
    api = TestClient(app)
    r = api.post("/api/video/runs", json={"prompt": "wait"})
    run_id = r.json()["id"]
    failures = []

    def work():
        try:
            with session_factory()() as s:
                tick(s, "video-cancel")
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=work)
    worker.start()
    try:
        for _ in range(100):
            if api.get("/api/runs/" + run_id).json()["status"] == "running":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("Video did not start")
        assert api.post("/api/runs/" + run_id + "/cancel").status_code == 200
        worker.join(10)
        assert not worker.is_alive() and not failures
        assert api.get("/api/runs/" + run_id).json()["status"] == "canceled"
        assert api.get("/api/artifacts?run_id=" + run_id).json() == []
        with session_factory()() as s:
            assert not active_locks(s)
        r = api.post("/api/video/runs", json={"prompt": "Scene"}).json()
        with session_factory()() as s:
            row = s.get(Run, r["id"])
            row.status = "running"
            row.worker_id = "gone"
            row.lease_expires_at = utcnow() - timedelta(seconds=1)
            row.metadata_json = {"dispatch_attempted": True}
            s.commit()
            recover_stale(s)
            s.commit()
            assert s.get(Run, row.id).status == "interrupted"
    finally:
        if worker.is_alive():
            bridge.post("/v1/process/cancel", json={"run_id": run_id})
            worker.join(10)


def test_failed_job_has_no_successful_artifact(bridge):
    api = TestClient(app)
    r = api.post("/api/video/runs", json={"prompt": "fail"}).json()
    with session_factory()() as s:
        tick(s, "video-failure")
        assert s.get(Run, r["id"]).status == "failed"
        assert not active_locks(s)
    assert api.get("/api/artifacts?run_id=" + r["id"]).json() == []


@pytest.mark.parametrize("action,with_image", [("video.generate", False), ("auto", True)])
def test_assistant_dispatches_video_and_returns_source_linked_output(bridge, action, with_image):
    api = TestClient(app)
    cid = api.post(
        "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
    ).json()["id"]
    source = image(api)["id"] if with_image else None
    r = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Wygeneruj wideo lasu we mgle",
            "action": action,
            "image_artifact_ids": [source] if source else [],
        },
    )
    assert r.status_code == 202, r.text
    with session_factory()() as s:
        tick(s, "video-assistant")
        tick(s, "video-child")
    detail = api.get(f"/api/chat/conversations/{cid}").json()
    child = next(step for step in detail["messages"][-1]["steps"] if step["capability"] == "video.generate")
    assert child["status"] == "succeeded"
    with session_factory()() as s:
        run = s.get(Run, child["id"])
        assert run.parent_run_id == r.json()["id"]
        assert run.parameters["parent_artifact_ids"] == ([source] if source else [])


def test_configured_hf_symlink_pins_canonical_file(bridge, monkeypatch, tmp_path):
    blob = tmp_path / "hash-without-extension"
    blob.write_bytes(b"configured-weights")
    link = tmp_path / "encoder.safetensors"
    link.symlink_to(blob)
    monkeypatch.setenv("AI_STATION_WAN_TEXT_ENCODER", str(link))
    clear_settings_cache()
    assert host_video.profile()["wan_text_encoder"] == blob.resolve()


def test_native_rejects_owned_input_symlink_escape(bridge, monkeypatch, tmp_path):
    from ai_station_runner.config import get_settings

    root = get_settings().host_data_dir().resolve()
    (root / "artifacts").mkdir(exist_ok=True)
    outside = tmp_path / "private.png"
    Image.new("RGB", (64, 64)).save(outside)
    (root / "artifacts/escaped.png").symlink_to(outside)
    response = bridge.post(
        "/v1/runs/video",
        json={
            "run_id": str(uuid4()),
            "prompt": "Scene",
            "gpu": 7,
            "permissions": ["filesystem_read", "workspace_write"],
            "image_relative": "artifacts/escaped.png",
        },
    )
    assert response.status_code == 403, response.text


def test_missing_runner_reports_unavailable_without_server_error():
    api = TestClient(app)
    response = api.get("/api/video/capabilities")
    assert response.status_code == 200 and not response.json()["available"]
    assert api.post("/api/video/runs", json={"prompt": "Scene"}).status_code == 409


def test_assistant_unavailable_video_clarifies_without_child(monkeypatch):
    monkeypatch.setattr(RunnerClient, "request", lambda *a, **k: {"available": False})
    api = TestClient(app)
    cid = api.post(
        "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
    ).json()["id"]
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Generate a video of a forest", "action": "video.generate"},
    )
    assert response.status_code == 202
    with session_factory()() as s:
        tick(s, "unavailable-video")
        assert len(list(s.scalars(select(Run)))) == 1
        parent = s.get(Run, response.json()["id"])
        assert parent.status == "succeeded" and parent.metadata_json["plan"]["action"] == "clarify"
    assert "needs setup" in api.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]["content"]
