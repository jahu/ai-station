"""Profile identity, admission and full-workflow propagation without GPU work."""

from uuid import uuid4

import pytest
from ai_station_runner import avatars as native
from ai_station_runner import memory_scope
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.avatar_schema import FullAvatarSettings
from app.avatars import AvatarRequest
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run, Task
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_avatars import avatar_bridge as avatar_bridge
from test_avatars import inputs
from test_media_jobs import avatar_sources
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge

PROFILE = {"available": True, "memory_profiles": [{"id": "bounded_11g", "available": True, "ram_mib": 11264}]}


@pytest.mark.parametrize("schema", [AvatarRequest, FullAvatarSettings])
def test_default_avatar_serialization_keeps_old_receipt_identity(schema):
    body = {"image_artifact_id": uuid4(), "audio_artifact_id": uuid4()}
    old = schema(**body).model_dump(mode="json")
    assert "memory_profile" not in old
    assert schema(**body, memory_profile="default").model_dump(mode="json") == old
    assert (
        schema(**body, memory_profile="bounded_11g").model_dump(mode="json")["memory_profile"]
        == "bounded_11g"
    )


@pytest.mark.parametrize("schema", [AvatarRequest, FullAvatarSettings])
@pytest.mark.parametrize("change", [{"size": 256}, {"size": 512}, {"steps": 4}])
def test_unqualified_geometry_or_sampling_is_rejected(schema, change):
    with pytest.raises(ValidationError, match="384x384"):
        schema(image_artifact_id=uuid4(), audio_artifact_id=uuid4(), memory_profile="bounded_11g", **change)


@pytest.mark.parametrize("key", ["weight_dtype", "memory_limit", "shell"])
def test_profile_is_not_a_precision_memory_or_command_api(key):
    with pytest.raises(ValidationError, match="Extra inputs"):
        FullAvatarSettings(image_artifact_id=uuid4(), audio_artifact_id=uuid4(), **{key: "arbitrary"})


def test_unavailable_profile_fails_before_any_work_is_published(avatar_bridge):
    with TestClient(app) as api:
        portrait, speech = inputs(api)
        response = api.post(
            "/api/media/jobs/avatar",
            json={
                "client_request_id": str(uuid4()),
                "image_artifact_id": portrait["id"],
                "audio_artifact_id": speech["id"],
                "memory_profile": "bounded_11g",
            },
        )
        assert response.status_code == 409, response.text
        with session_factory()() as db:
            assert not list(db.scalars(select(Run))) and not list(db.scalars(select(Task)))


def test_native_fixed_prefix_and_original_default_argv(avatar_bridge, monkeypatch):
    host, calls = avatar_bridge
    monkeypatch.setenv("AI_STATION_ECHO_BOUNDED_PROFILE", "true")
    clear_settings_cache()
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    prefixes = []
    monkeypatch.setattr(
        memory_scope, "scope_prefix", lambda rid, maximum: prefixes.append((rid, maximum)) or []
    )
    with TestClient(app) as api:
        portrait, speech = inputs(api)
        for profile in ["default", "bounded_11g"]:
            rid = str(uuid4())
            body = {
                "run_id": rid,
                "image_relative": portrait["relative_path"],
                "audio_relative": speech["relative_path"],
                "prompt": "A person speaking",
                "gpu": 7,
                "permissions": ["filesystem_read", "workspace_write"],
                "memory_profile": profile,
            }
            response = host.post("/v1/runs/avatar", json=body)
            assert response.status_code == 200, response.text
            argv = calls[-1]["argv"]
            assert ("--station-bounded-run-id" in argv) is (profile != "default")
            if profile != "default":
                assert prefixes == [(rid, 11264)]
                assert argv[argv.index("--station-bounded-run-id") + 1] == rid
            else:
                assert not prefixes and "--station-mapped-run-id" not in argv


