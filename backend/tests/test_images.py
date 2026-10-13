import io
import sys
from pathlib import Path

import pytest
from ai_station_runner import app as runner_module
from ai_station_runner.config import clear_settings_cache as clear_runner
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from fastapi.testclient import TestClient
from PIL import Image


def png():
    output = io.BytesIO()
    Image.new("RGB", (64, 48), "#426c57").save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    script = tmp_path / "fake_photo.py"
    script.write_text("""import os, sys, time
from PIL import Image
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
args = sys.argv
if '--prompt' in args and args[args.index('--prompt')+1] == 'fail':
    print('expected failure', file=sys.stderr)
    sys.exit(3)
print('x' * 300000)
print('diagnostic', file=sys.stderr)
Image.new('RGB', (64,48), '#426c57').save(args[args.index('--out')+1])
""")
    monkeypatch.setenv("AI_STATION_PHOTO_PYTHON", sys.executable)
    monkeypatch.setenv("AI_STATION_PHOTO_SCRIPT", str(script))
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_runner()
    runner_module.reset_manager()
    monkeypatch.setattr(runner_module, "collect", lambda _: {"gpus": [{"index": 7}]})
    with TestClient(runner_module.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        yield host
    runner_module.manager().shutdown()
    runner_module.reset_manager()
    clear_runner()


def upload(client):
    response = client.post("/api/images/uploads", files={"file": ("../source.png", png(), "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "mode,backend,count",
    [
        ("t2i", "qwen", 0),
        ("t2i", "juggernaut", 0),
        ("img2img", "qwen", 1),
        ("recompose", "qwen", 2),
        ("upscale", "qwen", 1),
    ],
)
def test_image_vertical_slice(bridge, mode, backend, count):
    with TestClient(app) as client:
        parents = [upload(client) for _ in range(count)]
        response = client.post(
            "/api/images/runs",
            json={
                "mode": mode,
                "backend": backend,
                "prompt": "a forest",
                "edit_prompt": "change the sky",
                "gpu": "007",
                "input_artifact_ids": [p["id"] for p in parents],
            },
        )
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["requested_gpu"] == "7"
        with session_factory()() as session:
            tick(session, "image-test")
            assert active_locks(session) == set()
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == "succeeded", result
        artifacts = client.get(f"/api/artifacts?run_id={run['id']}").json()
        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert artifact["parent_artifact_ids"] == [p["id"] for p in parents]
        assert artifact["metadata"]["width"] == 64
        assert artifact["metadata"]["prompt"] == "a forest"
        assert client.get(f"/api/artifacts/{artifact['id']}/file").content == png()
        assert (
            client.get(f"/api/artifacts/{artifact['id']}/thumbnail").headers["content-type"] == "image/jpeg"
        )
        events = client.get(f"/api/runs/{run['id']}/events").json()
        assert sum(len(e["payload"]["text"]) for e in events if e["event_type"] == "stdout") == 300001
        assert any(e["event_type"] == "stderr" and "diagnostic" in e["payload"]["text"] for e in events)


def test_lost_dispatch_response_keeps_reservation(bridge, monkeypatch):
    original = RunnerClient.start_photo

    def lost(self, payload):
        original(self, payload)
        raise RunnerUnavailable("response lost")

    monkeypatch.setattr(RunnerClient, "start_photo", lost)
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
            assert session.get(Run, run["id"]).status == "preparing"
            assert active_locks(session) == {"gpu:7"}
        assert client.post(f"/api/images/runs/{run['id']}/retry").status_code == 409


def test_cancellation_during_dispatch(bridge, monkeypatch):
    original = RunnerClient.start_photo

    def cancel_during_send(self, payload):
        with TestClient(app) as client:
            assert client.post(f"/api/runs/{payload['run_id']}/cancel").status_code == 200
        return original(self, payload)

    monkeypatch.setattr(RunnerClient, "start_photo", cancel_during_send)
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
            assert active_locks(session) == set()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert client.get(f"/api/artifacts?run_id={run['id']}").json() == []


def test_failed_image_retry_keeps_task_and_lineage(bridge):
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "fail"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        retry = client.post(f"/api/images/runs/{run['id']}/retry")
        assert retry.status_code == 202, retry.text
        assert retry.json()["task_id"] == run["task_id"]
        assert retry.json()["parent_run_id"] == run["id"]
        assert client.post(f"/api/images/runs/{run['id']}/retry").status_code == 409


def test_image_validation_and_storage_boundaries(bridge):
    with TestClient(app) as client:
        assert client.post("/api/images/uploads", files={"file": ("x.png", b"not image")}).status_code == 422
        source = upload(client)
        assert source["original_filename"] == "source.png"
        for payload in [
            {"mode": "t2i"},
            {"mode": "img2img", "edit_prompt": "x"},
            {"mode": "t2i", "prompt": "x", "width": 65536},
            {"mode": "t2i", "prompt": "x", "seed": 1},
            {"mode": "recompose", "prompt": "x"},
            {"mode": "t2i", "prompt": "x", "gpu": "cpu"},
            {"mode": "upscale", "input_artifact_ids": ["../../etc/passwd"]},
        ]:
            assert client.post("/api/images/runs", json=payload).status_code == 422
        path = get_settings().data_dir / source["relative_path"]
        path.unlink()
        path.symlink_to(Path("/etc/passwd"))
        assert client.get(f"/api/artifacts/{source['id']}/file").status_code == 404


def test_poll_failure_keeps_gpu_until_recovery(bridge, monkeypatch):
    def missing(self, run_id, **offsets):
        raise RunnerUnavailable("runner disconnected")

    monkeypatch.setattr(RunnerClient, "inspect_process", missing)
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
            assert session.get(Run, run["id"]).status == "running"
            assert active_locks(session) == {"gpu:7"}


def test_unknown_exit_never_succeeds(bridge, monkeypatch):
    original = RunnerClient.inspect_process

    def unknown(self, run_id, **offsets):
        info = original(self, run_id, **offsets)
        if not info["alive"]:
            info.update(status="interrupted", exit_code=None)
        return info

    monkeypatch.setattr(RunnerClient, "inspect_process", unknown)
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
            assert session.get(Run, run["id"]).status == "interrupted"
            assert active_locks(session) == set()
        assert client.get(f"/api/artifacts?run_id={run['id']}").json() == []


def test_missing_permission_never_dispatches(bridge):
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            session.get(Run, run["id"]).effective_permissions = []
            session.commit()
            tick(session, "image-test")
            assert session.get(Run, run["id"]).error_type == "PermissionDenied"
        assert bridge.get(f"/v1/process/{run['id']}").status_code == 404


def test_truncated_jpeg_is_rejected_before_storage():
    data = io.BytesIO()
    Image.new("RGB", (100, 100)).save(data, "JPEG")
    with TestClient(app) as client:
        response = client.post("/api/images/uploads", files={"file": ("broken.jpg", data.getvalue()[:-20])})
        assert response.status_code == 422
        assert client.get("/api/artifacts").json() == []


def test_file_delivery_releases_database_transaction(session):
    from uuid import UUID

    from app.images import artifact_file, artifact_thumbnail

    with TestClient(app) as client:
        source = upload(client)
    for response in (artifact_file, artifact_thumbnail):
        assert response(UUID(source["id"]), session).status_code == 200
        assert not session.in_transaction()


def test_image_waits_for_reaping_before_adopting_output(bridge, monkeypatch):
    original = RunnerClient.inspect_process
    pending_seen = []

    def inspect(self, run_id, **offsets):
        info = original(self, run_id, **offsets)
        if not info["alive"] and not pending_seen:
            pending_seen.append(True)
            info.update(completion_pending=True, status="running", exit_code=None)
        return info

    monkeypatch.setattr(RunnerClient, "inspect_process", inspect)
    with TestClient(app) as client:
        run = client.post("/api/images/runs", json={"mode": "t2i", "prompt": "forest"}).json()
        with session_factory()() as session:
            tick(session, "image-test")
            assert session.get(Run, run["id"]).status == "succeeded"
        assert pending_seen
        assert len(client.get(f"/api/artifacts?run_id={run['id']}").json()) == 1


def test_photo_worker_unloads_idle_model_before_dispatch(bridge, monkeypatch):
    from app.models import ResourceLock, RuntimeInstance
    from app.runs import create_run, create_task

    with session_factory()() as session:
        task = create_task(session, title="model", prompt="", capability="runtime.load")
        load = create_run(
            session, task, run_type="runtime", capability="runtime.load", executor_type="llama_load"
        )
        load.status = "succeeded"
        instance = RuntimeInstance(
            runtime_key="llama.cpp",
            name="model",
            ownership="managed",
            status="ready",
            metadata_json={"gpus": [7], "load_run_id": load.id},
        )
        session.add(instance)
        session.flush()
        instance.endpoint = "llamacpp:" + instance.id
        session.add(ResourceLock(resource_key="gpu:7", run_id=load.id))
        session.commit()
    stopped = []

    def stop(_, instance_id):
        stopped.append(instance_id)
        return {"status": "stopped", "alive": False}

    monkeypatch.setattr(RunnerClient, "stop_llama", stop)
    with TestClient(app) as client:
        image = client.post(
            "/api/images/runs", json={"mode": "t2i", "backend": "qwen", "prompt": "forest", "gpu": "auto"}
        ).json()
        with session_factory()() as session:
            assert tick(session, "image-test") == image["id"]
            assert session.get(Run, image["id"]).status == "queued"
            assert active_locks(session) == {"gpu:7"}
            stop_id = tick(session, "image-test")
            assert session.get(Run, stop_id).executor_type == "llama_stop"
            assert stopped == [instance.id]
            assert tick(session, "image-test") == image["id"]
            assert session.get(Run, image["id"]).status == "succeeded"
            assert not active_locks(session)
        assert len(client.get(f"/api/artifacts?run_id={image['id']}").json()) == 1


def test_generate_upscale_workflow_survives_restart_and_reuses_output(bridge):
    from app.db import reset_engine

    with TestClient(app) as client:
        first = client.post(
            "/api/images/runs", json={"mode": "t2i", "prompt": "forest", "gpu": "7", "upscale_result": True}
        ).json()
        assert client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"][0]["status"] == "queued"
        with session_factory()() as session:
            assert tick(session, "image-test") == first["id"]
            assert not active_locks(session)
        chain = client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"]
        assert [r["status"] for r in chain] == ["succeeded", "queued"]
        child = chain[1]
        source = client.get(f"/api/artifacts?run_id={first['id']}").json()[0]
        assert child["parameters"]["parent_artifact_ids"] == [source["id"]]
        assert child["parameters"]["inputs"] == [source["relative_path"]]
        assert child["parameters"]["upscale_result"] is False
        assert child["parent_run_id"] == first["id"]
        assert child["task_id"] == first["task_id"]
        assert child["requested_gpu"] == first["requested_gpu"]
        assert child["effective_permissions"] == first["effective_permissions"]
        reset_engine()
        with session_factory()() as session:
            assert tick(session, "restarted-image-worker") == child["id"]
            assert tick(session, "restarted-image-worker") is None
            assert not active_locks(session)
        assert [
            r["status"] for r in client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"]
        ] == ["succeeded", "succeeded"]
        final = client.get(f"/api/artifacts?run_id={child['id']}").json()[0]
        assert final["parent_artifact_ids"] == [source["id"]]
        assert client.get(f"/api/artifacts/{source['id']}/file").status_code == 200


@pytest.mark.parametrize("failure", ["exit", "cancel", "unknown"])
def test_unsuccessful_generation_never_publishes_upscale(bridge, monkeypatch, failure):
    with TestClient(app) as client:
        body = {"mode": "t2i", "prompt": "fail" if failure == "exit" else "forest", "upscale_result": True}
        first = client.post("/api/images/runs", json=body).json()
        if failure == "cancel":
            client.post(f"/api/runs/{first['id']}/cancel").raise_for_status()
        if failure == "unknown":
            original = RunnerClient.inspect_process

            def unknown(self, run_id, **offsets):
                info = original(self, run_id, **offsets)
                if not info["alive"]:
                    info.update(status="interrupted", exit_code=None)
                return info

            monkeypatch.setattr(RunnerClient, "inspect_process", unknown)
        with session_factory()() as session:
            tick(session, "image-test")
            assert not active_locks(session)
        chain = client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"]
        assert len(chain) == 1
        assert chain[0]["status"] in {"failed", "canceled", "interrupted"}


def test_cancel_upscale_preserves_source_and_retry_only_enlarges(bridge):
    with TestClient(app) as client:
        first = client.post(
            "/api/images/runs", json={"mode": "t2i", "prompt": "forest", "upscale_result": True}
        ).json()
        with session_factory()() as session:
            tick(session, "image-test")
        second = client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"][1]
        client.post(f"/api/runs/{second['id']}/cancel").raise_for_status()
        retry = client.post(f"/api/images/runs/{second['id']}/retry")
        assert retry.status_code == 202, retry.text
        assert retry.json()["parameters"]["mode"] == "upscale"
        with session_factory()() as session:
            assert tick(session, "image-test") == retry.json()["id"]
        chain = client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"]
        assert [r["status"] for r in chain] == ["succeeded", "canceled", "succeeded"]
        assert len(client.get(f"/api/artifacts?run_id={first['id']}").json()) == 1


def test_rejected_followup_rolls_back_artifact_and_queued_child(bridge, monkeypatch):
    import app.images as module
    from app.images import create_image_run

    def rejected(session, body, **kwargs):
        create_image_run(session, body, **kwargs)
        raise ValueError("simulated transaction failure after child creation")

    with TestClient(app) as client:
        first = client.post(
            "/api/images/runs", json={"mode": "t2i", "prompt": "forest", "upscale_result": True}
        ).json()
        monkeypatch.setattr(module, "create_image_run", rejected)
        with session_factory()() as session:
            tick(session, "image-test")
        chain = client.get(f"/api/images/runs/{first['id']}/workflow").json()["steps"]
        assert len(chain) == 1 and chain[0]["status"] == "failed"
        assert client.get("/api/artifacts").json() == []
        with session_factory()() as session:
            assert tick(session, "image-test") is None


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "t2i", "prompt": "x", "upscale_result": "true"},
        {"mode": "img2img", "edit_prompt": "x", "max_side": 4096, "upscale_result": True},
        {"mode": "upscale", "upscale_result": True},
    ],
)
def test_image_workflow_rejects_invalid_or_unbounded_followup(body):
    with TestClient(app) as client:
        if body["mode"] == "img2img":
            body = {**body, "input_artifact_ids": [upload(client)["id"]]}
        assert client.post("/api/images/runs", json=body).status_code == 422
        assert client.get("/api/runs").json() == []


def test_assistant_projects_all_image_stages_and_successful_upscale_retry(bridge):
    with TestClient(app) as client:
        conversation = client.post(
            "/api/chat/conversations", json={"model": "test", "execution_mode": "orchestrator"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        orchestration = client.post(
            route + "/messages", json={"content": "Generate an image of a forest, then upscale it."}
        ).json()
        with session_factory()() as session:
            assert tick(session, "image-test") == orchestration["id"]
            first_id = tick(session, "image-test")
        detail = client.get(route).json()
        second = detail["active_run"]
        assert second["capability"] == "image.upscale"
        client.post(f"/api/runs/{second['id']}/cancel").raise_for_status()
        retry = client.post(f"/api/images/runs/{second['id']}/retry").json()
        with session_factory()() as session:
            assert tick(session, "image-test") == retry["id"]
        detail = client.get(route).json()
        assert detail["active_run"] is None
        assert detail["messages"][-1]["task_status"] == "succeeded"
        assert [a["run_id"] for a in detail["messages"][-1]["artifacts"]] == [first_id, retry["id"]]
