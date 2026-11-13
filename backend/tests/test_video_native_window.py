"""Larger native windows preserve duration, frozen plans and old Runner behaviour."""

from uuid import uuid4

import pytest
from app.media_jobs import LongVideoRequest, publish_video
from app.media_plan import MediaTimeline, timeline
from app.models import Run, Task
from app.video import VideoRequest, create_video_run, native_window_frames, recommended_profile
from fastapi import HTTPException


def qualified_profile(windows=None):
    return {
        "available": True,
        "continuation_frames": [1],
        "profile_observation": {
            key: {"size_bytes": 0, "mtime": 0.0} for key in ("wan_model", "wan_text_encoder", "wan_vae")
        },
        "memory_profiles": [
            {
                "id": "bounded_11g",
                "available": True,
                "ram_mib": 11264,
                "native_windows": [{"width": 1280, "height": 704, "frames": 121}]
                if windows is None
                else windows,
            }
        ],
    }


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
        client_request_id=uuid4(),
        prompt="An adult turns their head",
        duration_seconds=10,
        memory_profile="bounded_11g",
    )
    old = publish_video(session, request, observed_profile=qualified_profile([]))
    old_plan = session.get(Task, old["task_id"]).metadata_json["media_plan"]
    profile = qualified_profile()
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


def test_qualified_windows_do_not_grant_untested_precision_or_portrait_geometry():
    profile = qualified_profile()
    assert native_window_frames(VideoRequest(prompt="Scene", memory_profile="bounded_11g"), profile) == 121
    assert native_window_frames(VideoRequest(prompt="Scene"), profile) == 81
    assert (
        native_window_frames(
            VideoRequest(prompt="Scene", memory_profile="bounded_11g", width=704, height=1280), profile
        )
        == 81
    )
    assert recommended_profile(profile, 27000) == "bounded_11g"


@pytest.mark.parametrize("window", [None, True, "121", 81, 122, 121.0])
def test_malformed_scoped_window_is_rejected_before_enqueue(session, window):
    profile = qualified_profile([{"width": 1280, "height": 704, "frames": window}])
    body = VideoRequest(prompt="Scene", frames=121, memory_profile="bounded_11g")
    with pytest.raises(HTTPException, match="unsupported native"):
        create_video_run(session, body, observed_profile=profile)


@pytest.mark.parametrize("frames,expected", [(81, [2, 7, 9]), (121, [7, 9])])
def test_larger_queued_run_filters_devices_that_do_not_fit_its_qualified_recipe(
    monkeypatch, frames, expected
):
    from types import SimpleNamespace

    from app.host_media_executor import HostMediaExecutor
    from app.video import VideoExecutor

    monkeypatch.setattr(
        HostMediaExecutor, "reserve_devices_from_hardware", lambda self, session, run, hardware: hardware
    )
    hardware = {
        "gpus": [
            {"index": 2, "memory_total_mib": 8192},
            {"index": 7, "memory_total_mib": 12288},
            {"index": 9, "memory_total_mib": 24576},
        ],
        "memory": {"available_mib": 26000},
    }
    result = VideoExecutor().reserve_devices_from_hardware(
        None, SimpleNamespace(parameters={"frames": frames}), hardware
    )
    assert [g["index"] for g in result["gpus"]] == expected
    assert result["memory"] == hardware["memory"]
