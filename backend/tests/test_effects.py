"""Actual typed API/native journal with synthetic inference and codec subprocesses."""

import json
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import app as native
from ai_station_runner import effects_runtime
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerError
from app.runs import create_run, create_task, request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient


@pytest.fixture
def sound_bridge(tmp_path, monkeypatch):
    for key, value in {
        "AI_STATION_MMAUDIO_ENABLED": "true",
        "AI_STATION_MMAUDIO_PYTHON": sys.executable,
        "AI_STATION_MMAUDIO_DIR": str(tmp_path / "source"),
        "AI_STATION_MMAUDIO_MODELS": str(tmp_path / "models"),
    }.items():
        monkeypatch.setenv(key, value)
    for p in (tmp_path / "source", tmp_path / "models"):
        p.mkdir()
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    clear_settings_cache()
    native.reset_manager()
    effects_runtime._checks.clear()
    monkeypatch.setattr(effects_runtime, "scope_available", lambda: True)
    monkeypatch.setattr(effects_runtime, "installation_signature", lambda *args: ("synthetic",))
    monkeypatch.setattr(effects_runtime, "installation_observation", lambda *args: "a" * 64)
    monkeypatch.setattr(effects_runtime, "scope_prefix", lambda rid, ram: ["/test-scope", str(ram)])
    hw = {
        "gpus": [{"index": 7, "memory_total_mib": 12288, "memory_used_mib": 100}],
        "memory": {"total_mib": 32768, "available_mib": 30000},
    }
    monkeypatch.setattr(native, "collect", lambda _: hw)
    monkeypatch.setattr(effects_runtime, "collect", lambda _: hw)
    manager = native.manager()
    start = manager.start
    launches = []
    script = tmp_path / "synthetic.py"
    script.write_text("""import sys,json,wave,time
from pathlib import Path
record=json.loads(Path(sys.argv[1]).read_text());root=Path.cwd();request=record['request'];rid=request['run_id']
if 'video' in request:
 assert request['gpu']==7 and request['observation']=='a'*64
 if request['prompt']=='WAIT':time.sleep(30)
 v=request['video'];out=root/'artifacts'/rid[:2]/rid[2:4]/(rid+'.wav');out.parent.mkdir(parents=True,exist_ok=True)
 with wave.open(str(out),'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(44100);f.writeframes(b'\\x01\\x00'*(v['frames']*44100//v['fps']))
 print('effects.window.completed 1/1',flush=True)
else:
 out=Path(record['output']);out.write_bytes(b'synthetic mp4 output')
 out.with_suffix('.json').write_text(json.dumps({'verified':True,'frames':request['target_frames'],'fps':request['fps'],'width':request['width'],'height':request['height'],'duration_seconds':request['target_frames']/request['fps']}))
""")

    def launch(**kwargs):
        assert kwargs["executor"] in ("mmaudio_effects", "effects_preview")
        if kwargs["executor"] == "mmaudio_effects":
            assert kwargs["argv"][:2] == ["/test-scope", "18432"]
        launches.append(kwargs)
        return start(**{**kwargs, "argv": [sys.executable, str(script), kwargs["argv"][-1]]})

    monkeypatch.setattr(manager, "start", launch)
    with TestClient(native.app) as host:

        def request(self, method, path, json=None):
            response = host.request(method, path, json=json)
            if response.status_code >= 400:
                raise RunnerError(response.status_code, response.text)
            return response.json()

        monkeypatch.setattr(RunnerClient, "request", request)
        deadline = time.monotonic() + 3
        while not effects_runtime.capabilities()["available"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        yield {"launches": launches, "host": host, "hardware": hw, "manager": manager}
    manager.shutdown()
    native.reset_manager()
    clear_settings_cache()
    effects_runtime._checks.clear()


def source_video(api):
    from app.artifacts import register_file
    from app.config import get_settings

    # An adopted generated video has server-owned timing. A normal test never
    # downloads models or needs a decoder/GPU; the typed native fixture is above.
    path = get_settings().data_dir / "synthetic.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic source mp4")
    from app.data_access import DataScope, ScopedSession
    from app.db import get_engine

    identity = api.get("/api/auth").json().get("user")
    scoped = (
        ScopedSession(bind=get_engine(), scope=DataScope(user_id=identity["id"]))
        if identity
        else control_session_factory()()
    )
    with scoped as db:
        task = create_task(db, title="Source", prompt="", capability="video.generate")
        run = create_run(db, task, run_type="video", capability="video.generate", executor_type="wan_video")
        for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED):
            transition(db, run, state, event_type="synthetic", payload={})
        a = register_file(
            db,
            source=path,
            artifact_type="video",
            mime_type="video/mp4",
            original_filename="fixture.mp4",
            run_id=run.id,
            metadata={"frames": 33, "fps": 24, "width": 1280, "height": 704},
        )
        db.commit()
        return a.id


