"""Temporary DB/fake generators test whole-film coordination, not film quality."""

import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.artifacts import register_file
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Run
from app.recovery import recover_stale
from app.runs import claim_next, create_run, create_task, transition
from app.state import TERMINAL, RunStatus
from app.studio_production import NAME, children
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_studio_audio_production import generators as generators
from test_studio_render import draft
from test_studio_render import ready as ready


class FakeVisual:
    def execute(self, session, run):
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        with tempfile.NamedTemporaryFile(suffix=".png") as source:
            Image.new("RGB", (32, 32), "blue").save(source.name)
            register_file(
                session,
                source=Path(source.name),
                artifact_type="image",
                mime_type="image/png",
                original_filename="synthetic.png",
                run_id=run.id,
            )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class FakeRender:
    def execute(self, session, run):
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        with tempfile.NamedTemporaryFile(suffix=".mp4") as source:
            source.write(b"synthetic renderer result; not a playable/qualified film")
            source.flush()
            register_file(
                session,
                source=Path(source.name),
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="synthetic.mp4",
                run_id=run.id,
            )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


@pytest.fixture
def movie(generators, ready):
    return {**generators[2], "photo_pipe": FakeVisual(), "motion_render": FakeRender()}


def produce(api, row, revision, **extra):
    return api.post(
        f"/api/studio/materials/{row['id']}/produce",
        json={"client_request_id": str(uuid4()), "revision_id": revision["id"], **extra},
    )


def advance(executors, count=80):
    with session_factory()() as db:
        for _ in range(count):
            if tick(db, "studio-whole-film", executors=executors) is None:
                break


def details(api, row):
    response = api.get(f"/api/studio/materials/{row['id']}/productions")
    assert response.status_code == 200, response.text
    return response.json()[0]


def test_one_request_produces_measured_audio_before_visuals_and_final_export(movie, generators):
    with TestClient(app) as api:
        row, revision = draft(api, audio="voice_music")
        nonce = str(uuid4())
        submitted = produce(api, row, revision, client_request_id=nonce)
        assert submitted.status_code == 202, submitted.text
        root = submitted.json()
        assert root["executor_type"] == NAME and not generators[0] and not generators[1]
        assert produce(api, row, revision, client_request_id=nonce).json()["id"] == root["id"]
        assert produce(api, row, revision).status_code == 409
        advance(movie)
        result = details(api, row)
        assert result["status"] == "succeeded", result
        assert result["output"]["type"] == "video"
        assert result["measured_revision_id"] != revision["id"]
        assert len(generators[0]) == len(generators[1]) == 1
        with session_factory()() as db:
            pipeline = db.get(Run, root["id"])
            kids = children(db, pipeline)
            assert len(kids) == 3 and len({t.id for t in kids}) == 3
            shot = next(r for r in db.scalars(select(Run)) if "studio_shot" in r.parameters)
            mix = db.scalar(select(Run).where(Run.executor_type == "studio_soundtrack"))
            render = db.scalar(select(Run).where(Run.executor_type == "motion_render"))
            assert mix.finished_at <= shot.created_at and shot.finished_at <= render.created_at
            assert render.parameters["composition"]["scenes"][0]["duration_frames"] > 30
            assert all(r.status == "succeeded" for r in db.scalars(select(Run)))


def test_explicit_completed_take_is_reused_without_generating_a_duplicate(movie, generators):
    with TestClient(app) as api:
        row, revision = draft(api)
        source, _ = upload(api, "blue")
        response = produce(api, row, revision, bindings=[{"scene": 0, "artifact_id": source}])
        assert response.status_code == 202, response.text
        advance(movie)
        result = details(api, row)
        assert result["status"] == "succeeded", result
        assert not generators[0] and not generators[1]
        assert all("studio_shot" not in r["parameters"] for r in result["runs"])
        with session_factory()() as db:
            render = db.scalar(select(Run).where(Run.executor_type == "motion_render"))
            assert render.parameters["bindings"] == [{"scene": 0, "artifact_id": source}]


