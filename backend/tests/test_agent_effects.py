"""Media agents reuse the qualified effects pipeline; normal inference is synthetic."""

import pytest
from app.api import app
from app.db import control_session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.media_results import final_media_executor
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, drain, no_text_model, start
from test_effects import sound_bridge as sound_bridge
from test_effects import source_video


def test_fixed_effects_agent_publishes_stem_and_verified_preview_without_text_inference(
    sound_bridge, monkeypatch
):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        source = source_video(api)
        agent = create(
            api,
            kind="effects",
            request={
                "video_artifact_id": source,
                "prompt": "Rain on leaves",
                "cues": [{"start_frame": 0, "end_frame": 24, "prompt": "A single bird call"}],
                "seed": 42,
            },
        )
        root = start(api, agent)
        with control_session_factory()() as db:
            drain(db)
            runs = list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(r.status == "succeeded" for r in runs), [
                (r.executor_type, r.status, r.error_message) for r in runs
            ]
            stem = next(r for r in runs if r.executor_type == "mmaudio_effects")
            preview = next(r for r in runs if r.executor_type == "effects_preview")
            assert stem.agent_id == agent["id"] and preview.agent_id == agent["id"]
            assert stem.parameters["cues"] == [
                {"start_frame": 0, "end_frame": 24, "prompt": "A single bird call"}
            ]
            assert stem.parameters["media_inputs"][0]["id"] == source
            assert stem.parameters["execution_deadline_at"] == preview.parameters["execution_deadline_at"]
        assert api.get("/api/artifacts", params={"run_id": stem.id}).json()[0]["type"] == "audio"
        result = api.get("/api/artifacts", params={"run_id": preview.id}).json()[0]
        assert result["type"] == "video" and result["metadata"]["verified"]
        assert final_media_executor(agent["media"]) == "effects_preview"
        from app.agent_email_results import verified_result
        from app.agent_schema import AgentSettings

        with control_session_factory()() as db:
            parent = db.get(Run, root["id"])
            definition = AgentSettings.model_validate(parent.parameters["definition"])
            summary = verified_result(
                db, db.get(Run, preview.id), parent, definition, media_metadata_only=True
            )
            assert summary["family"] == "media"
            with pytest.raises(ValueError, match="final result"):
                verified_result(db, db.get(Run, stem.id), parent, definition, media_metadata_only=True)


def test_effects_agent_can_save_without_reference_but_cannot_enable_or_run(sound_bridge):
    with TestClient(app) as api:
        draft = api.post(
            "/api/agents",
            json={
                "name": "Film sound",
                "goal": "Give a film an atmosphere",
                "tools": ["create_media"],
                "media": {"kind": "effects", "request": {"prompt": "Wind in trees"}},
            },
        )
        assert draft.status_code == 201, draft.text
        row = draft.json()
        enabled = api.post(
            "/api/agents/" + row["id"] + "/enabled",
            json={"enabled": True, "expected_updated_at": row["updated_at"]},
        )
        assert enabled.status_code in (400, 409, 422), enabled.text
        assert "Library film" in enabled.text
        failed = api.post(
            "/api/agents/" + row["id"] + "/run", json={"expected_updated_at": row["updated_at"]}
        )
        assert failed.status_code in (400, 409, 422), failed.text


def test_effects_agent_rejects_scene_outside_the_reviewed_film(sound_bridge):
    from app.agent_media import freeze_inputs
    from app.agent_media_schema import AgentEffectsScope

    with TestClient(app) as api:
        source = source_video(api)
        scope = AgentEffectsScope.model_validate(
            {
                "kind": "effects",
                "request": {
                    "video_artifact_id": source,
                    "prompt": "Wind",
                    "cues": [{"start_frame": 0, "end_frame": 100, "prompt": "Rain"}],
                },
            }
        )
        with control_session_factory()() as db:
            with pytest.raises(ValueError, match="exceeds"):
                freeze_inputs(db, scope)


