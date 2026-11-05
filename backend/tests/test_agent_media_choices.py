"""Registered media suggestions are data for disabled drafts, never model installs."""

import json
from uuid import uuid4

import pytest
from app.agent_media_choices import catalog, validate_selection
from app.agent_media_schema import AgentImageScope
from app.api import app
from app.db import control_session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, ModelDefinition
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_drafts import model as model
from test_agent_drafts import state, step, submit
from test_hub_video_installation import prepared
from test_hub_video_installation import video_bridge as video_bridge
from test_image_models import registered


def proposal(identifier):
    return {
        "name": "Morning river film",
        "goal": "Generate a silent river scene.",
        "tools": ["create_media"],
        "media": {
            "kind": "video",
            "request": {
                "model_id": identifier,
                "prompt": "River at sunrise",
                "duration_seconds": 5,
                "width": 1280,
                "height": 704,
                "steps": 20,
                "memory_profile": "bounded_11g",
            },
        },
    }


def test_image_choices_omit_paths_and_reject_incompatible_backend_or_removed_files(session):
    row, file = registered(session)
    offered = catalog(session)
    assert offered == [
        {"kind": "image", "model_id": row.id, "name": row.name, "backend": "krea2", "mode": "t2i"}
    ]
    assert file.host_path not in json.dumps(offered)
    media = AgentImageScope.model_validate(
        {
            "kind": "image",
            "request": {"model_id": row.id, "mode": "t2i", "backend": "krea2", "prompt": "River"},
        }
    )
    validate_selection(session, media, offered)
    row.name = "Renamed installed image"
    session.flush()
    validate_selection(session, media, offered)
    with pytest.raises(ValueError, match="registered backend"):
        validate_selection(
            session,
            media.model_copy(update={"request": media.request.model_copy(update={"backend": "qwen"})}),
            offered,
        )
    file.availability = "missing"
    session.flush()
    with pytest.raises(ValueError, match="changed"):
        validate_selection(session, media, offered)


def test_queued_draft_knows_the_installed_video_and_preserves_reviewed_workload(model, video_bridge):
    calls, responses = model
    with TestClient(app) as api:
        installed = prepared(api)
        identifier = installed["definition_id"]
        responses[0] = json.dumps(proposal(identifier))
        run = submit(
            api, instruction="Create an agent that makes a river video using my installed Wan checkpoint"
        )
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert not agent["enabled"] and agent["tools"] == ["create_media"]
        assert agent["media"]["request"]["model_id"] == identifier
        assert agent["media"]["request"]["memory_profile"] == "bounded_11g"
        prompt = json.loads(calls[0]["messages"][1]["content"])
        choices = prompt["registered_media_models"]
        assert choices[0]["model_id"] == identifier and choices[0]["cpu_offload"] is True
        assert "host_path" not in json.dumps(choices) and "source_url" not in json.dumps(choices)
        assert not video_bridge["starts"]  # Preparing a draft launches no media inference.


@pytest.mark.parametrize("change", ["invented", "workload", "removed"])
def test_model_identity_and_workload_cannot_escape_the_review_catalog(
    model, video_bridge, monkeypatch, change
):
    calls, responses = model
    with TestClient(app) as api:
        installed = prepared(api)
        identifier = installed["definition_id"]
        proposed = proposal(str(uuid4()) if change == "invented" else identifier)
        if change == "workload":
            proposed["media"]["request"]["memory_profile"] = "default"
        responses[0] = json.dumps(proposed)
        if change == "removed":

            async def stream(self, **params):
                calls.append(params)
                with control_session_factory()() as db:
                    db.get(ModelDefinition, identifier).status = "failed"
                    db.commit()
                yield responses[0]

            monkeypatch.setattr(LocalChatProvider, "stream", stream)
        run = submit(api, instruction="Create a local river video agent")
        step()
        done = state(api, run)
        assert done["status"] == "failed" and len(calls) == 2
        with control_session_factory()() as db:
            assert not list(db.scalars(select(Agent)))
        assert not video_bridge["starts"]


def test_registered_image_suggestion_survives_the_legacy_family_default(model):
    calls, responses = model
    with TestClient(app) as api:
        with control_session_factory()() as db:
            row, _ = registered(db)
            row.name = "Studio Photo"
            identifier = row.id
            db.commit()
        responses[0] = json.dumps(
            {
                "name": "Studio agent",
                "goal": "Create an image of a river",
                "tools": ["create_media"],
                "media": {
                    "kind": "image",
                    "request": {"mode": "t2i", "backend": "krea2", "model_id": identifier, "prompt": "River"},
                },
            }
        )
        run = submit(api, instruction="Create an image agent using Studio Photo")
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert not agent["enabled"]
        assert agent["media"]["request"]["model_id"] == identifier
        assert agent["media"]["request"]["backend"] == "krea2"
        assert len(calls) == 1
