"""Avatar agents use ordinary speech, whole-audio segments and final assembly."""

import json
from uuid import uuid4

import pytest
from ai_station_runner import avatars as native_avatar
from app.agent_drafts import Proposal, definition
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Notice, Run
from app.resources import active_locks
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, no_text_model, start
from test_media_jobs import avatar_sources
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge


@pytest.fixture
def avatar_agent_runtime(full_avatar_bridge, monkeypatch):
    # Real native installation/readiness is tested separately. No GPU model is used.
    monkeypatch.setattr(native_avatar, "capabilities", lambda: {"available": True, "backend": "echomimic-v3"})
    yield full_avatar_bridge


def settings(api, *, generated=True):
    sources = avatar_sources(api)
    return {key: value for key, value in sources.items() if key != "client_request_id"} | {
        "speech_text": "Dzień dobry." if generated else None,
        "prompt": "A person speaking naturally.",
        "gpu": "7",
    }


def drain(session):
    for _ in range(30):
        if tick(session, "agent-avatar") is None:
            return
    raise AssertionError("Avatar workflow did not finish")


@pytest.mark.parametrize("generated", [True, False])
def test_avatar_agent_returns_the_entire_verified_video_and_only_final_ready_notice(
    avatar_agent_runtime, monkeypatch, generated
):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        inputs = settings(api, generated=generated)
        agent = create(api, kind="avatar", request=inputs, notification_policy={"on_success": True})
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "preparation")
            task = session.get(Run, root["id"]).task
            plan = task.metadata_json["media_plan"]
            if generated:
                assert plan["timing"] is None
                prep_child = session.get(Run, plan["planner_run_id"])
                assert prep_child.operation_key.startswith("agent-media:")
                assert not list(session.scalars(select(Notice)))
            drain(session)
            rows = list(session.scalars(select(Run).where(Run.task_id == task.id)))
            assert all(row.status == "succeeded" for row in rows), [
                (row.capability, row.status, row.error_message) for row in rows
            ]
            prep = next(row for row in rows if row.executor_type == "agent_media")
            final = session.get(Run, task.metadata_json["media_plan"]["compose_run_id"])
            artifact = session.scalar(
                select(Artifact).where(Artifact.run_id == final.id, Artifact.artifact_type == "video")
            )
            assert artifact and artifact.metadata_json["verified"] and artifact.metadata_json["frames"] == 125
            assert final.agent_id == agent["id"] and final.parent_run_id
            budget = prep.parameters["execution_deadline_at"]
            assert all(
                row.parameters["execution_deadline_at"] == budget
                for row in rows
                if row.executor_type != "agent_workflow"
            )
            notices = list(session.scalars(select(Notice)))
            assert len(notices) == 1 and notices[0].run_id == final.id
            assert not active_locks(session)
            if generated:
                speech = next(row for row in rows if row.executor_type == "chatterbox")
                sound = session.scalar(
                    select(Artifact).where(Artifact.run_id == speech.id, Artifact.artifact_type == "audio")
                )
                assert inputs["audio_artifact_id"] in sound.parent_artifact_ids
                assert sound.id in artifact.parent_artifact_ids
                assert all(
                    any(item["id"] == sound.id for item in row.parameters["media_inputs"])
                    for row in rows
                    if row.executor_type == "echomimic"
                )
            tid = task.id
        view = api.get("/api/media/jobs/" + tid).json()
        assert view["status"] == "succeeded" and view["duration_seconds"] == 5


