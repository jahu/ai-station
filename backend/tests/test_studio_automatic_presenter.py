import copy
import io
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import app
from app.artifacts import register_file
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.recovery import recover_stale
from app.runs import transition
from app.state import RunStatus
from app.studio_materials import source_snapshot
from app.studio_production import children
from app.studio_render import StudioRenderExecutor, native_request
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_assistant_controller import submit as submit_chat
from test_studio_assistant import advance as advance_chat
from test_studio_assistant import director as director
from test_studio_assistant import owned as owned_chat
from test_studio_audio_production import generators as generators
from test_studio_production import FakeRender, advance, details, produce
from test_studio_production import movie as movie
from test_studio_render import draft
from test_studio_render import ready as ready

PROFILE = {
    "available": True,
    "backend": "sonic",
    "recipe": {"id": "sonic_whole_768_v1", "observation": "c" * 64},
    "ram_mib": 18432,
    "max_side": 768,
    "max_pixels": 512 * 768,
    "fps": 25,
    "detected_gpu_count": 1,
}


class FakeAvatar:
    def __init__(self):
        self.calls = []

    def execute(self, session, run):
        self.calls.append(copy.deepcopy(run.parameters))
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        with tempfile.NamedTemporaryFile(suffix=".mp4") as file:
            file.write(b"synthetic complete avatar part; not native video qualification")
            file.flush()
            artifact = register_file(
                session,
                source=Path(file.name),
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="synthetic-avatar.mp4",
                run_id=run.id,
                parent_artifact_ids=[s["artifact_id"] for s in run.parameters["whole_inputs"]],
                metadata={"frames": run.parameters["observed_input"]["target_frames"], "fps": 25},
            )
        plan = run.task.metadata_json["media_plan"]
        assert plan["version"] == 2 and plan["whole_run_id"] == run.id
        run.task.metadata_json = {
            **run.task.metadata_json,
            "media_plan": {**plan, "final_artifact_id": artifact.id},
        }
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class CheckedRender(FakeRender):
    def __init__(self):
        self.requests = []

    def execute(self, session, run):
        StudioRenderExecutor().validate_inputs(session, run)
        self.requests.append(native_request(run))
        return super().execute(session, run)


@pytest.fixture
def presenter(movie, monkeypatch):
    monkeypatch.setattr(
        "app.studio_render.capabilities",
        lambda: {"available": True, "ram_mib": 4352, "observation": "a" * 64, "max_presenter_clips": 32},
    )
    monkeypatch.setattr(
        "app.studio_presenter.profile_for_request", lambda *args, **kwargs: copy.deepcopy(PROFILE)
    )
    monkeypatch.setattr(
        "app.avatar_models.profile_for_request", lambda *args, **kwargs: copy.deepcopy(PROFILE)
    )
    avatar, render = FakeAvatar(), CheckedRender()
    return {**movie, "sonic_whole": avatar, "motion_render": render}, avatar, render


def test_complete_production_uses_measured_speech_once_and_hides_verified_parts(presenter, generators):
    executors, avatar, renderer = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice_music")
        queued = produce(client, row, revision, presenter={"image_artifact_id": image})
        assert queued.status_code == 202, queued.text
        advance(executors)
        result = details(client, row)
        assert result["status"] == "succeeded", result.get("failed_run") and (
            result["failed_run"].get("error_type"),
            result["failed_run"].get("error_message"),
        )
        assert len(avatar.calls) == len(renderer.requests) == len(generators[0]) == len(generators[1]) == 1
        assert avatar.calls[0]["level_volume"] is False
        assert renderer.requests[0]["audio_artifact_id"]
        clips = renderer.requests[0]["composition"]["presenter"]["clips"]
        assert len(clips) == 1 and clips[0]["duration_frames"] == 252
        with session_factory()() as db:
            root = db.get(Run, queued.json()["id"])
            state = root.metadata_json["production_state"]
            portrait = db.get(Artifact, state["presenter_portrait"]["artifact_id"])
            assert portrait.mime_type == "image/png" and portrait.parent_artifact_ids == [image]
            assert state["soundtrack_id"] == renderer.requests[0]["audio_artifact_id"]
            for task in children(db, root):
                assert task.metadata_json["studio_production_root_id"] == root.id
            part = db.get(Artifact, clips[0]["media"])
            assert (
                part.metadata_json["internal_media"] and part.metadata_json["studio_role"] == "presenter_part"
            )
            with pytest.raises(ValueError):
                source_snapshot(db, part.id, complete=True)
            assert (
                source_snapshot(db, part.id, complete=True, internal_role="presenter_part")["kind"] == "video"
            )
        visible = client.get("/api/artifacts").json()
        assert clips[0]["media"] not in {a["id"] for a in visible}