def test_retry_reuses_finished_audio_and_shots_after_export_failure(movie, generators):
    class FailedRender:
        def execute(self, session, run):
            raise ValueError("Synthetic renderer failure")

    with TestClient(app) as api:
        row, revision = draft(api, audio="voice_music")
        first = produce(api, row, revision).json()
        advance({**movie, "motion_render": FailedRender()})
        failed = details(api, row)
        assert failed["status"] == "failed" and failed["output"] is None
        assert len(generators[0]) == len(generators[1]) == 1
        second = produce(api, row, revision, reuse_from_run_id=first["id"])
        assert second.status_code == 202, second.text
        advance(movie)
        result = details(api, row)
        assert result["status"] == "succeeded", result
        assert len(generators[0]) == len(generators[1]) == 1
        assert not any(r["executor_type"] == "photo_pipe" for r in result["runs"])


def test_whole_production_stop_forwards_only_to_its_owned_child_tasks(movie):
    with TestClient(app) as api:
        row, revision = draft(api, audio="voice_music")
        first = produce(api, row, revision).json()
        advance(movie, count=1)
        with session_factory()() as db:
            unrelated = create_task(db, title="unrelated", prompt="unrelated", capability="test")
            untouched = create_run(db, unrelated, run_type="test", capability="test", executor_type="fake")
            unrelated_id = untouched.id
            db.commit()
        stopped = api.post(f"/api/studio/materials/{row['id']}/productions/{first['id']}/stop")
        assert stopped.status_code == 200, stopped.text
        with session_factory()() as db:
            assert db.get(Run, unrelated_id).status == "queued"
            root = db.get(Run, first["id"])
            assert all(t.metadata_json.get("stop_requested_at") for t in children(db, root))
            own = [root.task_id] + [t.id for t in children(db, root)]
            assert all(r.status in TERMINAL for r in db.scalars(select(Run).where(Run.task_id.in_(own))))
        assert details(api, row)["status"] == "canceled"


