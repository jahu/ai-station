"""Compound malformed-model results receive every independent repair category."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.studio_plan_validation import validate_storyboard
from fastapi.testclient import TestClient
from test_studio_director import local_model, request, step  # noqa: F401
from test_studio_materials import board, material


def test_bad_framing_does_not_hide_script_length_or_library_window():
    identity = str(uuid4())
    raw = board()
    raw["scenes"][0].update(
        framing="x" * 501,
        narration=" ".join(["word"] * 248),
        visual_kind="library",
        source_artifact_id=identity,
        duration_frames=600,
    )
    with pytest.raises(ValueError) as caught:
        validate_storyboard(
            json.dumps(raw),
            {
                "audio": "voice_music",
                "duration_seconds": 75,
                "narration_words": {"minimum": 170, "maximum": 190},
            },
            {identity: {"kind": "video"}},
            {identity: {"duration_seconds": 6.0}},
        )
    error = str(caught.value)
    assert "248 spoken words" in error and "at most 190" in error
    assert "framing" in error and "500 characters" in error
    assert "ends at 6s" in error and "ends at 20s" in error
    assert '"scene_count": 1' in error
    assert "x" * 100 not in error


def test_valid_schema_still_checks_source_windows_after_timing_fit():
    identity = str(uuid4())
    raw = board()
    raw["scenes"][0].update(visual_kind="library", source_artifact_id=identity)
    with pytest.raises(ValueError, match="fitted window ends at 30s"):
        validate_storyboard(
            json.dumps(raw),
            {"audio": "voice_music", "duration_seconds": 30},
            {identity: {"kind": "video"}},
            {identity: {"duration_seconds": 6.0}},
        )


def test_unknown_source_and_music_policy_report_together():
    raw = board()
    raw["music_brief"] = "x" * 600
    raw["scenes"][0].update(visual_kind="library", source_artifact_id=str(uuid4()))
    with pytest.raises(ValueError) as caught:
        validate_storyboard(json.dumps(raw), {"audio": "voice", "duration_seconds": 30}, {}, {})
    assert "audio policy" in str(caught.value)
    assert "512 characters" in str(caught.value)
    assert "source IDs only" in str(caught.value)


def test_compound_failure_is_corrected_in_one_remaining_model_attempt(local_model):  # noqa: F811
    calls, responses = local_model
    bad = board()
    bad["scenes"][0].update(framing="x" * 501, narration=" ".join(["word"] * 248))
    good = board()
    good["scenes"][0]["narration"] = " ".join(["word"] * 180)
    responses[:] = [json.dumps(bad), json.dumps(good)]
    with TestClient(app) as browser:
        row = material(browser, options={"narration_words": {"minimum": 170, "maximum": 190}})
        path = "/api/studio/materials/" + row["id"]
        queued = browser.post(path + "/plan", json=request()).json()
        step()
        finished = browser.get("/api/runs/" + queued["id"]).json()
        assert finished["status"] == "succeeded", finished["error_message"]
        feedback = calls[1]["messages"][-1]["content"]
        assert "248 spoken words" in feedback and "500 characters" in feedback
        assert len(calls) == 2
        assert len(browser.get(path + "/revisions").json()) == 1


@pytest.mark.parametrize("raw", [None, [], {"scenes": [None]}, {"scenes": [{"narration": False}]}])
def test_malformed_shapes_fail_cleanly_without_secondary_type_errors(raw):
    with pytest.raises(ValueError):
        validate_storyboard(json.dumps(raw), {"audio": "voice", "duration_seconds": 30}, {}, {})


@pytest.mark.parametrize("verified,fps,expected", [(True, 24, 6.0), (False, 24, None), (True, True, None)])
def test_worker_catalog_contains_only_completed_typed_timing_hints(local_model, verified, fps, expected):  # noqa: F811
    import tempfile
    from pathlib import Path

    from app.artifacts import register_file
    from app.db import session_factory
    from app.runs import create_run, create_task

    calls, responses = local_model
    with session_factory()() as db:
        task = create_task(db, title="Fake inspected video", prompt="Fixture", capability="video.generate")
        run = create_run(
            db, task, executor_type="fixture_video", capability="video.generate", run_type="video"
        )
        run.status = "succeeded"
        with tempfile.NamedTemporaryFile(suffix=".mp4") as file:
            file.write(b"fake source bytes; not real video qualification")
            file.flush()
            artifact = register_file(
                db,
                source=Path(file.name),
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="fixture.mp4",
                run_id=run.id,
                metadata={"verified": verified, "fps": fps, "frames": 144},
            )
        db.commit()
        identity = artifact.id
    output = board()
    output["scenes"][0].update(visual_kind="library", source_artifact_id=identity, duration_frames=180)
    responses[:] = [json.dumps(output)]
    with TestClient(app) as browser:
        row = material(browser, options={"duration_seconds": 6})
        queued = browser.post(
            "/api/studio/materials/" + row["id"] + "/plan", json=request(reference_artifact_ids=[identity])
        ).json()
        step()
        done = browser.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        entry = json.loads(calls[0]["messages"][1]["content"])["source_catalog"][0]
        assert entry["artifact_id"] == identity and entry["kind"] == "video"
        assert entry.get("duration_seconds") == expected
        assert not {"relative_path", "command", "permissions"} & entry.keys()


def test_bounded_report_keeps_word_failure_ahead_of_many_field_errors():
    raw = board()
    raw["scenes"] = [{**raw["scenes"][0], "framing": "x" * 501, "narration": ""} for _ in range(40)]
    raw["scenes"][0]["narration"] = " ".join(["word"] * 248)
    with pytest.raises(ValueError) as caught:
        validate_storyboard(
            json.dumps(raw),
            {"audio": "voice_music", "duration_seconds": 75, "narration_words": {"maximum": 190}},
            {},
            {},
        )
    report = str(caught.value)
    assert len(report) <= 6000 and "248 spoken words" in report and "500 characters" in report
    assert "additional schema errors" in report and "x" * 50 not in report
