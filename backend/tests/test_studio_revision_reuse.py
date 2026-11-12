"""Real typed APIs/temporary files, fake rendering; never GPU qualification."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.models import Artifact, Run
from app.studio_revision_reuse import audio_contract, capture, verify
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_studio_audio_production import generators as generators
from test_studio_presenter import clip
from test_studio_production import advance, details, produce
from test_studio_production import movie as movie
from test_studio_render import draft, render, wave_source
from test_studio_render import ready as ready


@pytest.mark.parametrize("change", ["narration", "narration_delivery", "music_brief", "timing"])
def test_audio_contract_includes_performance_words_music_and_each_scene(change):
    from test_studio_materials import board

    value = board("voice_music")
    old = SimpleNamespace(storyboard=value)
    revised = deepcopy(value)
    if change == "narration":
        revised["scenes"][0]["narration"] = "New spoken words."
    elif change == "narration_delivery":
        revised["narration_delivery"] = {"pace": "fast"}
    elif change == "music_brief":
        revised["music_brief"] = "A different score"
    else:
        revised["scenes"][0]["duration_frames"] += 1
    assert audio_contract(old) != audio_contract(SimpleNamespace(storyboard=revised))


def test_caption_edit_reuses_exact_soundtrack_and_presenter_and_retains_legacy_receipt(movie, generators):
    from app.studio_production import Produce

    with TestClient(app) as api:
        row, original = draft(api, audio="voice_music")
        image, _ = upload(api, "blue")
        presenter = clip(api)
        audio = wave_source(api)
        old = render(api, row, original, image, audio, presenter={"media": presenter, "placement": "right"})
        assert old.status_code == 202, old.text
        advance(movie)
        storyboard = deepcopy(original["storyboard"])
        storyboard["scenes"][0].update(
            title="A clearer headline", visual_kind="library", source_artifact_id=image
        )
        revised = api.post(
            f"/api/studio/materials/{row['id']}/revisions",
            json={
                "client_request_id": str(uuid4()),
                "expected_version": 2,
                "parent_revision_id": original["id"],
                "storyboard": storyboard,
            },
        )
        assert revised.status_code == 201, revised.text
        request_id = str(uuid4())
        submitted = produce(
            api, row, revised.json(), reuse_export_run_id=old.json()["id"], client_request_id=request_id
        )
        assert submitted.status_code == 202, submitted.text
        assert (
            produce(
                api, row, revised.json(), reuse_export_run_id=old.json()["id"], client_request_id=request_id
            ).json()["id"]
            == submitted.json()["id"]
        )
        advance(movie)
        result = details(api, row)
        assert result["status"] == "succeeded", result
        assert not generators[0] and not generators[1]
        with session_factory()() as db:
            renders = list(
                db.scalars(select(Run).where(Run.executor_type == "motion_render").order_by(Run.created_at))
            )
            assert len(renders) == 2
            new = renders[-1]
            assert new.parameters["presenter"] == old.json()["parameters"]["presenter"]
            assert new.parameters["soundtrack_artifact_id"] == audio
            assert new.parameters["sources"] == old.json()["parameters"]["sources"]
            assert new.parameters["composition"]["scenes"][0]["title"] == "A clearer headline"
            assert not db.scalar(select(Run.id).where(Run.executor_type == "photo_pipe"))
            # Frozen old clip/file descriptors remain checked after restart.
            root = db.get(Run, submitted.json()["id"])
            from app.models import StudioRevision

            revision = db.get(StudioRevision, revised.json()["id"])
            state = root.metadata_json["production_state"]
            verify(db, state, revision)
            db.get(Artifact, presenter).trashed_at = utcnow()
            db.flush()
            with pytest.raises(ValueError):
                capture(db, old.json()["id"], revision)
        legacy = Produce(client_request_id=uuid4(), revision_id=uuid4()).model_dump(mode="json")
        assert "reuse_export_run_id" not in legacy


def test_revision_validation_preserves_fractional_edit_and_rejects_unrequested_inference():
    import json

    from app.studio_plan_validation import fit_plan, validate_storyboard
    from app.studio_schema import Storyboard
    from test_studio_materials import board

    options = {"audio": "silent", "duration_seconds": 10}
    value = board("silent")
    value["scenes"][0]["duration_frames"] = 485
    plan = Storyboard.model_validate(value)
    assert fit_plan(plan, options, {}, fit_duration=False).frames == 485
    assert fit_plan(plan, options, {}).frames == 300
    with pytest.raises(ValueError, match="Preserve the completed visuals"):
        validate_storyboard(json.dumps(value), options, {}, {}, existing_visuals_only=True)
    value["scenes"][0]["visual_kind"] = "graphics"
    value["scenes"][0]["title"] = "An explicit editorial title"
    value["scenes"][0]["layout"] = "statement"
    validate_storyboard(json.dumps(value), options, {}, {}, existing_visuals_only=True, fit_duration=False)
