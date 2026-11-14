"""Selected conversation models reach ordinary frozen film Runs, without inference."""

from uuid import uuid4

import pytest
from app import video, video_models
from app.api import app
from app.assistant import VideoScope
from app.db import session_factory
from app.engine import tick
from app.models import ModelDefinition, Run, Task
from app.svi_executor import GEOMETRY, NAME, RAM_MIB
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_assistant import create, image
from test_assistant_controller import model as model
from test_assistant_controller import submit
from test_svi_models import install
from test_svi_models import prepared as prepared


@pytest.fixture
def selected(session, prepared, monkeypatch):
    definition, installed = install(session, prepared)
    session.commit()
    calls = []

    def observe(_client, method, path, payload):
        assert (method, path) == ("POST", "/v1/video/svi/model-capabilities")
        assert payload["managed_runtime"] == installed["managed_runtime"]
        calls.append(payload)
        portrait = payload.get("generation_profile") == "portrait"
        return {
            "available": True,
            "backend": "wan22-svi-pro-q4",
            **GEOMETRY,
            "width": 480 if portrait else 832,
            "height": 832 if portrait else 480,
            "generation_profiles": [
                {"id": "landscape", "width": 832, "height": 480},
                {"id": "portrait", "width": 480, "height": 832},
            ],
            "managed_runtime": installed["managed_runtime"],
            "native_window_frames": 81,
            "continuation_frames": 4,
            "memory_estimate_mib": RAM_MIB,
            "eligible_gpu_indices": [7],
        }

    monkeypatch.setattr(video_models.RunnerClient, "request", observe)
    monkeypatch.setattr(
        video, "capabilities", lambda: pytest.fail("A selected model must not use the default engine")
    )
    return definition.id, calls


@pytest.mark.parametrize("width,height", [(832, 480), (480, 832)])
def test_chat_selected_recurrent_model_publishes_its_exact_recipe(selected, width, height):
    model, calls = selected
    with TestClient(app) as api:
        cid = create(api)
        source = image(api)
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Animate this image as one continuous ten-second film",
                "action": "video.generate",
                "image_artifact_ids": [source],
                "web_search": {"enabled": False},
                "media_translation": {"mode": "off"},
                "media": {"duration_seconds": 10, "model_id": model, "width": width, "height": height},
            },
        )
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        with session_factory()() as db:
            assert tick(db, "conversation-video-selection") == identity
        with session_factory()() as db:
            root = db.get(Run, identity)
            assert root.status == "succeeded", root.error_message
            runs = list(db.scalars(select(Run).where(Run.task_id == root.task_id)))
            assert not any(r.executor_type == "wan_video" for r in runs)
            clips = [r for r in runs if r.executor_type == NAME]
            assert len(clips) == 2
            for clip in clips:
                assert (clip.parameters["width"], clip.parameters["height"], clip.parameters["fps"]) == (
                    width,
                    height,
                    15,
                )
                assert clip.parameters["video_model"]["definition_id"] == model
                assert clip.parameters["steps"] == 20 and clip.parameters["cfg"] == 5
                assert clip.parameters["image_artifact_id"] == source
                assert clip.requested_resources["ram_mib"] == RAM_MIB
            plan = db.get(Task, root.task_id).metadata_json["media_plan"]
            assert plan["timing"]["fps"] == 15 and plan["timing"]["target_frames"] == 150
        assert calls and all((c.get("generation_profile") == "portrait") == (height > width) for c in calls)


def test_video_scope_preserves_legacy_serialization_and_requires_complete_format():
    assert VideoScope(duration_seconds=10).model_dump() == {
        "duration_seconds": 10,
        "composition_mode": "continuous",
    }
    with pytest.raises(ValidationError):
        VideoScope(duration_seconds=10, model_id=uuid4(), width=480)


def test_closed_selected_model_never_falls_back_to_default(selected, monkeypatch):
    model, _ = selected
    monkeypatch.setattr(
        video_models.RunnerClient,
        "request",
        lambda *args: {"available": False, "reason": "Portrait qualification is closed"},
    )
    with TestClient(app) as api:
        cid = create(api)
        response = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Animate this image for ten seconds",
                "action": "video.generate",
                "image_artifact_ids": [image(api)],
                "web_search": {"enabled": False},
                "media": {"duration_seconds": 10, "model_id": model, "width": 480, "height": 832},
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as db:
            tick(db, "closed-conversation-video")
        with session_factory()() as db:
            root = db.get(Run, response.json()["id"])
            assert root.metadata_json["plan"]["action"] == "clarify"
            assert "Portrait qualification is closed" in root.metadata_json["plan"]["reason"]
            assert not db.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.executor_type.in_([NAME, "wan_video"]))
            )


@pytest.mark.parametrize("reviewed", [False, True])
def test_orchestrator_binds_only_a_frozen_registered_model_and_keeps_reviewed_format(
    selected, model, reviewed
):
    from app.assistant_controller_tools import wrapper_parameters
    from app.assistant_video_profiles import public_catalog

    identifier, _ = selected
    scope = {"duration_seconds": 10, "model_id": identifier, "width": 480, "height": 832}
    with TestClient(app) as api:
        result = submit(
            api,
            "Make a continuous ten-second portrait film",
            image_artifact_ids=[image(api)],
            **({"media": scope} if reviewed else {}),
        )
        with session_factory()() as db:
            root = db.get(Run, result["run"]["id"])
            offered = root.parameters["controller_video_catalog"]
            assert offered[identifier]["image_required"] is True
            assert "identity" not in public_catalog(offered)[identifier]
            arguments = {
                "instruction": "The hiker takes two natural steps",
                "images": ["input:image:1"],
                "duration_seconds": 10,
                "video_model": identifier,
                "video_format": "portrait",
            }
            bound = wrapper_parameters(db, root, "video.generate", arguments)
            assert all(bound["media"][key] == value for key, value in scope.items())
            if reviewed:
                with pytest.raises(ValueError, match="selected video duration"):
                    wrapper_parameters(db, root, "video.generate", {**arguments, "duration_seconds": 20})
            with pytest.raises(ValueError, match="selected video format|registered video_models alias"):
                wrapper_parameters(
                    db,
                    root,
                    "video.generate",
                    {
                        **arguments,
                        **({"video_format": "landscape"} if reviewed else {"video_model": str(uuid4())}),
                    },
                )
            definition = db.get(ModelDefinition, identifier)
            definition.status = "unavailable"
            db.flush()
            with pytest.raises(ValueError, match="unavailable or changed"):
                wrapper_parameters(db, root, "video.generate", arguments)
