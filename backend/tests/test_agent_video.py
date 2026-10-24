"""Persistent video uses the existing segmented pipeline and final composition."""

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from app import agent_media
from app.agent_drafts import Proposal, definition
from app.agent_media import publish_media
from app.agent_schema import AgentSettings
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, Notice, Run
from app.resources import active_locks
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_media import create, no_text_model, start
from test_media_jobs import bridge as bridge
from test_video import image


def settings(**patch):
    return {
        "prompt": "Quiet forest",
        "duration_seconds": 5,
        "width": 128,
        "height": 128,
        "steps": 4,
        "gpu": "7",
        **patch,
    }


def drain(session):
    for _ in range(40):
        if tick(session, "agent-video") is None:
            return
    raise AssertionError("Video workflow did not finish")


@pytest.mark.parametrize("mode", ["continuous", "shots"])
@pytest.mark.parametrize("runtime", [600, 7200])
def test_agent_video_finishes_only_with_a_complete_verified_film(bridge, monkeypatch, mode, runtime):
    monkeypatch.setattr(LocalChatProvider, "stream", no_text_model)
    with TestClient(app) as api:
        source = image(api)
        agent = create(
            api,
            kind="video",
            request=settings(
                image_artifact_id=source["id"],
                composition_mode=mode,
                **(
                    {
                        "scenes": [
                            {"prompt": "Morning", "duration_seconds": 2},
                            {"prompt": "Evening", "duration_seconds": 3},
                        ]
                    }
                    if mode == "shots"
                    else {}
                ),
            ),
            notification_policy={"on_success": True},
            maximum_runtime=runtime,
        )
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
            task = session.get(Run, root["id"]).task
            plan = task.metadata_json["media_plan"]
            compose = session.get(Run, plan["compose_run_id"])
            prep = session.get(Run, compose.parent_run_id)
            assert compose.operation_key == "agent-media:" + prep.id
            assert compose.status == "queued"
            assert not list(session.scalars(select(Notice)))
            budget = prep.parameters["execution_deadline_at"]
            assert (
                datetime.fromisoformat(budget) - session.get(Run, root["id"]).started_at
            ).total_seconds() == runtime
            for row in session.scalars(select(Run).where(Run.parent_run_id == prep.id)):
                assert row.parameters["execution_deadline_at"] == budget
                assert row.task_id == task.id and row.agent_id == agent["id"]
            drain(session)
            session.expire_all()
            runs = list(session.scalars(select(Run).where(Run.task_id == task.id)))
            assert all(r.status == "succeeded" for r in runs), [
                (r.capability, r.status, r.error_message) for r in runs
            ]
            session.commit()
            done = api.get("/api/media/jobs/" + task.id).json()
            assert done["status"] == "succeeded" and done["duration_seconds"] == 5
            output = session.get(Artifact, done["final_artifact_id"])
            assert output.run_id == compose.id and output.metadata_json["frames"] == 120
            assert len(output.parent_artifact_ids) == len(plan["segment_run_ids"])
            prep_json = session.get(Artifact, compose.metadata_json["agent_media_preparation_id"])
            for segment in session.scalars(
                select(Artifact).where(Artifact.id.in_(output.parent_artifact_ids))
            ):
                assert source["id"] in segment.parent_artifact_ids
                assert prep_json.id in segment.parent_artifact_ids
            notices = list(session.scalars(select(Notice)))
            assert len(notices) == 1 and notices[0].run_id == compose.id
            assert notices[0].title == "Agent media ready" and not active_locks(session)
            session.commit()
            assert api.get("/api/artifacts/" + output.id + "/file").headers["content-type"] == "video/mp4"


