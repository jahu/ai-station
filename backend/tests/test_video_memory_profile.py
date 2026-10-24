"""Frozen reduced-memory jobs retain legacy receipts and ordinary Run admission."""

from uuid import uuid4

import pytest
from ai_station_runner import memory_scope
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import session_factory
from app.models import Run, Task
from app.video_schema import LongVideoSettings, VideoRequest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_media_jobs import bridge as bridge


def test_old_and_explicit_default_settings_have_identical_serialized_identity():
    for schema in (VideoRequest, LongVideoSettings):
        old = schema(prompt="Scene")
        explicit = schema(prompt="Scene", memory_profile="default")
        assert old.model_dump(mode="json") == explicit.model_dump(mode="json")
        assert "memory_profile" not in old.model_dump()


@pytest.mark.parametrize("change", [{"width": 512}, {"height": 288}, {"steps": 4}])
def test_reduced_profile_rejects_unqualified_geometry_and_sampling(change):
    with pytest.raises(ValidationError):
        VideoRequest(prompt="Scene", memory_profile="bounded_11g", **change)


def test_disabled_native_profile_cannot_publish_a_lower_memory_reservation(bridge):
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/video/runs", json={"prompt": "Scene", "memory_profile": "bounded_11g"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/media/jobs/video",
                json={"prompt": "Scene", "memory_profile": "bounded_11g", "client_request_id": str(uuid4())},
            ).status_code
            == 409
        )
    with session_factory()() as session:
        assert not list(session.scalars(select(Run)))


def test_reviewed_job_freezes_profile_and_ram_but_cannot_reuse_legacy_receipt(bridge, monkeypatch):
    monkeypatch.setenv("AI_STATION_WAN_BOUNDED_PROFILE", "true")
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    clear_settings_cache()
    body = {
        "client_request_id": str(uuid4()),
        "prompt": "Coast",
        "memory_profile": "bounded_11g",
        "duration_seconds": 5,
    }
    with TestClient(app) as client:
        response = client.post("/api/media/jobs/video", json=body)
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        assert response.json()["request"]["memory_profile"] == "bounded_11g"
        with session_factory()() as session:
            task = session.get(Task, tid)
            plan = task.metadata_json["media_plan"]
            for rid in plan["segment_run_ids"]:
                run = session.get(Run, rid)
                assert run.requested_resources == {"ram_mib": 11264}
                assert run.parameters["memory_profile"] == "bounded_11g"
                assert run.parameters["profile_observation"] == plan["profile_observation"]
        assert (
            client.post("/api/media/jobs/video", json={**body, "memory_profile": "default"}).status_code
            == 409
        )
        # A saved receipt remains readable even if the option is later disabled.
        monkeypatch.setenv("AI_STATION_WAN_BOUNDED_PROFILE", "false")
        clear_settings_cache()
        assert client.post("/api/media/jobs/video", json=body).json()["task_id"] == tid


def test_short_clip_uses_the_same_reduced_reservation(bridge, monkeypatch):
    monkeypatch.setenv("AI_STATION_WAN_BOUNDED_PROFILE", "true")
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    clear_settings_cache()
    with TestClient(app) as client:
        response = client.post("/api/video/runs", json={"prompt": "Coast", "memory_profile": "bounded_11g"})
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            run = session.get(Run, response.json()["id"])
            assert run.requested_resources == {"ram_mib": 11264}


def test_nested_agent_default_profile_preserves_definition_identity():
    from app.agent_media_schema import AgentVideoScope

    legacy = {"kind": "video", "request": {"prompt": "Scene"}}
    old = AgentVideoScope.model_validate(legacy).model_dump(mode="json")
    explicit = AgentVideoScope.model_validate(
        {"kind": "video", "request": {"prompt": "Scene", "memory_profile": "default"}}
    ).model_dump(mode="json")
    assert old == explicit and "memory_profile" not in old["request"]
    chosen = AgentVideoScope.model_validate(
        {"kind": "video", "request": {"prompt": "Scene", "memory_profile": "bounded_11g"}}
    ).model_dump(mode="json")
    assert chosen["request"]["memory_profile"] == "bounded_11g"
