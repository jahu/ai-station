import json
from dataclasses import replace
from datetime import timedelta

import pytest
from app.agent_schema import AgentSettings
from app.agent_tools import AGENT_TOOLS
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, Run
from app.resources import active_locks
from app.runner_client import RunnerClient
from app.schedule import scheduler_tick
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_images import bridge as bridge
from test_images import upload
from test_music import music_bridge as music_bridge


@pytest.fixture
def implemented_media(monkeypatch):
    # Explicit fixture selection keeps execution contract tests independent of
    # future registry readiness changes; native runtimes are always fakes here.
    monkeypatch.setitem(AGENT_TOOLS, "create_media", replace(AGENT_TOOLS["create_media"], operational=True))


def create(api, *, kind="music", request=None, **extra):
    response = api.post(
        "/api/agents",
        json={
            "name": "Create a local result",
            "goal": "Create the reviewed output",
            "enabled": True,
            "tools": ["create_media"],
            "media": {"kind": kind, "request": request or {"caption": "Calm piano", "duration_seconds": 10}},
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def start(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def drain(session):
    for _ in range(12):
        if tick(session, "agent-media-test") is None:
            return
    raise AssertionError("Media workflow did not drain")


def no_text_model(*args, **kwargs):
    raise AssertionError("A fixed media scope attempted text-model inference")


def test_fixed_music_agent_uses_existing_native_media_without_a_text_model(
    implemented_media, music_bridge, monkeypatch
):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        agent = create(api)
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert len(runs) == 3
            assert all(row.status == "succeeded" for row in runs), [
                (r.capability, r.status, r.error_message) for r in runs
            ]
            media = next(row for row in runs if row.capability == "audio.music")
            assert media.agent_id == agent["id"]
            preparation = session.get(Run, media.parent_run_id)
            assert preparation.executor_type == "agent_media" and preparation.parent_run_id == root["id"]
            assert (
                media.parameters["execution_deadline_at"] == preparation.parameters["execution_deadline_at"]
            )
            assert not active_locks(session)
        artifacts = api.get("/api/artifacts", params={"run_id": media.id}).json()
        assert len(artifacts) == 1 and artifacts[0]["metadata"]["duration_seconds"] == 10
        assert api.get("/api/agents/" + agent["id"]).json()["last_status"] == "succeeded"
        view = api.get("/api/runs/" + root["id"]).json()["workflow"]
        assert any(step["capability"] == "audio.music" for step in view["steps"])


def test_fixed_image_agent_reuses_photo_pipeline_and_library(implemented_media, bridge, monkeypatch):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    profile = bridge.get("/v1/photo/capabilities")
    assert profile.status_code == 200 and profile.json().get("available"), profile.text
    with TestClient(app) as api:
        agent = create(
            api,
            kind="image",
            request={
                "mode": "t2i",
                "prompt": "Quiet green landscape",
                "width": 256,
                "height": 256,
                "steps": 1,
            },
        )
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(row.status == "succeeded" for row in runs), [
                (r.capability, r.status, r.error_message) for r in runs
            ]
            media = next(row for row in runs if row.capability == "image.generate")
            assert media.agent_id == agent["id"] and media.parameters["execution_deadline_at"]
        artifact = api.get("/api/artifacts", params={"run_id": media.id}).json()[0]
        assert artifact["type"] == "image" and artifact["mime_type"] == "image/png"


def test_unconfigured_media_agent_cannot_be_enabled_or_launch_work(implemented_media):
    with TestClient(app) as api:
        response = api.post(
            "/api/agents",
            json={
                "name": "Unavailable engine",
                "goal": "Create a track",
                "enabled": True,
                "tools": ["create_media"],
                "media": {"kind": "music", "request": {"caption": "Piano"}},
            },
        )
        assert response.status_code == 409 and "unavailable" in response.text
        assert api.get("/api/runs").json() == []


def test_goal_description_uses_sources_and_corrects_extra_authority_without_changing_scope(
    implemented_media, music_bridge, monkeypatch
):
    requests = []

    async def describe(self, **kwargs):
        requests.append(kwargs)
        payload = json.loads(kwargs["messages"][1]["content"])
        assert payload["observations"][0]["tool"] == "system_snapshot"
        assert payload["execution"]["saved_schedule"]["planned_only"] is True
        assert payload["execution"]["saved_schedule"]["schedule_timezone"] == "America/New_York"
        assert payload["execution"]["timezone"] == "UTC"
        assert kwargs["json_output"] is True
        yield json.dumps(
            {"description": "Warm acoustic piano", **({"gpu": "0"} if len(requests) == 1 else {})}
        )

    monkeypatch.setattr(LocalChatProvider, "stream", describe)
    with TestClient(app) as api:
        agent = create(
            api,
            model="fake-local",
            tools=["system_snapshot", "create_media"],
            schedule_timezone="America/New_York",
            media={
                "kind": "music",
                "description_source": "goal",
                "request": {
                    "caption": "Compose something calm",
                    "duration_seconds": 10,
                    "seed": 42,
                    "gpu": "7",
                },
            },
        )
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            runs = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert all(row.status == "succeeded" for row in runs), [
                (r.capability, r.status, r.error_message) for r in runs
            ]
            media = next(row for row in runs if row.capability == "audio.music")
            assert media.parameters["caption"] == "Warm acoustic piano"
            assert media.parameters["duration_seconds"] == 10 and media.parameters["seed"] == 42
            assert media.requested_gpu == "7" and set(media.effective_permissions) == {
                "filesystem_read",
                "workspace_write",
            }
            preparation = session.get(Artifact, media.metadata_json["agent_media_preparation_id"])
            assert preparation.parent_artifact_ids
            assert session.get(Run, preparation.run_id).parameters["media_context_snapshot"][
                "source_artifacts"
            ]
            wave = session.scalar(
                select(Artifact).where(Artifact.run_id == media.id, Artifact.artifact_type == "audio")
            )
            assert preparation.id in wave.parent_artifact_ids
        assert len(requests) == 2


def test_scheduled_fixed_media_preserves_the_same_task_and_frozen_scope(implemented_media, music_bridge):
    with TestClient(app) as api:
        agent = create(api, trigger="interval", interval_seconds=60)
        with session_factory()() as session:
            row = session.get(Agent, agent["id"])
            row.next_run_at = utcnow() - timedelta(seconds=1)
            session.commit()
            scheduled = scheduler_tick(session)
            assert len(scheduled) == 1
            session.commit()
            root = session.scalar(
                select(Run).where(Run.agent_id == row.id, Run.executor_type == "agent_workflow")
            )
            assert root.id == scheduled[0]
            assert (
                root.triggered_by == "scheduler" and root.parameters["definition"]["media"]["kind"] == "music"
            )
            drain(session)
            media = session.scalar(
                select(Run).where(Run.task_id == root.task_id, Run.capability == "audio.music")
            )
            assert media and media.status == "succeeded" and media.triggered_by == "scheduler"
            assert row.next_run_at > utcnow()


def test_changed_frozen_definition_fails_before_media_dispatch(implemented_media, music_bridge):
    with TestClient(app) as api:
        agent = create(api)
        root = start(api, agent)
        with session_factory()() as session:
            assert tick(session, "publish-media-root") == root["id"]
            stored = session.get(Agent, agent["id"])
            stored.media = {**stored.media, "request": {**stored.media["request"], "caption": "Changed"}}
            session.commit()
            drain(session)
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                )
                is None
            )
            preparation = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert preparation.status == "failed" and "definition changed" in preparation.error_message


def test_parent_stop_cancels_queued_preparation_and_prevents_late_media(implemented_media, music_bridge):
    with TestClient(app) as api:
        agent = create(api)
        root = start(api, agent)
        with session_factory()() as session:
            assert tick(session, "publish-media") == root["id"]
        response = api.post(f"/api/runs/{root['id']}/cancel")
        assert response.status_code == 200, response.text
        with session_factory()() as session:
            drain(session)
            assert session.get(Run, root["id"]).task.metadata_json.get("stop_requested_at")
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                )
                is None
            )
            stage = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert stage.status == "canceled"