def test_stale_sql_only_coordinator_recovers_without_duplicate_child_tasks(movie):
    with TestClient(app) as api:
        row, revision = draft(api)
        first = produce(api, row, revision).json()
        with session_factory()() as db:
            run = claim_next(db, "lost-studio-worker")
            assert run.id == first["id"]
            transition(db, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(db, run, RunStatus.RUNNING, event_type="executor.started")
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
            assert first["id"] in recover_stale(db)
            db.commit()
            assert db.get(Run, first["id"]).status == "queued"
        advance(movie)
        assert details(api, row)["status"] == "succeeded"
        with session_factory()() as db:
            assert len(children(db, db.get(Run, first["id"]))) == 2


def test_cross_account_production_reuse_and_stop_are_invisible(accounts, movie):
    owner, other, _ = accounts
    row, revision = draft(owner)
    submitted = produce(owner, row, revision)
    assert submitted.status_code == 202, submitted.text
    root = submitted.json()
    assert other.get(f"/api/studio/materials/{row['id']}/productions").status_code == 404
    assert other.post(f"/api/studio/materials/{row['id']}/productions/{root['id']}/stop").status_code == 404
    assert produce(other, row, revision).status_code == 404


def test_missing_renderer_blocks_costly_work_before_enqueue(monkeypatch, movie, generators):
    monkeypatch.setattr(
        "app.studio_render.capabilities", lambda: {"available": False, "reason": "Not prepared"}
    )
    with TestClient(app) as api:
        row, revision = draft(api)
        result = produce(api, row, revision)
        assert result.status_code == 409 and not generators[0]
        with session_factory()() as db:
            assert not list(db.scalars(select(Run).where(Run.executor_type == NAME)))


@pytest.mark.parametrize("damaged_source", [False, True])
def test_retry_of_partial_audio_reuses_completed_spoken_cues(movie, generators, damaged_source):
    from test_studio_audio_production import FakeAudio, two_shots

    class FailSecondCue:
        def execute(self, session, run):
            if "next piece" in run.parameters["text"]:
                raise ValueError("Synthetic second cue failure")
            return FakeAudio().execute(session, run)

    with TestClient(app) as api:
        row, revision = two_shots(api)
        first = produce(api, row, revision)
        assert first.status_code == 202, first.text
        advance({**movie, "synthetic_speech": FailSecondCue()})
        assert details(api, row)["status"] == "failed"
        assert len(generators[0]) == 2 and len(generators[1]) == 0
        if damaged_source:
            from app.config import get_settings
            from app.models import Artifact

            with session_factory()() as db:
                spoken = db.scalar(
                    select(Artifact)
                    .join(Run, Run.id == Artifact.run_id)
                    .where(Run.executor_type == "synthetic_speech", Run.status == "succeeded")
                )
                path = get_settings().data_dir / spoken.relative_path
                data = bytearray(path.read_bytes())
                data[-1] ^= 1
                path.write_bytes(data)
        second = produce(api, row, revision, reuse_from_run_id=first.json()["id"])
        assert second.status_code == 202, second.text
        advance(movie)
        result = details(api, row)
        if damaged_source:
            assert result["status"] == "failed", result
            assert len(generators[0]) == 2 and len(generators[1]) == 0
            return
        assert result["status"] == "succeeded", result
        assert len(generators[0]) == 3 and len(generators[1]) == 1
        assert generators[0][-1]["reference_artifact_id"] is not None


def test_multiple_video_shots_keep_separate_real_segment_plans(movie, monkeypatch):
    from app.models import Artifact

    monkeypatch.setattr(
        "app.video_models.profile_for", lambda *a: {"available": True, "memory_estimate_mib": 16384}
    )
    with TestClient(app) as api:
        row, revision = draft(api, kind="video")
        value = revision["storyboard"]
        value["scenes"].append(
            {**value["scenes"][0], "visual_brief": "A different concrete visual in the same story."}
        )
        saved = api.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": revision["id"],
                "storyboard": value,
            },
        )
        assert saved.status_code == 201, saved.text
        submitted = produce(api, row, saved.json())
        assert submitted.status_code == 202, submitted.text
        identity = submitted.json()["id"]
        for scene in range(2):
            # Only the real SQL publisher executes. Native video results are faked.
            advance(movie, count=1)
            with session_factory()() as db:
                root = db.get(Run, identity)
                task = children(db, root)[scene]
                primary = db.get(Run, root.metadata_json["child_tasks"][scene]["run_id"])
                assert primary.executor_type == "media_compose"
                assert primary.parameters["studio_scene"] == scene
                assert task.metadata_json["media_plan"]
                for child in db.scalars(select(Run).where(Run.task_id == task.id)):
                    child.status = "succeeded"
                    child.finished_at = utcnow()
                with tempfile.NamedTemporaryFile(suffix=".mp4") as source:
                    source.write(b"synthetic completed footage, no actual video inference")
                    source.flush()
                    register_file(
                        db,
                        source=Path(source.name),
                        artifact_type="video",
                        mime_type="video/mp4",
                        original_filename="synthetic.mp4",
                        run_id=primary.id,
                    )
                db.commit()
        advance(movie, count=1)
        with session_factory()() as db:
            root = db.get(Run, identity)
            tasks = children(db, root)
            assert len(tasks) == 3 and len({t.id for t in tasks}) == 3
            films = tasks[:2]
            assert (
                films[0].metadata_json["media_plan"]["request"]["prompt"]
                != films[1].metadata_json["media_plan"]["request"]["prompt"]
            )
            assert db.scalar(select(Artifact.id).where(Artifact.run_id == root.id)) is None
            assert db.get(Run, root.metadata_json["render_run_id"]).executor_type == "motion_render"


def test_coordinator_cannot_be_cloned_into_another_task(movie):
    from app.studio_production import StudioProductionExecutor

    with TestClient(app) as api:
        row, revision = draft(api)
        first = produce(api, row, revision).json()
        with session_factory()() as db:
            root = db.get(Run, first["id"])
            task = create_task(db, title="synthetic orphan", prompt="test", capability="studio.produce")
            orphan = create_run(
                db,
                task,
                run_type="planning",
                capability="studio.produce",
                executor_type=NAME,
                parameters={"studio_production_root_id": root.id},
                permissions=["filesystem_read", "workspace_write"],
            )
            transition(db, orphan, RunStatus.CLAIMED, event_type="run.claimed")
            with pytest.raises(ValueError, match="cannot move to another Task"):
                StudioProductionExecutor().execute(db, orphan)
            assert children(db, root) == []
            db.rollback()
