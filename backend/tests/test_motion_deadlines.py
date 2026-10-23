"""Native video/avatar/compose budgets; fake workloads, real owned CPU processes."""

import hashlib
import json
import sys
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from ai_station_runner import app as host_app
from ai_station_runner.avatars import AvatarRequest as NativeAvatar
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.media_compose import ComposeRequest
from ai_station_runner.video import VideoRequest as NativeVideo
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from fastapi.testclient import TestClient
from test_avatars import avatar_bridge as avatar_bridge
from test_avatars import inputs
from test_video import bridge as bridge

PERMISSIONS = ["filesystem_read", "workspace_write"]


@pytest.fixture
def compose_bridge(monkeypatch):
    monkeypatch.delenv("AI_STATION_DATA_HOST_PATH", raising=False)
    monkeypatch.setenv("AI_STATION_VIDEO_PYTHON", sys.executable)
    clear_settings_cache()
    host_app.reset_manager()
    manager = host_app.manager()
    original = manager.start

    def sleeping_compose(**kwargs):
        assert kwargs["executor"] == "media_compose"
        kwargs["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        return original(**kwargs)

    monkeypatch.setattr(manager, "start", sleeping_compose)
    with TestClient(host_app.app) as host:
        yield host
    manager.shutdown()
    host_app.reset_manager()
    clear_settings_cache()


def native_case(kind, request):
    base = {"run_id": str(uuid4()), "permissions": PERMISSIONS}
    if kind == "video":
        return request.getfixturevalue("bridge"), {**base, "prompt": "wait", "gpu": 7}
    if kind == "avatar":
        host, _ = request.getfixturevalue("avatar_bridge")
        with TestClient(app) as api:
            portrait, speech = inputs(api)
        return host, {
            **base,
            "prompt": "wait",
            "gpu": 7,
            "image_relative": portrait["relative_path"],
            "audio_relative": speech["relative_path"],
        }
    host = request.getfixturevalue("compose_bridge")
    root = get_settings().data_dir
    path = root / "artifacts/clip.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"owned fixture; never decoded by sleeping fake")
    return host, {
        **base,
        "fps": 24,
        "width": 128,
        "height": 128,
        "target_frames": 17,
        "clips": [
            {
                "relative_path": "artifacts/clip.mp4",
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "expected_frames": 17,
                "frames": 17,
            }
        ],
    }


@pytest.mark.parametrize("kind", ["video", "avatar", "media-compose"])
def test_motion_native_expiry_stops_owned_work_without_any_worker(kind, request):
    host, payload = native_case(kind, request)
    deadline = time.time() + 0.5
    response = host.post("/v1/runs/" + kind, json={**payload, "deadline_at": deadline})
    assert response.status_code == 200, response.text
    until = time.monotonic() + 6
    while True:
        result = host_app.manager().inspect(payload["run_id"])
        if not result["alive"] and not result["completion_pending"]:
            break
        assert time.monotonic() < until, "Native motion job outlived its absolute budget"
        time.sleep(0.02)
    assert result["status"] == "canceled"
    assert result["deadline_at"] == deadline
    assert result["deadline_exceeded_at"] >= deadline


@pytest.mark.parametrize("kind", ["video", "avatar", "media-compose"])
@pytest.mark.parametrize("offset", [-1, 7200])
def test_expired_and_unbounded_native_motion_requests_return_validation_errors(kind, offset, request):
    host, payload = native_case(kind, request)
    response = host.post("/v1/runs/" + kind, json={**payload, "deadline_at": time.time() + offset})
    assert response.status_code == 422, response.text
    assert payload["run_id"] not in json.loads(host_app.manager().path.read_text())


@pytest.mark.parametrize("kind", ["video", "avatar", "media-compose"])
@pytest.mark.parametrize("value", [True, "later", float("nan"), float("inf"), 0, -1])
def test_motion_budget_schema_refuses_nonfinite_or_untyped_values(kind, value, request):
    _, payload = native_case(kind, request)
    schema = {"video": NativeVideo, "avatar": NativeAvatar, "media-compose": ComposeRequest}[kind]
    with pytest.raises(ValueError):
        schema.model_validate({**payload, "deadline_at": value})


def test_video_worker_forwards_exact_absolute_budget_and_confirms_cleanup(bridge):
    with TestClient(app) as api:
        response = api.post("/api/video/runs", json={"prompt": "wait"})
        assert response.status_code == 202
        with session_factory()() as session:
            run = session.get(Run, response.json()["id"])
            deadline = utcnow() + timedelta(seconds=0.6)
            run.parameters = {**run.parameters, "execution_deadline_at": deadline.isoformat()}
            session.commit()
            tick(session, "budgeted-video")
            session.refresh(run)
            native = host_app.manager().inspect(run.id)
            assert run.status == "canceled" and not native["alive"]
            assert native["deadline_at"] == deadline.timestamp()
            assert not active_locks(session)
        assert api.get("/api/artifacts", params={"run_id": run.id}).json() == []


def test_avatar_worker_forwards_exact_absolute_budget_and_confirms_cleanup(avatar_bridge):
    with TestClient(app) as api:
        portrait, speech = inputs(api)
        response = api.post(
            "/api/avatars/runs",
            json={
                "prompt": "wait",
                "image_artifact_id": portrait["id"],
                "audio_artifact_id": speech["id"],
            },
        )
        assert response.status_code == 202
        with session_factory()() as session:
            run = session.get(Run, response.json()["id"])
            deadline = utcnow() + timedelta(seconds=0.6)
            run.parameters = {**run.parameters, "execution_deadline_at": deadline.isoformat()}
            session.commit()
            tick(session, "budgeted-avatar")
            session.refresh(run)
            native = host_app.manager().inspect(run.id)
            assert run.status == "canceled" and not native["alive"]
            assert native["deadline_at"] == deadline.timestamp()
            assert not active_locks(session)
        assert api.get("/api/artifacts", params={"run_id": run.id}).json() == []


@pytest.mark.parametrize("key", ["deadline_at", "execution_deadline_at"])
def test_public_motion_forms_cannot_supply_internal_budgets(key):
    from app.avatars import AvatarRequest
    from app.media_jobs import FullAvatarRequest, LongVideoRequest
    from app.video import VideoRequest

    for schema in (VideoRequest, AvatarRequest, LongVideoRequest, FullAvatarRequest):
        with pytest.raises(ValueError) as error:
            schema.model_validate({key: time.time() + 30})
        assert any(
            item["type"] == "extra_forbidden" and item["loc"] == (key,) for item in error.value.errors()
        )


@pytest.mark.parametrize("budgeted", [True, False])
def test_composition_dispatch_preserves_the_frozen_budget_without_adding_one(budgeted, tmp_path):
    from app.artifacts import register_file
    from app.media_jobs import CompositionExecutor
    from app.media_plan import timeline
    from app.runs import create_run, create_task

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"owned segment fixture; native decode is tested separately")
    deadline = utcnow() + timedelta(seconds=30)
    with session_factory()() as session:
        task = create_task(session, title="Film", prompt="Film", capability="video.long")
        stage = create_run(
            session, task, run_type="video", capability="video.generate", executor_type="wan_video"
        )
        stage.status = "succeeded"
        register_file(
            session,
            source=source,
            artifact_type="video",
            mime_type="video/mp4",
            original_filename="clip.mp4",
            run_id=stage.id,
        )
        run = create_run(
            session,
            task,
            run_type="video",
            capability="media.compose",
            executor_type="media_compose",
            permissions=PERMISSIONS,
            parameters={
                "stage_run_ids": [stage.id],
                "width": 128,
                "height": 128,
                "timeline": timeline(frames=17, fps=24, seed=1).model_dump(mode="json"),
                **({"execution_deadline_at": deadline.isoformat()} if budgeted else {}),
            },
        )
        session.commit()

        class CapturedRunner:
            def request(self, method, path, payload):
                assert (method, path) == ("POST", "/v1/runs/media-compose")
                ComposeRequest.model_validate(payload)
                return payload

        payload = CompositionExecutor()._start(CapturedRunner(), run, None, None)
        if budgeted:
            assert payload["deadline_at"] == deadline.timestamp()
        else:
            assert "deadline_at" not in payload