def work():
    with control_session_factory()() as db:
        return tick(db, "effects-fixture")


def test_video_effects_and_sound_preview_publish_separate_linked_artifacts(sound_bridge):
    with TestClient(app) as api:
        aid = source_video(api)
        response = api.post(
            "/api/audio/effects/runs", json={"video_artifact_id": aid, "prompt": "Quiet wind", "seed": 42}
        )
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["requested_resources"] == {"ram_mib": 18432}
        assert work() == run["id"]
        result = api.get("/api/runs/" + run["id"]).json()
        assert result["status"] == "succeeded", result
        preview = result["metadata"]["effects_preview_run_id"]
        assert work() == preview
        assert api.get("/api/runs/" + preview).json()["status"] == "succeeded"
        artifacts = api.get("/api/artifacts").json()
        stem = next(a for a in artifacts if a["run_id"] == run["id"])
        film = next(a for a in artifacts if a["run_id"] == preview)
        assert stem["metadata"]["samples"] == 60637 and stem["parent_artifact_ids"] == [aid]
        assert set(film["parent_artifact_ids"]) == {aid, stem["id"]} and film["metadata"]["frames"] == 33
        with control_session_factory()() as db:
            assert not active_locks(db)


def test_changed_video_does_not_reach_native_or_publish_any_sound(sound_bridge):
    from app.config import get_settings

    with TestClient(app) as api:
        aid = source_video(api)
        run = api.post("/api/audio/effects/runs", json={"video_artifact_id": aid, "prompt": "Wind"}).json()
        a = api.get("/api/artifacts/" + aid).json()
        (get_settings().data_dir / a["relative_path"]).write_bytes(b"tampered")
        work()
        assert api.get("/api/runs/" + run["id"]).json()["status"] == "failed"
        assert not sound_bridge["launches"]


def test_effects_wait_for_ram_vram_and_stop_only_the_owned_process(sound_bridge, monkeypatch):
    with TestClient(app) as api:
        aid = source_video(api)
        run = api.post("/api/audio/effects/runs", json={"video_artifact_id": aid, "prompt": "WAIT"}).json()
        sound_bridge["hardware"]["memory"]["available_mib"] = 12000
        work()
        assert not sound_bridge["launches"]
        sound_bridge["hardware"]["memory"]["available_mib"] = 30000
        sound_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 9000
        with control_session_factory()() as db:
            from app.resources import RESOURCE_WAIT_KEY

            task = db.get(Run, run["id"]).task
            task.metadata_json = {k: v for k, v in task.metadata_json.items() if k != RESOURCE_WAIT_KEY}
            db.commit()
        work()
        assert not sound_bridge["launches"]
        sound_bridge["hardware"]["gpus"][0]["memory_used_mib"] = 100
        with control_session_factory()() as db:
            task = db.get(Run, run["id"]).task
            task.metadata_json = {k: v for k, v in task.metadata_json.items() if k != RESOURCE_WAIT_KEY}
            db.commit()
        original = RunnerClient.request

        def request(self, method, path, json=None):
            result = original(self, method, path, json)
            if path == "/v1/runs/effects":
                with control_session_factory()() as db:
                    request_cancel(db, db.get(Run, run["id"]))
                    db.commit()
            return result

        monkeypatch.setattr(RunnerClient, "request", request)
        work()
        assert api.get("/api/runs/" + run["id"]).json()["status"] == "canceled"
        assert not sound_bridge["manager"].inspect(run["id"])["alive"]
        assert api.get("/api/artifacts", params={"run_id": run["id"]}).json() == []