def test_goal_avatar_prepares_words_without_changing_portrait_voice_or_motion(
    avatar_agent_runtime, monkeypatch
):
    async def words(self, messages, **kwargs):
        assert "exact Polish text" in messages[0]["content"]
        yield json.dumps({"description": "Dzień dobry. To Twój dzisiejszy komunikat."})

    monkeypatch.setattr(LocalChatProvider, "stream", words)
    with TestClient(app) as api:
        body = settings(api)
        agent = create(
            api,
            kind="avatar",
            request=body,
            model="fake-local",
            media={"kind": "avatar", "request": body, "description_source": "goal"},
        )
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            speech = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "chatterbox")
            )
            assert speech and speech.status == "succeeded"
            assert speech.parameters["text"] == "Dzień dobry. To Twój dzisiejszy komunikat."
            prep = session.get(Run, speech.parent_run_id)
            assert prep.parameters["definition"]["media"]["request"] == body | {
                "size": 256,
                "steps": 4,
                "seed": 43,
            }
            video = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "echomimic")
            )
            assert video.parameters["prompt"] == body["prompt"] and video.requested_gpu == "7"


def test_pending_avatar_draft_can_save_but_cannot_enable_without_both_sources():
    with TestClient(app) as api:
        body = {
            "name": "Avatar",
            "goal": "Read a welcome",
            "tools": ["create_media"],
            "media": {
                "kind": "avatar",
                "description_source": "goal",
                "request": {"speech_text": "Read a short welcome"},
            },
        }
        response = api.post("/api/agents", json=body)
        assert response.status_code == 201, response.text
        agent = response.json()
        response = api.post(
            "/api/agents/" + agent["id"] + "/enabled",
            json={"enabled": True, "expected_updated_at": agent["updated_at"]},
        )
        assert response.status_code == 422
        assert not api.get("/api/runs").json()


@pytest.mark.parametrize("when", ["before_preparation", "before_speech", "before_planner", "before_segments"])
def test_stop_prevents_later_avatar_stages(avatar_agent_runtime, when):
    with TestClient(app) as api:
        agent = create(api, kind="avatar", request=settings(api))
        root = start(api, agent)
        count = {"before_preparation": 1, "before_speech": 2, "before_planner": 3, "before_segments": 4}[when]
        with session_factory()() as session:
            for _ in range(count):
                tick(session, "advance")
        response = api.post("/api/runs/" + root["id"] + "/cancel")
        assert response.status_code == 200
        with session_factory()() as session:
            drain(session)
            rows = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert not any(
                row.executor_type == "echomimic" and row.metadata_json.get("dispatch_attempted")
                for row in rows
            )
            assert not any(row.executor_type == "media_compose" and row.status == "succeeded" for row in rows)
            assert not active_locks(session)
        assert not avatar_agent_runtime


@pytest.mark.parametrize("kind", ["image_artifact_id", "audio_artifact_id"])
@pytest.mark.parametrize("change", ["bytes", "trash"])
def test_sources_changed_after_speech_block_avatar_publication(avatar_agent_runtime, kind, change):
    from app.config import get_settings

    with TestClient(app) as api:
        body = settings(api)
        agent = create(api, kind="avatar", request=body)
        root = start(api, agent)
        with session_factory()() as session:
            for _ in range(3):
                tick(session, "advance")
            source = session.get(Artifact, body[kind])
            if change == "bytes":
                (get_settings().data_dir / source.relative_path).write_bytes(b"modified source")
            else:
                source.trashed_at = utcnow()
            session.commit()
            drain(session)
            planner = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "avatar_media_plan")
            )
            assert planner.status == "failed"
            assert not list(session.scalars(select(Run).where(Run.executor_type == "echomimic")))
        assert not avatar_agent_runtime


def test_avatar_drafting_cannot_invent_source_ids():
    proposal = Proposal(
        name="Avatar",
        goal="Speak",
        tools=["create_media"],
        media={
            "kind": "avatar",
            "request": {"image_artifact_id": uuid4(), "audio_artifact_id": None, "speech_text": "Hi"},
        },
    )
    with pytest.raises(ValueError, match="invent"):
        definition(proposal, "Create an avatar", "fake-local")