def test_video_publication_replays_without_runner_io_or_duplicate_segments(bridge, monkeypatch):
    original_publish = agent_media.publish_media

    def forbidden(*args, **kwargs):
        raise AssertionError("Publication attempted native HTTP")

    def checked_publication(*args, **kwargs):
        with monkeypatch.context() as scope:
            scope.setattr(RunnerClient, "request", forbidden)
            return original_publish(*args, **kwargs)

    monkeypatch.setattr(agent_media, "publish_media", checked_publication)
    with TestClient(app) as api:
        agent = create(api, kind="video", request=settings())
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
            prep = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            child = session.get(Run, prep.metadata_json["media_run_id"])
            count = session.query(Run).count()
            scope = AgentSettings.model_validate(prep.parameters["definition"]).media
            artifact_id = child.metadata_json["agent_media_preparation_id"]

            monkeypatch.setattr(RunnerClient, "request", forbidden)
            again = publish_media(session, prep, scope, {"available": True}, artifact_id)
            assert again.id == child.id and session.query(Run).count() == count


def test_goal_video_can_change_only_the_shared_prompt(bridge, monkeypatch):
    async def describe(self, messages, **kwargs):
        yield json.dumps({"description": "Sunlight moves across a quiet green forest"})

    monkeypatch.setattr(LocalChatProvider, "stream", describe)
    with TestClient(app) as api:
        agent = create(
            api,
            kind="video",
            request=settings(),
            model="fake-local",
            media={"kind": "video", "description_source": "goal", "request": settings()},
        )
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            rows = list(
                session.scalars(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "wan_video")
                )
            )
            assert rows and all(r.status == "succeeded" for r in rows)
            assert all(r.parameters["prompt"] == "Sunlight moves across a quiet green forest" for r in rows)
            assert all(
                r.parameters["width"] == 128 and r.parameters["steps"] == 4 and r.requested_gpu == "7"
                for r in rows
            )
            task = rows[0].task
            assert task.metadata_json["media_plan"]["timing"]["target_frames"] == 120


@pytest.mark.parametrize("stop_after_publication", [False, True])
def test_task_stop_prevents_queued_film_stages_from_being_dispatched(bridge, stop_after_publication):
    with TestClient(app) as api:
        agent = create(api, kind="video", request=settings())
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            if stop_after_publication:
                tick(session, "prepare")
            assert api.post("/api/runs/" + root["id"] + "/cancel").status_code == 200
            drain(session)
            rows = list(session.scalars(select(Run).where(Run.task_id == root["task_id"])))
            assert not any(r.metadata_json.get("dispatch_attempted") for r in rows)
            assert not active_locks(session) and not bridge


def test_changed_first_frame_blocks_video_before_publication(bridge):
    with TestClient(app) as api:
        source = image(api)
        agent = create(api, kind="video", request=settings(image_artifact_id=source["id"]))
        root = start(api, agent)
        with session_factory()() as session:
            artifact = session.get(Artifact, source["id"])
            from app.config import get_settings

            (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed source")
            drain(session)
            prep = session.scalar(
                select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "agent_media")
            )
            assert prep.status == "failed"
            assert not list(session.scalars(select(Run).where(Run.executor_type == "wan_video")))


def test_expired_video_budget_never_dispatches_and_agent_resume_cannot_extend_it(bridge):
    with TestClient(app) as api:
        agent = create(api, kind="video", request=settings())
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
            task = session.get(Run, root["id"]).task
            for row in session.scalars(
                select(Run).where(
                    Run.task_id == task.id, Run.executor_type.in_(["wan_video", "media_compose"])
                )
            ):
                row.parameters = {
                    **row.parameters,
                    "execution_deadline_at": (utcnow() - timedelta(seconds=1)).isoformat(),
                }
            session.commit()
            drain(session)
            assert not bridge and not active_locks(session)
            session.commit()
            response = api.post(
                "/api/media/jobs/" + task.id + "/resume",
                json={"client_request_id": str(uuid4()), "expected_revision": 1},
            )
            assert response.status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"frames": 81},
        {"client_request_id": str(uuid4())},
        {"duration_seconds": 61},
        {"composition_mode": "shots", "scenes": [{"prompt": "A", "duration_seconds": 1}]},
    ],
)
def test_video_scopes_reject_extra_identity_short_frames_or_conflicting_timing(change):
    with pytest.raises(ValueError):
        AgentSettings(
            name="Film",
            goal="Film",
            tools=["create_media"],
            media={"kind": "video", "request": settings(**change)},
        )