def test_parent_stop_reaches_already_launched_media_and_keeps_outputs_unpublished(
    implemented_media, music_bridge, monkeypatch
):
    original = RunnerClient.request
    with TestClient(app) as api:
        agent = create(api, request={"caption": "wait", "duration_seconds": 10})
        root = start(api, agent)

        def request(self, method, path, json=None):
            result = original(self, method, path, json)
            if path == "/v1/runs/music":
                canceled = api.post(f"/api/runs/{root['id']}/cancel")
                assert canceled.status_code == 200, canceled.text
            return result

        monkeypatch.setattr(RunnerClient, "request", request)
        with session_factory()() as session:
            drain(session)
            media = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
            )
            assert media.status == "canceled" and not active_locks(session)
        assert api.get("/api/artifacts", params={"run_id": media.id}).json() == []


def test_fixed_gated_media_does_not_load_the_unused_selected_language_model(
    implemented_media, music_bridge, monkeypatch
):
    import app.llama as llama

    monkeypatch.setattr(llama, "prepare_consumer", no_text_model)
    with TestClient(app) as api:
        agent = create(api, model="llamacpp:unused-choice", workflow_mode="gated")
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            preparation = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert preparation.status == "waiting_for_approval"
            preparation_id = preparation.id
        response = api.post(f"/api/runs/{preparation_id}/approval", json={"resolution": "granted"})
        assert response.status_code == 200, response.text
        with session_factory()() as session:
            drain(session)
            media = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
            )
            assert media.status == "succeeded"


