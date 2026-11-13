"""Larger native windows preserve duration, frozen plans and old Runner behaviour."""

from uuid import uuid4

import pytest
from app.media_jobs import LongVideoRequest, publish_video
from app.media_plan import MediaTimeline, timeline
from app.models import Run, Task
from app.video import VideoRequest, create_video_run
from fastapi import HTTPException


@pytest.mark.parametrize("frames", [24, 81, 120, 121, 122, 240, 480, 7200])
@pytest.mark.parametrize("context", [1, 17])
def test_larger_window_preserves_exact_duration_and_overlap(frames, context):
    plan = timeline(
        frames=frames, fps=24, seed=43, mode="continuous", context_frames=context, window_frames=121
    )
    assert sum(s.output_frames for s in plan.segments) == frames
    assert all(s.generated_frames <= 121 for s in plan.segments)
    assert [s.first_frame for s in plan.segments] == [0] + [context] * (len(plan.segments) - 1)
    assert MediaTimeline.model_validate_json(plan.model_dump_json()) == plan
    if frames > 121:
        assert len(plan.segments) <= len(
            timeline(frames=frames, fps=24, seed=43, mode="continuous", context_frames=context).segments
        )


@pytest.mark.parametrize("window", [True, 81.0, "121", 82, 120, 122, None])
def test_no_arbitrary_or_coerced_window(window):
    with pytest.raises(ValueError, match="bounded media"):
        timeline(frames=240, fps=24, seed=43, window_frames=window)


def test_new_capability_freezes_two_windows_and_legacy_plan_stays_unchanged(session):
    request = LongVideoRequest(
        client_request_id=uuid4(), prompt="An adult turns their head", duration_seconds=10
    )
    old = publish_video(session, request, observed_profile={"available": True, "continuation_frames": [1]})
    old_plan = session.get(Task, old["task_id"]).metadata_json["media_plan"]
    profile = {"available": True, "continuation_frames": [1], "native_window_frames": 121}
    # Idempotent publication does not repartition an existing frozen Task.
    again = publish_video(session, request, observed_profile=profile)
    assert again["task_id"] == old["task_id"]
    assert session.get(Task, again["task_id"]).metadata_json["media_plan"] == old_plan
    request = request.model_copy(update={"client_request_id": uuid4()})
    new = publish_video(session, request, observed_profile=profile)
    plan = session.get(Task, new["task_id"]).metadata_json["media_plan"]
    assert [s["output_frames"] for s in plan["timing"]["segments"]] == [121, 119]
    runs = [session.get(Run, identifier) for identifier in plan["segment_run_ids"]]
    assert [r.parameters["frames"] for r in runs] == [121, 121]
    assert runs[1].parameters["previous_video_run_id"] == runs[0].id
    assert len(old_plan["segment_run_ids"]) == 3


@pytest.mark.parametrize("window", [None, True, "121", 81, 122])
def test_unqualified_large_direct_run_is_rejected_before_enqueue(session, window):
    body = VideoRequest(prompt="A cup on a table", frames=121)
    with pytest.raises(HTTPException, match="larger native"):
        create_video_run(session, body, observed_profile={"available": True, "native_window_frames": window})


def test_large_window_preserves_explicit_shot_boundaries():
    plan = timeline(frames=240, fps=24, seed=43, scene_frames=[72, 168], window_frames=121)
    assert [s.start_frame for s in plan.segments] == [0, 72, 193]
    assert [s.output_frames for s in plan.segments] == [72, 121, 47]
    assert all(s.first_frame == 0 for s in plan.segments)