def test_video_proposal_does_not_invent_a_first_frame():
    proposal = Proposal(
        name="Film",
        goal="Film",
        tools=["create_media"],
        media={"kind": "video", "request": settings(image_artifact_id=uuid4())},
    )
    with pytest.raises(ValueError, match="invent"):
        definition(proposal, "Make a film", "fake-local")


def test_task_stop_reaches_the_running_owned_video_and_its_queued_dependents(bridge, monkeypatch):
    import sys
    import threading
    import time

    from ai_station_runner import app as host_app

    def sleeping_video(manager, body):
        return manager.start(
            run_id=str(body.run_id),
            argv=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=host_app.get_settings().host_data_dir(),
            executor="wan_video",
            deadline_at=body.deadline_at,
        )

    monkeypatch.setattr(host_app, "start_video", sleeping_video)
    with TestClient(app) as api:
        agent = create(api, kind="video", request=settings())
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
        errors = []

        def execute():
            try:
                with session_factory()() as session:
                    tick(session, "running-agent-video")
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=execute)
        worker.start()
        until = time.monotonic() + 8
        while True:
            with session_factory()() as session:
                active = session.scalar(
                    select(Run).where(
                        Run.task_id == root["task_id"],
                        Run.status == "running",
                        Run.executor_type == "wan_video",
                    )
                )
                active_id = active.id if active else None
            if active_id:
                break
            assert time.monotonic() < until
            time.sleep(0.02)
        response = api.post("/api/runs/" + root["id"] + "/cancel")
        assert response.status_code == 200
        worker.join(timeout=10)
        assert not worker.is_alive() and not errors
        with session_factory()() as session:
            drain(session)
            rows = list(
                session.scalars(
                    select(Run).where(
                        Run.task_id == root["task_id"], Run.executor_type.in_(["wan_video", "media_compose"])
                    )
                )
            )
            assert rows and all(row.status == "canceled" for row in rows)
            assert not active_locks(session)
        assert not host_app.manager().inspect(active_id)["alive"]


def test_failed_video_stage_never_publishes_a_finished_film_notice(bridge, monkeypatch):
    import sys

    from ai_station_runner import app as host_app

    def failing_video(manager, body):
        return manager.start(
            run_id=str(body.run_id),
            argv=[sys.executable, "-c", "raise SystemExit(3)"],
            cwd=host_app.get_settings().host_data_dir(),
            executor="wan_video",
            deadline_at=body.deadline_at,
        )

    monkeypatch.setattr(host_app, "start_video", failing_video)
    with TestClient(app) as api:
        agent = create(
            api,
            kind="video",
            request=settings(),
            notification_policy={"on_success": True, "on_failure": True},
        )
        root = start(api, agent)
        with session_factory()() as session:
            drain(session)
            task = session.get(Run, root["id"]).task
            compose = session.get(Run, task.metadata_json["media_plan"]["compose_run_id"])
            assert compose.status in {"failed", "canceled", "interrupted"} and not active_locks(session)
            assert not session.scalar(select(Artifact).where(Artifact.run_id == compose.id))
            notices = list(session.scalars(select(Notice)))
            assert notices and not any(notice.kind == "succeeded" for notice in notices)


@pytest.mark.parametrize("change", ["bytes", "trash", "record"])
def test_queued_video_rechecks_its_first_frame_before_each_gpu_dispatch(bridge, change):
    from app.config import get_settings

    with TestClient(app) as api:
        source = image(api)
        agent = create(api, kind="video", request=settings(image_artifact_id=source["id"]))
        root = start(api, agent)
        with session_factory()() as session:
            tick(session, "parent")
            tick(session, "prepare")
            artifact = session.get(Artifact, source["id"])
            if change == "bytes":
                (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed after publication")
            elif change == "trash":
                artifact.trashed_at = utcnow()
            else:
                artifact.sha256 = "0" * 64
            session.commit()
            drain(session)
            rows = list(
                session.scalars(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "wan_video")
                )
            )
            assert rows and all(row.status in {"failed", "canceled"} for row in rows)
            assert not bridge and not active_locks(session)
