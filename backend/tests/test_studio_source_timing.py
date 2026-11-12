"""Actual 6s→11.9s failure: preserve finite footage and fit elastic stills instead."""

import json
import random
import tempfile
from copy import deepcopy
from uuid import uuid4

import pytest
from app.api import app
from app.artifacts import register_file
from app.db import session_factory
from app.runs import create_run, create_task
from app.studio_schema import Storyboard
from app.studio_storyboard import fit_source_timing, fit_timing
from fastapi.testclient import TestClient
from test_studio_director import local_model, request, step  # noqa: F401
from test_studio_materials import board, material
from test_studio_storyboard import shared, visual


def outline(identity, audio="silent"):
    kinds = ["image", "library", "video", "image", "image", "image"]
    lengths = [210, 180, 120, 210, 210, 210]
    scenes = [
        visual(n, kind=k, **({"source_artifact_id": identity} if k == "library" else {}))
        for k, n in zip(kinds, lengths, strict=True)
    ]
    if audio != "silent":
        for shot, words in zip(scenes, [55, 12, 11, 55, 55, 55], strict=True):
            shot["narration"] = " ".join(["word"] * words)
    return Storyboard.model_validate(board(audio, scenes=scenes))


def test_actual_short_plan_fills_75s_without_stretching_supplied_or_planned_video():
    identity = str(uuid4())
    original = outline(identity)
    saved = deepcopy(original.model_dump())
    catalog = {identity: {"kind": "video", "duration_seconds": 6.0}}
    assert fit_timing(original, 75).scenes[1].duration_frames == 357  # 11.9s: original bug
    fitted = fit_source_timing(original, 75, catalog)
    assert [s.duration_frames for s in fitted.scenes] == [488, 180, 120, 488, 487, 487]
    assert fitted.frames == 2250 and original.model_dump() == saved
    assert fit_source_timing(fitted, 75, catalog) == fitted
    for old, new in zip(original.scenes, fitted.scenes, strict=True):
        assert old.model_dump(exclude={"duration_frames"}) == new.model_dump(exclude={"duration_frames"})


def test_reused_clip_respects_each_trim_window_even_if_total_frames_already_match():
    identity = str(uuid4())
    plan = Storyboard.model_validate(
        board(
            "silent",
            scenes=[
                visual(120, kind="library", source_artifact_id=identity),
                shared(0, 120, media_start_seconds=4.0),
                visual(120),
            ],
        )
    )
    fitted = fit_source_timing(plan, 12, {identity: {"kind": "video", "duration_seconds": 6.0}})
    assert [s.duration_frames for s in fitted.scenes] == [120, 60, 180]
    assert fitted.scenes[1].media_start_seconds == 4.0 and fitted.scenes[1].reuse_scene == 0


def test_insufficient_or_tiny_real_windows_fail_instead_of_looping_freezing_or_stretching():
    identity = str(uuid4())
    clip = visual(120, kind="library", source_artifact_id=identity)
    with pytest.raises(ValueError, match="Available clip windows"):
        fit_source_timing(
            Storyboard.model_validate(board("silent", scenes=[clip, clip])),
            15,
            {identity: {"kind": "video", "duration_seconds": 6.0}},
        )
    with pytest.raises(ValueError, match="minimum one-second"):
        fit_source_timing(
            Storyboard.model_validate(
                board("silent", scenes=[{**clip, "media_start_seconds": 5.8}, visual()])
            ),
            10,
            {identity: {"kind": "video", "duration_seconds": 6.0}},
        )


@pytest.mark.parametrize("duration", [None, True, "6", float("nan"), float("inf")])
def test_unknown_or_untyped_timing_does_not_invent_a_physical_source_limit(duration):
    identity = str(uuid4())
    plan = Storyboard.model_validate(
        board("silent", scenes=[visual(120, kind="library", source_artifact_id=identity)])
    )
    assert fit_source_timing(
        plan, 30, {identity: {"kind": "video", "duration_seconds": duration}}
    ) == fit_timing(plan, 30)


def test_bounded_rounding_preserves_exact_budget_caps_and_content_across_different_weights():
    rng = random.Random(7321)
    for _ in range(80):
        count = rng.randint(2, 8)
        caps = {i: rng.randint(30, 2000) for i in range(count)}
        seconds = rng.randint(count, sum(caps.values()) // 30)
        plan = Storyboard.model_validate(
            board("silent", scenes=[visual(rng.randint(30, 1200)) for _ in range(count)])
        )
        fitted = fit_timing(plan, seconds, limits=caps)
        assert fitted.frames == seconds * 30
        assert all(30 <= shot.duration_frames <= caps[i] for i, shot in enumerate(fitted.scenes))
        assert fit_timing(fitted, seconds, limits=caps) == fitted


def test_worker_uses_identical_source_limits_for_validation_speech_edit_and_publication(local_model):  # noqa: F811
    calls, responses = local_model
    with session_factory()() as db:
        task = create_task(
            db, title="Fixture source", prompt="Fake inspected receipt", capability="video.generate"
        )
        run = create_run(
            db, task, executor_type="fixture_video", capability="video.generate", run_type="video"
        )
        run.status = "succeeded"
        with tempfile.NamedTemporaryFile(suffix=".mp4") as file:
            file.write(b"fake inspected source; no real media inference")
            file.flush()
            from pathlib import Path

            asset = register_file(
                db,
                source=Path(file.name),
                artifact_type="video",
                mime_type="video/mp4",
                original_filename="fixture.mp4",
                run_id=run.id,
                metadata={"verified": True, "fps": 24, "frames": 144},
            )
        db.commit()
        identity = asset.id
    raw = outline(identity, "voice_music")
    responses[:] = [
        raw.model_dump_json(),
        json.dumps(
            {
                "lines": [
                    {"scene": i, "text": " ".join(["word"] * n)} for i, n in enumerate([44, 4, 4, 44, 42, 42])
                ]
            }
        ),
    ]
    with TestClient(app) as browser:
        row = material(
            browser, options={"duration_seconds": 75, "narration_words": {"minimum": 170, "maximum": 190}}
        )
        path = "/api/studio/materials/" + row["id"]
        queued = browser.post(path + "/plan", json=request(reference_artifact_ids=[identity])).json()
        step()
        result = browser.get("/api/runs/" + queued["id"]).json()
        assert result["status"] == "succeeded", result["error_message"]
        assert len(calls) == 2 and calls[1]["messages"][0]["content"].startswith(
            "You are the Studio narration editor"
        )
        saved = browser.get(path + "/revisions").json()
        assert len(saved) == 1
        shots = saved[0]["storyboard"]["scenes"]
        assert (
            sum(s["duration_frames"] for s in shots) == 2250
            and shots[1]["duration_frames"] <= 180
            and shots[2]["duration_frames"] <= 120
        )
        assert sum(len(s["narration"].split()) for s in shots) == 180
        cues = json.loads(calls[1]["messages"][1]["content"])["scenes"]
        assert cues[1]["seconds"] == 6 and cues[2]["seconds"] == 4
