"""Real owned fixture process: lose the observer, collect without another launch."""

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run
from app.resources import active_locks
from app.runner_client import RunnerClient, RunnerUnavailable
from fastapi.testclient import TestClient
from test_images import bridge as image_bridge  # noqa: F401
from test_video import bridge as video_bridge  # noqa: F401


@pytest.mark.parametrize(
    "fixture,endpoint,body",
    [
        ("image_bridge", "/api/images/runs", {"mode": "t2i", "prompt": "neutral test"}),
        ("video_bridge", "/api/video/runs", {"prompt": "neutral test"}),
    ],
)
def test_lost_media_observer_collects_one_native_launch(request, monkeypatch, fixture, endpoint, body):
    request.getfixturevalue(fixture)
    original_inspect = RunnerClient.inspect_process
    original_request = RunnerClient.request
    lost = False
    launches = []

    def inspect(self, run_id, **kwargs):
        nonlocal lost
        info = original_inspect(self, run_id, **kwargs)
        if kwargs and not lost:
            lost = True
            raise RunnerUnavailable("Synthetic lost media observer")
        return info

    def native_request(self, method, path, json=None):
        if method == "POST" and path in {"/v1/runs/photo", "/v1/runs/video"}:
            launches.append(path)
        return original_request(self, method, path, json)

    monkeypatch.setattr(RunnerClient, "inspect_process", inspect)
    monkeypatch.setattr(RunnerClient, "request", native_request)
    with TestClient(app) as api:
        response = api.post(endpoint, json=body)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session_factory()() as session:
            tick(session, "lost-worker")
            session.refresh(session.get(Run, run_id))
            assert session.get(Run, run_id).status == "running"
            assert active_locks(session) == {"gpu:7"}
            session.commit()
            tick(session, "replacement-worker")
            session.refresh(session.get(Run, run_id))
            assert session.get(Run, run_id).status == "succeeded"
            assert not active_locks(session)
        assert lost and len(launches) == 1
        artifacts = api.get("/api/artifacts", params={"run_id": run_id}).json()
        assert len(artifacts) == 1
        assert api.get(f"/api/artifacts/{artifacts[0]['id']}/file").status_code == 200
