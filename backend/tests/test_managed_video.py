"""Managed video admission freezes inputs through short/whole-film jobs and Resume."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app import media_jobs, video
from app.api import app
from app.db import session_factory, utcnow
from app.models import Artifact, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def profile(monkeypatch):
    value = {
        "available": True,
        "configuration_source": "managed",
        "managed_runtime": {
            "profile": "wan22-5b-linux-x86-64-python312-v1",
            "manifest_sha256": "a" * 64,
            "environment_id": "b" * 64,
        },
        "eligible_gpu_indices": [7],
        "profile_observation": {
            key: dict(size_bytes=1, mtime=1.0) for key in ["wan_model", "wan_text_encoder", "wan_vae"]
        },
        "memory_profiles": [dict(id="bounded_11g", available=True, ram_mib=11264)],
        "memory_estimate_mib": 16384,
        "continuation_frames": [1, 17],
        "continuation_guidance": ["standard"],
    }
    monkeypatch.setattr(video, "capabilities", lambda: value)
    monkeypatch.setattr(media_jobs, "capabilities", lambda: value)
    return value


def test_short_run_freezes_actual_profile_inputs_and_absolute_budget(profile):
    api = TestClient(app)
    response = api.post("/api/video/runs", json={"prompt": "Lake at sunrise"})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["parameters"]["managed_runtime"] == profile["managed_runtime"]
    assert run["parameters"]["managed_video_gpu_indices"] == [7]
    assert run["parameters"]["memory_profile"] == "bounded_11g"
    assert run["requested_resources"] == {"ram_mib": 11264}
    assert run["parameters"]["execution_deadline_at"]
    assert (
        api.post(
            "/api/video/runs", json={"prompt": "Lake", "managed_runtime": profile["managed_runtime"]}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("changes", [{"width": 512, "height": 288}, {"steps": 4}, {"gpu": "9"}])
def test_incompatible_settings_are_rejected_before_any_dispatch(profile, changes):
    api = TestClient(app)
    assert api.post("/api/video/runs", json={"prompt": "Scene", **changes}).status_code == 422
    with session_factory()() as session:
        assert not list(session.scalars(select(Run)))


def test_whole_film_preserves_receipt_and_same_runtime_on_each_segment_and_composition(profile):
    api = TestClient(app)
    body = {"client_request_id": str(uuid4()), "prompt": "Quiet forest", "duration_seconds": 5}
    response = api.post("/api/media/jobs/video", json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert api.post("/api/media/jobs/video", json=body).json()["task_id"] == result["task_id"]
    with session_factory()() as session:
        plan = session.get(Task, result["task_id"]).metadata_json["media_plan"]
        assert plan["managed_runtime"] == profile["managed_runtime"]
        assert plan["request"].get("memory_profile", "default") == "default"
        assert len(plan["segment_run_ids"]) > 1
        for identity in [*plan["segment_run_ids"], plan["compose_run_id"]]:
            run = session.get(Run, identity)
            assert run.parameters["managed_runtime"] == profile["managed_runtime"]
            assert run.parameters["execution_deadline_at"] == plan["execution_deadline_at"]
            if run.executor_type == "wan_video":
                assert (
                    run.requested_resources == {"ram_mib": 11264}
                    and run.parameters["memory_profile"] == "bounded_11g"
                )
    assert api.post("/api/media/jobs/" + result["task_id"] + "/cancel", json={}).status_code == 200
    profile["managed_runtime"] = {**profile["managed_runtime"], "environment_id": "c" * 64}
    resumed = api.post(
        "/api/media/jobs/" + result["task_id"] + "/resume",
        json={"client_request_id": str(uuid4()), "expected_revision": 1},
    )
    assert resumed.status_code == 409, resumed.text


def test_managed_native_step_keeps_one_hour_ceiling_within_frozen_whole_film_budget(profile):
    run = SimpleNamespace(
        parameters={
            "managed_runtime": profile["managed_runtime"],
            "execution_deadline_at": (utcnow() + timedelta(hours=72)).isoformat(),
        }
    )
    budget = video.managed_native_budget(run)
    assert (
        (utcnow() + timedelta(minutes=59)).timestamp()
        < budget["deadline_at"]
        <= (utcnow() + timedelta(hours=1)).timestamp()
    )
    earlier = (utcnow() + timedelta(minutes=5)).isoformat()
    run.parameters["execution_deadline_at"] = earlier
    assert video.managed_native_budget(run) == video.HostMediaExecutor.native_budget(run)


def test_composition_dispatch_freezes_same_environment_and_reserves_cpu_ram(profile):
    api = TestClient(app)
    response = api.post(
        "/api/media/jobs/video",
        json={"client_request_id": str(uuid4()), "prompt": "Lake", "duration_seconds": 4},
    )
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        plan = session.get(Task, response.json()["task_id"]).metadata_json["media_plan"]
        for rid in plan["segment_run_ids"]:
            run = session.get(Run, rid)
            run.status = "succeeded"
            session.add(
                Artifact(
                    run_id=rid,
                    artifact_type="video",
                    relative_path=f"artifacts/{rid}.mp4",
                    size_bytes=123,
                    sha256="c" * 64,
                )
            )
        session.commit()
        composition = session.get(Run, plan["compose_run_id"])
        assert composition.requested_resources == {"ram_mib": 4096}
        dispatch = SimpleNamespace(
            id=composition.id,
            parameters=dict(composition.parameters),
            effective_permissions=list(composition.effective_permissions),
        )
    runner = SimpleNamespace(request=lambda method, path, payload: payload)
    payload = media_jobs.CompositionExecutor()._start(runner, dispatch, None, "unused")
    assert payload["managed_runtime"] == profile["managed_runtime"]
    assert len(payload["clips"]) == 2 and payload["deadline_at"]


def test_managed_film_cannot_extend_an_explicit_reviewed_agent_budget(profile):
    deadline = (utcnow() + timedelta(minutes=5)).isoformat()
    with session_factory()() as session:
        value = media_jobs.publish_video(
            session,
            media_jobs.LongVideoRequest(client_request_id=uuid4(), prompt="Quiet river", duration_seconds=4),
            observed_profile=profile,
            execution_deadline_at=deadline,
        )
        plan = session.get(Task, value["task_id"]).metadata_json["media_plan"]
        assert plan["execution_deadline_at"] == deadline
        for identity in [*plan["segment_run_ids"], plan["compose_run_id"]]:
            assert session.get(Run, identity).parameters["execution_deadline_at"] == deadline


def test_agent_profile_checks_managed_constraints_before_prompt_preparation(profile, monkeypatch):
    from app import agent_media
    from app.agent_media_schema import AgentVideoScope

    monkeypatch.setattr(agent_media.RunnerClient, "request", lambda *args, **kwargs: profile)
    assert (
        agent_media.require_profile(
            AgentVideoScope.model_validate({"kind": "video", "request": {"prompt": "Lake"}})
        )
        == profile
    )
    with pytest.raises(ValueError, match="1280"):
        agent_media.require_profile(
            AgentVideoScope.model_validate(
                {"kind": "video", "request": {"prompt": "Lake", "width": 512, "height": 288}}
            )
        )
