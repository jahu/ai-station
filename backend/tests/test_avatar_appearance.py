from uuid import uuid4

import pytest
from ai_station_runner import avatars as native
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run, Task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_avatars import avatar_bridge as avatar_bridge
from test_avatars import inputs
from test_media_jobs import avatar_sources
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge

RECIPE = {"id": "portrait_anchor_v1", "observation": "a" * 64}
PROFILE = {
    "available": True,
    "recommended_appearance_profile": RECIPE["id"],
    "appearance_profiles": [{**RECIPE, "available": True}],
}


def drain():
    for index in range(16):
        with session_factory()() as db:
            if tick(db, f"appearance-{index}") is None:
                return
    raise AssertionError("Disposable avatar workflow did not drain")


@pytest.mark.parametrize("speech", [None, "Keep the complete narration"])
@pytest.mark.parametrize("entry", ["workspace", "agent", "legacy_agent"])
def test_recipe_reaches_manual_and_agent_speech_animation_and_final_artifact(
    full_avatar_bridge, monkeypatch, speech, entry
):
    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    with TestClient(app) as api:
        body = {**avatar_sources(api), "size": 384, "steps": 8}
        if speech is not None:
            body["speech_text"] = speech
        if entry == "workspace":
            response = api.post("/api/media/jobs/avatar", json=body)
            assert response.status_code == 202, response.text
            tid = response.json()["task_id"]
            # A capability change cannot reinterpret an acknowledged request ID.
            monkeypatch.setattr(native, "capabilities", lambda: {"available": False})
            repeat = api.post("/api/media/jobs/avatar", json=body)
            assert repeat.status_code == 202 and repeat.json()["task_id"] == tid
            monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
        else:
            created = api.post(
                "/api/agents",
                json={
                    "name": "Talking QA report",
                    "goal": "Animate the reviewed recording",
                    "tools": ["create_media"],
                    "enabled": True,
                    "maximum_runtime": 1800,
                    "media": {
                        "kind": "avatar",
                        "description_source": "fixed",
                        "request": {key: value for key, value in body.items() if key != "client_request_id"},
                    },
                },
            )
            assert created.status_code == 201, created.text
            agent = created.json()
            response = api.post(
                "/api/agents/" + agent["id"] + "/run",
                json={"expected_updated_at": agent["updated_at"]},
            )
            assert response.status_code == 202, response.text
            tid = response.json()["task_id"]
            with session_factory()() as db:
                root = db.scalar(select(Run).where(Run.task_id == tid, Run.executor_type == "agent_workflow"))
                assert root.parameters["avatar_appearance_recipe"] == RECIPE
                if entry == "legacy_agent":
                    root.parameters = {
                        key: value
                        for key, value in root.parameters.items()
                        if key != "avatar_appearance_recipe"
                    }
                    db.commit()
        drain()
        result = api.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded", result
        assert len(full_avatar_bridge) == 2
        expected = None if entry == "legacy_agent" else RECIPE
        assert all(body.appearance_recipe == expected for body in full_avatar_bridge)
        with session_factory()() as db:
            task = db.get(Task, tid)
            assert task.metadata_json["media_plan"].get("appearance_recipe") == expected
            assert "appearance_recipe" not in task.metadata_json["media_plan"]["request"]
            artifact = db.get(Artifact, result["final_artifact_id"])
            assert artifact.metadata_json.get("appearance_recipe") == expected
            assert artifact.metadata_json["frames"] == 125 and artifact.metadata_json["verified"]


