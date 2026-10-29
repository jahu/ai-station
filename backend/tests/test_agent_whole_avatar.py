"""Reviewed whole-recording agents reuse the same manual media graph."""

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Artifact, Notice, Run
from app.resources import active_locks
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, no_text_model, start
from test_whole_avatar_jobs import bridge as bridge
from test_whole_avatar_jobs import drain
from test_whole_avatars import PROFILE
from test_whole_avatars import sources as sources


def test_agent_readiness_accepts_a_sonic_only_installation(monkeypatch):
    from app.agent_media import runtime_readiness
    from app.runner_client import RunnerClient

    monkeypatch.setattr("app.music.capabilities", lambda: {})
    monkeypatch.setattr(
        RunnerClient,
        "request",
        lambda self, method, path: PROFILE if path.endswith("whole-capabilities") else {},
    )
    assert runtime_readiness()["avatar"] == {"ready": True, "speech_ready": False, "reason": None}


@pytest.mark.parametrize("generated", [False, True])
def test_reviewed_whole_avatar_agent_only_announces_its_verified_final_recording(
    bridge, monkeypatch, generated
):
    identifiers, state = bridge
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    request = {
        "image_artifact_id": identifiers[0],
        "audio_artifact_id": identifiers[1],
        "generation_profile": PROFILE["recipe"]["id"],
    }
    if generated:
        request["speech_text"] = "Neutral speech for the reviewed recording."
    with TestClient(app) as api:
        agent = create(
            api,
            kind="avatar",
            request=request,
            maximum_runtime=7200,
            notification_policy={"on_success": True},
        )
        root = start(api, agent)
        drain()
        result = api.get("/api/agents/" + agent["id"]).json()
        assert result["last_status"] == "succeeded", result
        workflow = api.get("/api/runs/" + root["id"]).json()["workflow"]
        assert any(step["capability"] == "avatar.animate" for step in workflow["steps"])
    with session_factory()() as db:
        parent = db.get(Run, root["id"])
        assert parent.parameters["avatar_whole_recipe"] == PROFILE["recipe"]
        assert "avatar_appearance_recipe" not in parent.parameters
        runs = list(db.scalars(select(Run).where(Run.task_id == parent.task_id)))
        assert all(run.status == "succeeded" for run in runs), [
            (run.executor_type, run.status, run.error_message) for run in runs
        ]
        final = next(run for run in runs if run.executor_type == "sonic_whole")
        artifact = db.scalar(
            select(Artifact).where(Artifact.run_id == final.id, Artifact.artifact_type == "video")
        )
        assert artifact and artifact.metadata_json["verified"] is True
        notices = list(db.scalars(select(Notice)))
        assert len(notices) == 1 and notices[0].run_id == final.id
        assert not active_locks(db)
        budget = final.parameters["execution_deadline_at"]
        assert all(
            run.parameters["execution_deadline_at"] == budget
            for run in runs
            if run.executor_type != "agent_workflow"
        )
        assert (
            final.agent_id == agent["id"]
            and final.parameters["whole_recipe"] == parent.parameters["avatar_whole_recipe"]
        )
    assert len(state["whole"]) == 1
    assert len(state["speech"]) == (1 if generated else 0)