@pytest.mark.parametrize("extra", [{"command": "sh"}, {"steps": 500}, {"gpu": "none"}, {"cfg": float("inf")}])
def test_unbounded_effects_requests_cannot_enqueue(extra):
    with TestClient(app) as api:
        response = api.post(
            "/api/audio/effects/runs",
            content=json.dumps({"video_artifact_id": str(uuid4()), "prompt": "Wind", **extra}),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


def test_lost_acknowledgement_retains_sound_gpu_and_recovers_without_replay(sound_bridge, monkeypatch):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale

    original = RunnerClient.request

    def request(self, method, path, json=None):
        result = original(self, method, path, json)
        if path == "/v1/runs/effects":
            raise RunnerError(503, "Synthetic lost reply")
        return result

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as api:
        source = source_video(api)
        run = api.post("/api/audio/effects/runs", json={"video_artifact_id": source, "prompt": "WAIT"}).json()
        work()
        with control_session_factory()() as db:
            row = db.get(Run, run["id"])
            assert row.status == "preparing"
            row.lease_expires_at = utcnow() - timedelta(seconds=60)
            db.commit()
            recover_stale(db)
            db.commit()
            assert len(active_locks(db)) == 1
            assert len(sound_bridge["launches"]) == 1
            request_cancel(db, row)
            row.lease_expires_at = utcnow() - timedelta(seconds=60)
            db.commit()
        sound_bridge["manager"].cancel(run["id"])
        with control_session_factory()() as db:
            recover_stale(db)
            db.commit()
            assert db.get(Run, run["id"]).status == "canceled" and not active_locks(db)
        assert len(sound_bridge["launches"]) == 1


def test_native_sound_receipt_is_idempotent_and_cannot_extend_one_run_deadline(sound_bridge):
    from app.config import get_settings

    with TestClient(app) as api:
        source = source_video(api)
        run = api.post("/api/audio/effects/runs", json={"video_artifact_id": source, "prompt": "Wind"}).json()
        work()
        receipt = get_settings().data_dir / f"runs/{run['id']}/effects-launch/request.json"
        body = json.loads(receipt.read_text())["request"]
        first = sound_bridge["manager"].inspect(run["id"])
        repeat = sound_bridge["host"].post("/v1/runs/effects", json=body)
        assert repeat.status_code == 200 and repeat.json()["pid"] == first["pid"]
        assert len(sound_bridge["launches"]) == 1
        changed = sound_bridge["host"].post(
            "/v1/runs/effects", json={**body, "deadline_at": body["deadline_at"] + 60}
        )
        assert changed.status_code == 409 and len(sound_bridge["launches"]) == 1


def test_local_enhancement_prepares_effects_prompt_without_changing_video_authority(
    sound_bridge, monkeypatch
):
    from test_media_translation import settings
    from test_prompt_enhancement_workflows import SUFFIX

    async def complete(session, params):
        assert params["location"] == "local" and "tools" not in params
        values = json.loads(params["messages"][-1]["content"])
        yield json.dumps({k: v + SUFFIX if k == "prompt" else v for k, v in values.items()})

    monkeypatch.setattr("app.media_translation.completion_stream", complete)
    with TestClient(app) as api:
        settings(api)
        source = source_video(api)
        run = api.post(
            "/api/audio/effects/runs",
            json={
                "video_artifact_id": source,
                "prompt": "Wind",
                "translation": {"mode": "off", "enhance": True},
            },
        ).json()
        assert run.get("id"), run
        for _ in range(8):
            if work() is None:
                break
        current = api.get("/api/runs/" + run["id"]).json()
        assert current["status"] == "succeeded", current["error_message"]
        assert current["parameters"]["prompt"] == "Wind" + SUFFIX
        assert current["parameters"]["video"] == run["parameters"]["video"]
        assert "mmaudio" in current["metadata"]["prompt_translation"]["policy"]["enhancement_template"]