def test_long_narration_drives_multiple_source_bound_parts_without_a_sixty_second_film_limit(presenter):
    executors, avatar, renderer = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        board = copy.deepcopy(revision["storyboard"])
        board["scenes"] = [
            {**board["scenes"][0], "duration_frames": 1350, "title": f"Part {i + 1}"} for i in range(3)
        ]
        saved = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": revision["id"],
                "storyboard": board,
            },
        )
        assert saved.status_code == 201, saved.text
        queued = produce(client, row, saved.json(), presenter={"image_artifact_id": image})
        assert queued.status_code == 202, queued.text
        advance(executors, count=120)
        result = details(client, row)
        assert result["status"] == "succeeded", result.get("failed_run") and (
            result["failed_run"].get("error_type"),
            result["failed_run"].get("error_message"),
        )
        assert len(avatar.calls) == 3
        assert len({c["whole_inputs"][0]["artifact_id"] for c in avatar.calls}) == 1
        assert len({c["whole_inputs"][1]["artifact_id"] for c in avatar.calls}) == 3
        assert [
            c["observed_input"]["samples"] / c["observed_input"]["sample_rate"] for c in avatar.calls
        ] == [45, 45, 45]
        clips = renderer.requests[0]["composition"]["presenter"]["clips"]
        assert sum(c["duration_frames"] for c in clips) == 4050


def test_retry_reuses_completed_presenter_and_does_not_repeat_speech_or_native_generation(
    presenter, generators
):
    executors, avatar, renderer = presenter

    class Broken:
        def execute(self, *args):
            raise ValueError("synthetic export failure")

    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice_music")
        settings = {"presenter": {"image_artifact_id": image}}
        first = produce(client, row, revision, **settings).json()
        advance({**executors, "motion_render": Broken()})
        assert details(client, row)["status"] == "failed"
        second = produce(client, row, revision, reuse_from_run_id=first["id"], **settings)
        assert second.status_code == 202, second.text
        advance(executors)
        result = details(client, row)
        assert result["status"] == "succeeded", result.get("failed_run") and (
            result["failed_run"].get("error_type"),
            result["failed_run"].get("error_message"),
        )
        assert len(avatar.calls) == len(generators[0]) == len(generators[1]) == 1


def test_stop_reaches_owned_avatar_task_and_blocks_a_later_render(presenter):
    executors, avatar, renderer = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        root = produce(client, row, revision, presenter={"image_artifact_id": image}).json()
        with session_factory()() as db:
            for _ in range(40):
                tick(db, "before-avatar", executors=executors)
                queued = db.scalar(
                    select(Run).where(Run.executor_type == "sonic_whole", Run.status == "queued")
                )
                if queued:
                    break
            else:
                pytest.fail("No avatar was queued")
            task_id = queued.task_id
        stopped = client.post(f"/api/studio/materials/{row['id']}/productions/{root['id']}/stop")
        assert stopped.status_code == 200, stopped.text
        advance(executors)
        assert not avatar.calls and not renderer.requests
        with session_factory()() as db:
            assert db.get(Run, queued.id).status == "canceled"
            assert db.get(Run, queued.id).task_id == task_id


def test_foreign_portrait_and_silent_policy_fail_before_media_work(presenter, accounts):
    _, alice, bob = accounts
    image, _ = upload(bob, "red")
    row, revision = draft(alice, audio="voice")
    assert produce(alice, row, revision, presenter={"image_artifact_id": image}).status_code == 422
    own, _ = upload(alice, "blue")
    silent, silent_revision = draft(alice)
    assert produce(alice, silent, silent_revision, presenter={"image_artifact_id": own}).status_code == 422


@pytest.mark.parametrize("unavailable", ["renderer", "avatar"])
def test_unavailable_presenter_capability_refuses_before_queuing_production(
    presenter, monkeypatch, unavailable
):
    _, avatar, renderer = presenter
    if unavailable == "renderer":
        monkeypatch.setattr("app.studio_render.capabilities", lambda: {"available": True})
    else:
        monkeypatch.setattr("app.studio_presenter.profile_for_request", lambda *args: {"available": False})
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        response = produce(client, row, revision, presenter={"image_artifact_id": image})
        assert response.status_code == 409, response.text
        assert client.get(f"/api/studio/materials/{row['id']}/productions").json() == []
        assert not avatar.calls and not renderer.requests


def test_webp_portrait_is_normalized_without_touching_the_original(presenter):
    executors, avatar, _ = presenter
    with TestClient(app) as client:
        raw = io.BytesIO()
        Image.new("RGB", (256, 320), "green").save(raw, "WEBP")
        source = client.post(
            "/api/images/uploads", files={"file": ("portrait.webp", raw.getvalue(), "image/webp")}
        )
        assert source.status_code == 201, source.text
        image = source.json()["id"]
        row, revision = draft(client, audio="voice")
        queued = produce(client, row, revision, presenter={"image_artifact_id": image})
        assert queued.status_code == 202, queued.text
        advance(executors)
        assert details(client, row)["status"] == "succeeded"
        assert avatar.calls[0]["whole_inputs"][0]["mime_type"] == "image/png"
        assert client.get("/api/artifacts/" + image + "/file").content == raw.getvalue()