@pytest.mark.parametrize("entry", ["workspace", "agent", "chat"])
def test_reviewed_profile_survives_full_task_and_verified_composition(full_avatar_bridge, monkeypatch, entry):
    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    # The ordinary fixture runs no GPU. Real scope/render qualification is separate.
    with TestClient(app) as api:
        request = {**avatar_sources(api), "size": 384, "steps": 8, "memory_profile": "bounded_11g"}
        if entry == "workspace":
            response = api.post("/api/media/jobs/avatar", json=request)
        elif entry == "agent":
            media = {key: value for key, value in request.items() if key != "client_request_id"}
            definition = api.post(
                "/api/agents",
                json={
                    "name": "Talking report",
                    "goal": "Animate the reviewed recording",
                    "tools": ["create_media"],
                    "enabled": True,
                    "maximum_runtime": 1800,
                    "media": {"kind": "avatar", "description_source": "fixed", "request": media},
                },
            )
            assert definition.status_code == 201, definition.text
            agent = definition.json()
            response = api.post(
                "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
            )
        else:
            from app import avatars

            monkeypatch.setattr(
                avatars, "capabilities", lambda: {**PROFILE, "recommended_memory_profile": "bounded_11g"}
            )
            cid = api.post(
                "/api/chat/conversations", json={"model": "test", "execution_mode": "work"}
            ).json()["id"]
            response = api.post(
                f"/api/chat/conversations/{cid}/messages",
                json={
                    "content": "Animate this portrait",
                    "action": "avatar.animate",
                    "image_artifact_ids": [request["image_artifact_id"]],
                    "audio_artifact_id": request["audio_artifact_id"],
                },
            )
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        for i in range(12):
            with session_factory()() as db:
                if tick(db, f"avatar-profile-{i}") is None:
                    break
        with session_factory()() as db:
            rows = list(db.scalars(select(Run).where(Run.task_id == tid)))
            assert rows and all(row.status == "succeeded" for row in rows), [
                (v.capability, v.status, v.error_message) for v in rows
            ]
            segments = [v for v in rows if v.executor_type == "echomimic"]
            assert len(segments) == 2
            assert all(
                v.parameters["memory_profile"] == "bounded_11g"
                and v.requested_resources == {"ram_mib": 11264}
                for v in segments
            )
            compose = next(v for v in rows if v.executor_type == "media_compose")
            artifact = db.scalar(
                select(Artifact).where(Artifact.run_id == compose.id, Artifact.artifact_type == "video")
            )
            assert (
                artifact.metadata_json["verified"]
                and artifact.metadata_json["memory_profile"] == "bounded_11g"
            )
            if entry == "agent":
                expiry = next(v for v in rows if v.executor_type == "agent_workflow").parameters[
                    "media_deadline_at"
                ]
                assert all(v.parameters["execution_deadline_at"] == expiry for v in segments)
            task = db.get(Task, tid)
            assert task.metadata_json["media_plan"]["request"]["memory_profile"] == "bounded_11g"
        assert all(v.memory_profile == "bounded_11g" for v in full_avatar_bridge)


@pytest.mark.parametrize(
    "available,expected",
    [
        (13000, "bounded_11g"),
        (20000, "bounded_11g"),
        (30000, "default"),
        (None, "default"),
        (-1, "default"),
        (True, "default"),
        (float("nan"), "default"),
        ("13000", "default"),
    ],
)
def test_recommendation_uses_only_finite_measured_free_memory(monkeypatch, available, expected):
    from app.runner_client import RunnerClient

    def request(self, method, path, json=None):
        assert (method, path) == ("GET", "/v1/avatar/capabilities")
        return PROFILE

    monkeypatch.setattr(RunnerClient, "request", request)
    monkeypatch.setattr(RunnerClient, "hardware", lambda _: {"memory": {"available_mib": available}})
    with TestClient(app) as api:
        response = api.get("/api/avatars/capabilities")
        assert response.status_code == 200 and response.json()["available"]
        assert response.json()["recommended_memory_profile"] == expected


def test_resume_preserves_profile_and_cannot_bypass_lost_readiness(full_avatar_bridge, monkeypatch):
    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    with TestClient(app) as api:
        request = {**avatar_sources(api), "size": 384, "steps": 8, "memory_profile": "bounded_11g"}
        first = api.post("/api/media/jobs/avatar", json=request)
        assert first.status_code == 202, first.text
        tid = first.json()["task_id"]
        api.post("/api/media/jobs/" + tid + "/cancel").raise_for_status()
        resumed = api.post(
            "/api/media/jobs/" + tid + "/resume",
            json={
                "expected_revision": 1,
                "client_request_id": str(uuid4()),
            },
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["request"]["memory_profile"] == "bounded_11g"
        api.post("/api/media/jobs/" + tid + "/cancel").raise_for_status()
        monkeypatch.setattr(native, "capabilities", lambda: {"available": True, "memory_profiles": []})
        rejected = api.post(
            "/api/media/jobs/" + tid + "/resume",
            json={
                "expected_revision": 2,
                "client_request_id": str(uuid4()),
            },
        )
        assert rejected.status_code == 409, rejected.text


@pytest.mark.parametrize("full", [False, True])
def test_standard_reserves_observed_loader_memory_and_waits_without_launch(avatar_bridge, monkeypatch, full):
    from app.runner_client import RunnerClient

    _, calls = avatar_bridge
    monkeypatch.setattr(
        RunnerClient, "hardware", lambda _: {"gpus": [{"index": 7}], "memory": {"available_mib": 20000}}
    )
    with TestClient(app) as api:
        portrait, speech = inputs(api)
        body = {"image_artifact_id": portrait["id"], "audio_artifact_id": speech["id"]}
        path = "/api/media/jobs/avatar" if full else "/api/avatars/runs"
        if full:
            body["client_request_id"] = str(uuid4())
        response = api.post(path, json=body)
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            tick(db, "standard-memory-check")
            rows = list(db.scalars(select(Run).where(Run.executor_type == "echomimic")))
            assert rows and all(v.requested_resources == {"ram_mib": 24576} for v in rows)
            assert all(v.status == "queued" and v.actual_gpu is None for v in rows)
            assert rows[0].metadata_json["resource_wait"]["required_mib"] == 24576
        assert not calls, "Standard launched despite insufficient RAM for its measured loader"