@pytest.mark.parametrize("stop_before", [True, False])
def test_effects_agent_approval_and_stop_reuse_workflow_authority(sound_bridge, stop_before):
    with TestClient(app) as api:
        agent = create(
            api,
            kind="effects",
            request={"video_artifact_id": source_video(api), "prompt": "Wind"},
            workflow_mode="gated",
        )
        root = start(api, agent)
        with control_session_factory()() as db:
            drain(db)
            stage = db.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert stage.status == "waiting_for_approval"
            assert (
                db.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "mmaudio_effects")
                )
                is None
            )
        if stop_before:
            assert api.post("/api/runs/" + root["id"] + "/cancel").status_code == 200
        else:
            assert (
                api.post("/api/runs/" + stage.id + "/approval", json={"resolution": "granted"}).status_code
                == 200
            )
        with control_session_factory()() as db:
            drain(db)
            outputs = list(
                db.scalars(
                    select(Run).where(
                        Run.task_id == root["task_id"],
                        Run.executor_type.in_(["mmaudio_effects", "effects_preview"]),
                    )
                )
            )
            if stop_before:
                assert not outputs
            else:
                assert len(outputs) == 2 and all(r.status == "succeeded" for r in outputs)


def test_effects_agent_publication_reconciles_receipts_without_runner_io(sound_bridge, monkeypatch):
    from app import agent_media
    from app.agent_schema import AgentSettings
    from app.runner_client import RunnerClient

    inside = {"publication": False}
    original_publish, original_request = agent_media.publish_media, RunnerClient.request

    def publish(*args, **kwargs):
        inside["publication"] = True
        try:
            return original_publish(*args, **kwargs)
        finally:
            inside["publication"] = False

    def request(self, method, path, json=None):
        assert not inside["publication"], "No Runner HTTP while committing a media child"
        return original_request(self, method, path, json)

    monkeypatch.setattr(agent_media, "publish_media", publish)
    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as api:
        agent = create(
            api, kind="effects", request={"video_artifact_id": source_video(api), "prompt": "Wind"}
        )
        root = start(api, agent)
        with control_session_factory()() as db:
            assert tick(db, "root-receipt") == root["id"]
            stage = db.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert tick(db, "effect-receipt") == stage.id
            db.refresh(stage)
            child = db.get(Run, stage.metadata_json["media_run_id"])
            scope = AgentSettings.model_validate(stage.parameters["definition"]).media
            profile = agent_media.require_profile(scope)
            replay = publish(db, stage, scope, profile, child.metadata_json["agent_media_preparation_id"])
            assert replay.id == child.id
            assert (
                len(
                    list(
                        db.scalars(
                            select(Run).where(
                                Run.task_id == root["task_id"], Run.executor_type == "mmaudio_effects"
                            )
                        )
                    )
                )
                == 1
            )


def test_effects_agent_frozen_source_bytes_cannot_change_before_publication(sound_bridge):
    from app.config import get_settings
    from app.models import Artifact

    with TestClient(app) as api:
        source = source_video(api)
        agent = create(api, kind="effects", request={"video_artifact_id": source, "prompt": "Wind"})
        root = start(api, agent)
        with control_session_factory()() as db:
            assert tick(db, "source-root") == root["id"]
            a = db.get(Artifact, source)
            path = get_settings().data_dir / a.relative_path
            path.write_bytes(path.read_bytes() + b"changed")
            drain(db)
            stage = db.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert stage.status == "failed"
            assert not list(
                db.scalars(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "mmaudio_effects")
                )
            )


def test_effects_goal_prepares_only_the_description_preserving_film_and_scene_timings(
    sound_bridge, monkeypatch
):
    import json

    async def stream(self, messages, **kwargs):
        yield json.dumps({"description": "Soft wind through the trees."})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        source = source_video(api)
        cues = [{"start_frame": 0, "end_frame": 24, "prompt": "A single bird call"}]
        agent = create(
            api,
            model="fake-local",
            media={
                "kind": "effects",
                "description_source": "goal",
                "request": {
                    "video_artifact_id": source,
                    "prompt": "Write sounds from the goal",
                    "cues": cues,
                    "seed": 42,
                },
            },
        )
        root = start(api, agent)
        with control_session_factory()() as db:
            drain(db)
            outputs = list(db.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(r.status == "succeeded" for r in outputs), [
                (r.executor_type, r.error_message) for r in outputs
            ]
            sound = next(r for r in outputs if r.executor_type == "mmaudio_effects")
            assert sound.parameters["prompt"] == "Soft wind through the trees."
            assert sound.parameters["cues"] == cues and sound.parameters["video_artifact_id"] == source
            assert sound.parameters["seed"] == 42
