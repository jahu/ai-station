"""Owned renderer bindings reuse exact media, including clip trim coverage."""

from uuid import uuid4

from app.api import app
from app.db import session_factory
from app.models import Run
from fastapi.testclient import TestClient
from test_account_private_api import accounts, private_app, upload  # noqa: F401
from test_studio_render import draft, render
from test_studio_render import ready as ready
from test_studio_storyboard import shared, visual


def shared_plan(api, scenes):
    row, old = draft(api)
    response = api.post(
        f"/api/studio/materials/{row['id']}/revisions",
        json={
            "client_request_id": str(uuid4()),
            "expected_version": 2,
            "parent_revision_id": old["id"],
            "storyboard": {**old["storyboard"], "scenes": scenes},
        },
    )
    assert response.status_code == 201, response.text
    return row, response.json()


def test_export_shares_one_owned_image_but_keeps_independent_captions_and_motion(ready):
    with TestClient(app) as api:
        source, _ = upload(api, "blue")
        row, revision = shared_plan(
            api,
            [
                visual(),
                shared(0, title="A different caption", media_motion="pan_left"),
                shared(1, media_motion="pull_out"),
            ],
        )
        result = render(api, row, revision, source)
        assert result.status_code == 202, result.text
        composition = result.json()["parameters"]["composition"]
        assert [s["media"] for s in composition["scenes"]] == [source] * 3
        assert composition["scenes"][1]["title"] == "A different caption"
        assert composition["scenes"][2]["media_motion"] == "pull_out"
        assert len(result.json()["parameters"]["sources"]) == 1
        second, _ = upload(api, "red")
        mismatch = api.post(
            f"/api/studio/materials/{row['id']}/render",
            json={
                "client_request_id": str(uuid4()),
                "revision_id": revision["id"],
                "bindings": [{"scene": 0, "artifact_id": source}, {"scene": 1, "artifact_id": second}],
            },
        )
        assert mismatch.status_code == 422 and "shared scene" in mismatch.text
        generated = api.post(
            f"/api/studio/materials/{row['id']}/shots",
            json={"client_request_id": str(uuid4()), "revision_id": revision["id"], "scene": 1},
        )
        assert generated.status_code == 422 and "original source" in generated.text


def test_shared_library_source_resolves_without_a_fake_generated_take(ready):
    with TestClient(app) as api:
        source, _ = upload(api, "blue")
        row, revision = shared_plan(api, [visual(kind="library", source_artifact_id=source), shared(0)])
        result = render(api, row, revision)
        assert result.status_code == 202, result.text
        assert [s["media"] for s in result.json()["parameters"]["composition"]["scenes"]] == [source, source]


def test_generated_clip_budget_covers_later_shared_scene_trim(monkeypatch):
    monkeypatch.setattr(
        "app.video_models.profile_for", lambda *args: {"available": True, "memory_estimate_mib": 16384}
    )
    with TestClient(app) as api:
        row, revision = shared_plan(api, [visual(60, kind="video"), shared(0, 120, media_start_seconds=4.0)])
        result = api.post(
            f"/api/studio/materials/{row['id']}/shots",
            json={"client_request_id": str(uuid4()), "revision_id": revision["id"], "scene": 0},
        )
        assert result.status_code == 202, result.text
        assert result.json()["parameters"]["timeline"]["target_frames"] >= 8 * 24
        with session_factory()() as db:
            run = db.get(Run, result.json()["id"])
            assert run.parameters["studio_storyboard_sha256"]


def test_shared_sources_remain_private_and_manual_saved_timing_is_not_refitted(ready, accounts):  # noqa: F811
    admin, alice, bob = accounts
    source, _ = upload(alice, "blue")
    foreign, _ = upload(bob, "red")
    row, revision = shared_plan(alice, [visual(60), shared(0, 120)])
    assert sum(s["duration_frames"] for s in revision["storyboard"]["scenes"]) == 180
    assert revision["options"]["duration_seconds"] != 6
    assert render(alice, row, revision, foreign).status_code == 422
    assert render(bob, row, revision, source).status_code == 404
    assert render(admin, row, revision, source).status_code == 404
    assert render(alice, row, revision, source).status_code == 202