def test_changed_portrait_fails_before_any_synthesis(presenter, generators):
    executors, avatar, _ = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        queued = produce(client, row, revision, presenter={"image_artifact_id": image})
        assert queued.status_code == 202
        with session_factory()() as db:
            item = db.get(Artifact, image)
            from app.config import get_settings

            (get_settings().data_dir / item.relative_path).write_bytes(b"changed portrait")
        advance(executors)
        assert details(client, row)["status"] == "failed"
        assert not generators[0] and not avatar.calls


def test_stale_observer_reuses_the_completed_avatar_instead_of_generating_it_again(presenter):
    executors, avatar, _ = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        root = produce(client, row, revision, presenter={"image_artifact_id": image}).json()
        with session_factory()() as db:
            for _ in range(40):
                tick(db, "before-observer", executors=executors)
                step = db.scalar(select(Run).where(Run.task_id == root["task_id"], Run.status == "queued"))
                if (
                    step
                    and (step.parameters.get("pending") or {}).get("kind") == "presenter"
                    and avatar.calls
                ):
                    break
            else:
                pytest.fail("No completed avatar observer was queued")
            for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(db, step, status, event_type="qa.fixture")
            step.worker_id, step.lease_expires_at = "gone", utcnow() - timedelta(seconds=1)
            db.commit()
            recover_stale(db)
            db.commit()
            assert step.status == "queued"
        advance(executors)
        result = details(client, row)
        assert result["status"] == "succeeded", result["failed_run"]
        assert len(avatar.calls) == 1


def test_uncertain_native_process_cannot_be_replayed_by_continuing_the_production(presenter):
    executors, avatar, _ = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        settings = {"presenter": {"image_artifact_id": image}}
        root = produce(client, row, revision, **settings).json()
        with session_factory()() as db:
            for _ in range(40):
                tick(db, "before-uncertain", executors=executors)
                child = db.scalar(
                    select(Run).where(Run.executor_type == "sonic_whole", Run.status == "queued")
                )
                if child:
                    break
            else:
                pytest.fail("No native avatar was queued")
            for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.INTERRUPTED):
                transition(db, child, status, event_type="qa.fixture")
            child.metadata_json = {**child.metadata_json, "dispatch_attempted": True}
            db.commit()
        advance(executors)
        denied = produce(client, row, revision, reuse_from_run_id=root["id"], **settings)
        assert denied.status_code == 409 and "may still be running" in denied.text
        assert not avatar.calls


def test_forged_internal_part_metadata_does_not_grant_rendering_authority(presenter):
    executors, _, _ = presenter
    with TestClient(app) as client:
        image, _ = upload(client, "red")
        row, revision = draft(client, audio="voice")
        queued = produce(client, row, revision, presenter={"image_artifact_id": image}).json()
        advance(executors)
        assert details(client, row)["status"] == "succeeded"
        with session_factory()() as db:
            root = db.get(Run, queued["id"])
            identity = root.metadata_json["production_state"]["presenter_parts"][0]["video"]["artifact_id"]
            item = db.get(Artifact, identity)
            item.metadata_json = {**item.metadata_json, "studio_production_root_id": str(uuid4())}
            db.commit()
            with pytest.raises(ValueError):
                source_snapshot(db, identity, complete=True, internal_role="presenter_part")


def test_real_react_preserves_presenter_alias_separately_from_broll_and_returns_only_final_film(
    accounts, director, presenter
):
    from app.assistant_controller import controller_results

    executors, avatar, renderer = presenter
    _, alice, _ = accounts
    image, _ = upload(alice, "red")
    director["studio"]["audio"] = "voice_music"
    director["outcome"] = {"reference_mode": "provided", "source_inputs": ["input:image:1"]}
    director["presenter_reference"] = "input:image:1"
    result = submit_chat(
        alice,
        "Create a film explaining a prism, with this portrait as its speaking presenter",
        image_artifact_ids=[image],
    )
    advance_chat(executors, count=140)
    with owned_chat(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded", [
            (r.executor_type, r.status, r.error_message) for r in db.scalars(select(Run))
        ]
        public = controller_results(db, root)
        assert len(public["artifacts"]) == 1 and public["artifacts"][0]["type"] == "video"
    assert len(avatar.calls) == len(renderer.requests) == 1
    assert director["plans"][0]["source_catalog"] == []