@pytest.mark.parametrize("legacy", [False, True])
def test_resume_never_promotes_old_plan_or_mixes_changed_observations(
    full_avatar_bridge, monkeypatch, legacy
):
    monkeypatch.setattr(native, "capabilities", lambda: {"available": True} if legacy else PROFILE)
    with TestClient(app) as api:
        body = {**avatar_sources(api), "size": 384, "steps": 8}
        response = api.post("/api/media/jobs/avatar", json=body)
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        assert api.post("/api/media/jobs/" + tid + "/cancel").json()["status"] == "canceled"
        changed = {**PROFILE, "appearance_profiles": [{**RECIPE, "observation": "b" * 64, "available": True}]}
        monkeypatch.setattr(native, "capabilities", lambda: changed)
        with session_factory()() as db:
            before = set(db.scalars(select(Run.id).where(Run.task_id == tid)))
        resumed = api.post(
            "/api/media/jobs/" + tid + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        if legacy:
            assert resumed.status_code == 202, resumed.text
            drain()
            assert all(body.appearance_recipe is None for body in full_avatar_bridge)
            with session_factory()() as db:
                assert "appearance_recipe" not in db.get(Task, tid).metadata_json["media_plan"]
        else:
            assert resumed.status_code == 409 and "appearance" in resumed.text, resumed.text
            with session_factory()() as db:
                assert set(db.scalars(select(Run.id).where(Run.task_id == tid))) == before
            assert full_avatar_bridge == []


def test_changed_recipe_cannot_reuse_preceding_motion(full_avatar_bridge, monkeypatch):
    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    with TestClient(app) as api:
        response = api.post("/api/media/jobs/avatar", json={**avatar_sources(api), "size": 384, "steps": 8})
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        with session_factory()() as db:
            tick(db, "first-avatar-window")
        with session_factory()() as db:
            plan = db.get(Task, tid).metadata_json["media_plan"]
            second = db.get(Run, plan["segment_run_ids"][1])
            second_id = second.id
            second.parameters = {
                **second.parameters,
                "appearance_recipe": {**RECIPE, "observation": "b" * 64},
            }
            db.commit()
        drain()
        assert len(full_avatar_bridge) == 1
        result = api.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "failed"
        rejected = api.get("/api/runs/" + second_id).json()
        assert rejected["status"] == "failed" and "different appearance" in rejected["error_message"]


def test_delayed_speech_planning_cannot_adopt_a_new_recipe(full_avatar_bridge, monkeypatch):
    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    with TestClient(app) as api:
        response = api.post(
            "/api/media/jobs/avatar",
            json={**avatar_sources(api), "size": 384, "steps": 8, "speech_text": "Original complete speech"},
        )
        assert response.status_code == 202, response.text
        tid = response.json()["task_id"]
        changed = {**PROFILE, "appearance_profiles": [{**RECIPE, "observation": "b" * 64, "available": True}]}
        monkeypatch.setattr(native, "capabilities", lambda: changed)
        drain()
        assert full_avatar_bridge == []
        assert api.get("/api/media/jobs/" + tid).json()["status"] == "failed"
        with session_factory()() as db:
            task = db.get(Task, tid)
            assert task.metadata_json["media_plan"]["appearance_recipe"] == RECIPE
            assert task.metadata_json["media_plan"]["timing"] is None
            speech = db.scalar(select(Run).where(Run.task_id == tid, Run.executor_type == "chatterbox"))
            assert speech.status == "succeeded"


def test_native_changed_observation_rejects_before_starting_process(avatar_bridge):
    host, calls = avatar_bridge
    with TestClient(app) as api:
        portrait, speech = inputs(api)
    response = host.post(
        "/v1/runs/avatar",
        json={
            "run_id": str(uuid4()),
            "image_relative": portrait["relative_path"],
            "audio_relative": speech["relative_path"],
            "prompt": "Speaking",
            "gpu": 7,
            "audio_window": {"start_frame": 0},
            "appearance_recipe": RECIPE,
            "permissions": ["filesystem_read", "workspace_write"],
        },
    )
    assert response.status_code == 409 and "observation changed" in response.text
    assert calls == []


def test_stop_and_resume_reuse_completed_window_and_its_frozen_recipe(full_avatar_bridge, monkeypatch):
    import hashlib

    from app.config import get_settings
    from app.paths import safe_join

    monkeypatch.setattr(native, "capabilities", lambda: PROFILE)
    with TestClient(app) as api:
        created = api.post("/api/media/jobs/avatar", json={**avatar_sources(api), "size": 384, "steps": 8})
        assert created.status_code == 202, created.text
        tid = created.json()["task_id"]
        with session_factory()() as db:
            tick(db, "first-completed-window")
            first_id = db.get(Task, tid).metadata_json["media_plan"]["segment_run_ids"][0]
            first = db.get(Run, first_id)
            original_times = (first.started_at, first.finished_at)
            artifact = db.scalar(select(Artifact).where(Artifact.run_id == first_id))
            first_path = safe_join(get_settings().data_dir, artifact.relative_path)
            digest = artifact.sha256
        stopped = api.post("/api/media/jobs/" + tid + "/cancel")
        assert stopped.status_code == 200 and stopped.json()["completed_segments"] == 1
        assert stopped.json()["status"] == "canceled"
        # A changed recommendation is not a reason to rewrite a supported plan.
        monkeypatch.setattr(
            native, "capabilities", lambda: {**PROFILE, "recommended_appearance_profile": None}
        )
        resumed = api.post(
            "/api/media/jobs/" + tid + "/resume",
            json={"client_request_id": str(uuid4()), "expected_revision": 1},
        )
        assert resumed.status_code == 202, resumed.text
        drain()
        result = api.get("/api/media/jobs/" + tid).json()
        assert result["status"] == "succeeded" and result["revision"] == 2
        assert len(full_avatar_bridge) == 2
        assert all(body.appearance_recipe == RECIPE for body in full_avatar_bridge)
        assert hashlib.sha256(first_path.read_bytes()).hexdigest() == digest
        with session_factory()() as db:
            first = db.get(Run, first_id)
            assert (first.started_at, first.finished_at) == original_times
            plan = db.get(Task, tid).metadata_json["media_plan"]
            assert plan["segment_run_ids"][0] == first_id and plan["appearance_recipe"] == RECIPE