@pytest.mark.parametrize("change", ["bytes", "trash"])
def test_generated_canonical_audio_is_rechecked_before_animation(avatar_agent_runtime, change):
    from app.config import get_settings

    with TestClient(app) as api:
        agent = create(api, kind="avatar", request=settings(api))
        root = start(api, agent)
        with session_factory()() as session:
            for _ in range(4):
                tick(session, "advance")
            sound = session.scalar(
                select(Artifact)
                .join(Run, Run.id == Artifact.run_id)
                .where(
                    Run.task_id == root["task_id"],
                    Run.executor_type == "chatterbox",
                    Artifact.artifact_type == "audio",
                )
            )
            if change == "bytes":
                (get_settings().data_dir / sound.relative_path).write_bytes(b"modified canonical audio")
            else:
                sound.trashed_at = utcnow()
            session.commit()
            drain(session)
            rows = list(
                session.scalars(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "echomimic")
                )
            )
            assert rows and all(row.status in {"failed", "canceled"} for row in rows)
            assert not active_locks(session)
        assert not avatar_agent_runtime


def test_avatar_preparation_publication_and_replay_have_no_native_http(avatar_agent_runtime, monkeypatch):
    from app import agent_media
    from app.agent_schema import AgentSettings
    from app.runner_client import RunnerClient

    original = agent_media.publish_media

    def forbidden(*args, **kwargs):
        raise AssertionError("Native HTTP inside publication")

    def checked(*args, **kwargs):
        with monkeypatch.context() as patch:
            patch.setattr(RunnerClient, "request", forbidden)
            return original(*args, **kwargs)

    monkeypatch.setattr(agent_media, "publish_media", checked)
    with TestClient(app) as api:
        agent = create(api, kind="avatar", request=settings(api))
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
            prep = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            child = session.get(Run, prep.metadata_json["media_run_id"])
            artifact_id = child.metadata_json["agent_media_preparation_id"]
            scope = AgentSettings.model_validate(prep.parameters["definition"]).media
            before = session.query(Run).count()
            assert checked(session, prep, scope, {}, artifact_id).id == child.id
            assert session.query(Run).count() == before
            session.commit()
            drain(session)
            after = session.query(Run).count()
            assert checked(session, prep, scope, {}, artifact_id).id == child.id
            assert session.query(Run).count() == after


def test_stop_reaches_a_running_avatar_and_queued_composition(avatar_agent_runtime, monkeypatch):
    import sys
    import threading
    import time

    from ai_station_runner import app as host_app

    def sleeping(manager, body):
        return manager.start(
            run_id=str(body.run_id),
            argv=[sys.executable, "-c", "import time;time.sleep(30)"],
            cwd=host_app.get_settings().host_data_dir(),
            executor="echomimic",
            deadline_at=body.deadline_at,
        )

    monkeypatch.setattr(host_app, "start_avatar", sleeping)
    with TestClient(app) as api:
        agent = create(api, kind="avatar", request=settings(api))
        root = start(api, agent)
        with session_factory()() as session:
            for _ in range(4):
                tick(session, "advance")
        errors = []

        def execute():
            try:
                with session_factory()() as session:
                    tick(session, "running-avatar")
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=execute)
        worker.start()
        until = time.monotonic() + 8
        while True:
            with session_factory()() as session:
                row = session.scalar(
                    select(Run).where(
                        Run.task_id == root["task_id"],
                        Run.executor_type == "echomimic",
                        Run.status == "running",
                    )
                )
                active = row.id if row else None
            if active:
                break
            assert time.monotonic() < until
            time.sleep(0.02)
        assert api.post("/api/runs/" + root["id"] + "/cancel").status_code == 200
        worker.join(timeout=10)
        assert not worker.is_alive() and not errors
        with session_factory()() as session:
            drain(session)
            rows = list(
                session.scalars(
                    select(Run).where(
                        Run.task_id == root["task_id"], Run.executor_type.in_(["echomimic", "media_compose"])
                    )
                )
            )
            assert rows and all(row.status == "canceled" for row in rows)
            assert not active_locks(session)
        assert not host_app.manager().inspect(active)["alive"]