@pytest.mark.parametrize("changed", ["permissions", "definition", "deadline", "parent", "inputs"])
def test_tampered_preparation_never_publishes_a_media_child(implemented_media, music_bridge, changed):
    with TestClient(app) as api:
        agent = create(api)
        root = start(api, agent)
        with session_factory()() as session:
            assert tick(session, "root-before-tamper") == root["id"]
            stage = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            parameters = json.loads(json.dumps(stage.parameters))
            if changed == "permissions":
                stage.effective_permissions = ["filesystem_read"]
            elif changed == "definition":
                parameters["definition"]["media"]["request"]["caption"] = "Unreviewed"
            elif changed == "deadline":
                parameters["execution_deadline_at"] = (utcnow() + timedelta(hours=2)).isoformat()
            elif changed == "parent":
                stage.parent_run_id = None
            else:
                parameters["media_inputs"] = [{"id": "invented"}]
            stage.parameters = parameters
            session.commit()
            drain(session)
            session.refresh(stage)
            assert stage.status == "failed", stage.error_message
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                )
                is None
            )


def test_reference_content_is_verified_against_its_queued_checksum(implemented_media, bridge):
    from app.config import get_settings

    with TestClient(app) as api:
        source = upload(api)
        agent = create(
            api,
            kind="image",
            request={"mode": "img2img", "edit_prompt": "New clothing", "input_artifact_ids": [source["id"]]},
        )
        root = start(api, agent)
        with session_factory()() as session:
            assert tick(session, "freeze-reference") == root["id"]
            artifact = session.get(Artifact, source["id"])
            path = get_settings().data_dir / artifact.relative_path
            content = path.read_bytes()
            path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
            drain(session)
            stage = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert stage.status == "failed" and "checksum" in stage.error_message
            assert (
                session.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.capability == "image.edit")
                )
                is None
            )


def test_media_publication_has_no_runner_io_and_replays_the_same_child(
    implemented_media, music_bridge, monkeypatch
):
    from app import agent_media

    inside = {"publication": False}
    original_publish, original_request = agent_media.publish_media, RunnerClient.request

    def publish(*args, **kwargs):
        inside["publication"] = True
        try:
            return original_publish(*args, **kwargs)
        finally:
            inside["publication"] = False

    def request(self, method, path, json=None):
        assert not inside["publication"], "Runner HTTP inside media publication"
        return original_request(self, method, path, json)

    monkeypatch.setattr(agent_media, "publish_media", publish)
    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as api:
        agent = create(api)
        root = start(api, agent)
        with session_factory()() as session:
            assert tick(session, "receipt-root") == root["id"]
            stage = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert tick(session, "receipt-stage") == stage.id
            session.refresh(stage)
            child = session.get(Run, stage.metadata_json["media_run_id"])
            scope = AgentSettings.model_validate(stage.parameters["definition"]).media
            profile = agent_media.require_profile(scope)
            replay = publish(
                session, stage, scope, profile, child.metadata_json["agent_media_preparation_id"]
            )
            assert replay.id == child.id
            assert (
                len(
                    list(
                        session.scalars(
                            select(Run).where(Run.task_id == root["task_id"], Run.capability == "audio.music")
                        )
                    )
                )
                == 1
            )


def test_tool_readiness_reports_each_engine_without_launching(implemented_media, music_bridge):
    with TestClient(app) as api:
        media = next(tool for tool in api.get("/api/agents/tools").json() if tool["name"] == "create_media")
        assert media["operational"] is True
        assert media["outputs"]["music"]["ready"] is True
        assert media["outputs"]["image"]["ready"] is False
        assert api.get("/api/runs").json() == []
