from uuid import uuid4

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.image_models import DefaultsWrite, change_default
from app.models import Artifact, Run
from app.state import RunStatus
from app.studio_shots import verify_shot_sources
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import accounts, private_app, upload  # noqa: F401
from test_studio_render import draft


def submit(client, row, revision, **extra):
    return client.post(
        f"/api/studio/materials/{row['id']}/shots",
        json={
            "client_request_id": str(uuid4()),
            "revision_id": revision["id"],
            "scene": 0,
            **extra,
        },
    )


def test_shot_receipt_uses_saved_direction_defaults_and_prevents_duplicate_active_work():
    with TestClient(app) as client:
        row, revision = draft(client)
        with session_factory()() as session:
            change_default(DefaultsWrite(revision=0, mode="t2i", choice="juggernaut"), session)
            session.commit()
        nonce = str(uuid4())
        first = submit(client, row, revision, client_request_id=nonce)
        assert first.status_code == 202, first.text
        run = first.json()
        assert run["parameters"]["backend"] == "juggernaut"
        assert run["parameters"]["prompt_style"] == "prompt"
        assert "A prism in a narrow beam of light" in run["parameters"]["prompt"]
        assert (run["parameters"]["width"], run["parameters"]["height"]) == (864, 1536)
        assert submit(client, row, revision, client_request_id=nonce).json()["id"] == run["id"]
        assert submit(client, row, revision).status_code == 409
        assert submit(client, row, revision, client_request_id=nonce, image_model="qwen").status_code == 409
        assert submit(client, row, revision, scene=1).status_code == 422


def test_regenerating_keeps_previous_takes_and_uses_explicit_model():
    with TestClient(app) as client:
        row, revision = draft(client)
        first = submit(client, row, revision).json()
        with session_factory()() as session:
            run = session.get(Run, first["id"])
            run.status = RunStatus.SUCCEEDED
            session.commit()
        second = submit(client, row, revision, image_model="juggernaut")
        assert second.status_code == 202, second.text
        assert second.json()["id"] != first["id"]
        assert second.json()["parameters"]["backend"] == "juggernaut"
        data = client.get(f"/api/studio/materials/{row['id']}/revisions/{revision['id']}/production").json()
        assert {r["id"] for r in data["runs"]} == {first["id"], second.json()["id"]}


def test_video_publishes_real_continuation_and_compose_runs_for_complete_coverage(monkeypatch):
    monkeypatch.setattr(
        "app.video_models.profile_for",
        lambda *a: {
            "available": True,
            "memory_estimate_mib": 16384,
        },
    )
    with TestClient(app) as client:
        row, revision = draft(client, kind="video")
        result = submit(client, row, revision)
        assert result.status_code == 202, result.text
        compose = result.json()
        assert compose["executor_type"] == "media_compose"
        with session_factory()() as session:
            children = list(session.scalars(select(Run).where(Run.task_id == compose["task_id"])))
            assert any(r.executor_type == "wan_video" for r in children)
            assert all(r.parameters["studio_revision_id"] == revision["id"] for r in children)
            assert all(
                r.parameters["execution_deadline_at"] == compose["parameters"]["execution_deadline_at"]
                for r in children
            )
            assert compose["parameters"]["timeline"]["target_frames"] >= 24
        assert submit(client, row, revision).status_code == 409
        assert submit(client, row, revision, image_model="qwen").status_code == 422


def test_generated_shot_reference_bytes_are_rechecked_before_dispatch():
    with TestClient(app) as client:
        image, _ = upload(client, "blue")
        row, revision = draft(client)
        revision["storyboard"]["scenes"][0]["reference_artifact_ids"] = [image]
        saved = client.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": revision["id"],
                "storyboard": revision["storyboard"],
            },
        ).json()
        queued = submit(client, row, saved, image_model="qwen")
        assert queued.status_code == 202, queued.text
        assert queued.json()["parameters"]["mode"] == "recompose"
        with session_factory()() as session:
            run = session.get(Run, queued.json()["id"])
            verify_shot_sources(session, run)
            source = session.get(Artifact, image)
            (get_settings().data_dir / source.relative_path).write_bytes(b"changed source")
            with pytest.raises(ValueError):
                verify_shot_sources(session, run)


def test_generation_and_production_views_are_private(accounts):  # noqa: F811
    admin, alice, bob = accounts
    row, revision = draft(alice)
    assert submit(alice, row, revision).status_code == 202
    for browser in (admin, bob):
        assert submit(browser, row, revision).status_code == 404
        assert (
            browser.get(
                f"/api/studio/materials/{row['id']}/revisions/{revision['id']}/production"
            ).status_code
            == 404
        )


def test_shot_stop_cancels_every_video_stage_without_touching_other_materials(monkeypatch):
    monkeypatch.setattr(
        "app.video_models.profile_for",
        lambda *a: {
            "available": True,
            "memory_estimate_mib": 16384,
        },
    )
    with TestClient(app) as client:
        row, revision = draft(client, kind="video")
        queued = submit(client, row, revision).json()
        other, other_revision = draft(client)
        unrelated = submit(client, other, other_revision).json()
        stopped = client.post(f"/api/studio/materials/{row['id']}/shots/{queued['id']}/stop")
        assert stopped.status_code == 200, stopped.text
        with session_factory()() as session:
            stages = list(session.scalars(select(Run).where(Run.task_id == queued["task_id"])))
            assert len(stages) >= 2 and all(r.status == "canceled" for r in stages)
            assert session.get(Run, unrelated["id"]).status == "queued"
        assert (
            client.post(f"/api/studio/materials/{other['id']}/shots/{queued['id']}/stop").status_code == 404
        )


def test_new_take_changes_repeatable_seed_while_a_retried_receipt_keeps_it():
    with TestClient(app) as client:
        row, revision = draft(client)
        nonce = str(uuid4())
        first = submit(client, row, revision, image_model="juggernaut", client_request_id=nonce).json()
        repeat = submit(client, row, revision, image_model="juggernaut", client_request_id=nonce).json()
        assert repeat["parameters"]["seed"] == first["parameters"]["seed"]
        with session_factory()() as session:
            run = session.get(Run, first["id"])
            run.status = RunStatus.FAILED
            session.commit()
        another = submit(client, row, revision, image_model="juggernaut").json()
        assert another["parameters"]["seed"] != first["parameters"]["seed"]
