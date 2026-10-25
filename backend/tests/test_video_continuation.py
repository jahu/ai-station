"""Frozen continuation policy preserves old tasks and uses owned pixels for new jobs."""

from uuid import uuid4

import pytest
from app.artifacts import adopt_existing
from app.config import get_settings
from app.media_jobs import LongVideoRequest, publish_video
from app.models import Run, Task
from app.runs import create_run, create_task
from app.video import VideoExecutor


def test_new_continuous_video_freezes_last_frame_for_all_segments(session):
    body = LongVideoRequest(client_request_id=uuid4(), prompt="Lake", duration_seconds=10)
    result = publish_video(
        session, body, observed_profile={"available": True, "continuation_frames": [1, 17]}
    )
    task = session.get(Task, result["task_id"])
    plan = task.metadata_json["media_plan"]
    assert plan["continuation_strategy"] == "last_frame_v1"
    segments = [session.get(Run, identifier) for identifier in plan["segment_run_ids"]]
    assert len(segments) == 3
    assert [run.parameters["media_segment"]["first_frame"] for run in segments] == [0, 1, 1]
    assert [run.parameters["media_segment"]["output_frames"] for run in segments] == [81, 80, 79]
    assert all(run.parameters["continuation_strategy"] == "last_frame_v1" for run in segments)
    assert "previous_video_run_id" not in segments[0].parameters
    assert all(
        run.parameters["previous_video_run_id"] == previous.id
        for previous, run in zip(segments, segments[1:])
    )
    assert session.get(Run, plan["compose_run_id"]).parameters["continuation_strategy"] == "last_frame_v1"


@pytest.mark.parametrize("advertised", [None, [17], [True], "1"])
def test_old_or_unrecognized_runner_capability_keeps_legacy_conditioning(session, advertised):
    body = LongVideoRequest(client_request_id=uuid4(), prompt="Lake", duration_seconds=10)
    result = publish_video(
        session, body, observed_profile={"available": True, "continuation_frames": advertised}
    )
    plan = session.get(Task, result["task_id"]).metadata_json["media_plan"]
    assert plan["continuation_strategy"] == "cached_latents_v1"
    assert len(plan["segment_run_ids"]) == 4
    assert [
        session.get(Run, identifier).parameters["media_segment"]["first_frame"]
        for identifier in plan["segment_run_ids"]
    ] == [0, 17, 17, 17]


@pytest.fixture
def owned_video_pair(session):
    root = get_settings().data_dir
    (root / "artifacts").mkdir(exist_ok=True)
    (root / "artifacts/prior.mp4").write_bytes(b"owned prior clip")
    (root / "artifacts/motion.safetensors").write_bytes(b"bounded test motion")
    task = create_task(session, title="Motion", prompt="Lake", capability="video.long")
    previous = create_run(
        session, task, run_type="video", capability="video.generate", executor_type="wan_video"
    )
    previous.status = "succeeded"
    video = adopt_existing(
        session,
        relative_path="artifacts/prior.mp4",
        artifact_type="video",
        mime_type="video/mp4",
        original_filename="prior.mp4",
        run_id=previous.id,
    )
    motion = adopt_existing(
        session,
        relative_path="artifacts/motion.safetensors",
        artifact_type="document",
        mime_type="application/octet-stream",
        original_filename="motion.safetensors",
        run_id=previous.id,
    )
    descriptor = {
        "relative_path": motion.relative_path,
        "sha256": motion.sha256,
        "size_bytes": motion.size_bytes,
    }
    video.metadata_json = {"motion_context": descriptor, "motion_context_artifact_id": motion.id}
    current = create_run(
        session,
        task,
        run_type="video",
        capability="video.generate",
        executor_type="wan_video",
        permissions=["filesystem_read", "workspace_write"],
        parameters={
            "previous_video_run_id": previous.id,
            "prompt": "Lake",
            "negative_prompt": "",
            "image_relative": None,
            "width": 1280,
            "height": 704,
            "frames": 81,
            "steps": 20,
            "cfg": 5,
            "seed": 43,
            "memory_profile": "bounded_11g",
        },
    )
    session.commit()
    return current, video, motion


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body):
        self.calls.append((method, path, body))
        return {"status": "running"}


@pytest.mark.parametrize("strategy", [None, "cached_latents_v1", "last_frame_v1"])
def test_continuation_dispatch_keeps_frozen_or_legacy_strategy(session, owned_video_pair, strategy):
    run, video, motion = owned_video_pair
    if strategy is not None:
        run.parameters = {**run.parameters, "continuation_strategy": strategy}
        session.commit()
    runner = RecordingRunner()
    VideoExecutor()._start(runner, run, "0", "unused")
    method, path, payload = runner.calls[0]
    assert (method, path) == ("POST", "/v1/runs/video")
    assert payload["continuation"]["sha256"] == video.sha256
    assert payload["frames"] == 81 and payload["seed"] == 43
    assert payload["image_relative"] is None
    if strategy == "last_frame_v1":
        assert payload["continuation_frames"] == 1
        assert "motion_context" not in payload
    else:
        assert payload["motion_context"]["sha256"] == motion.sha256


def test_last_frame_uses_video_even_when_unused_cache_is_trashed(session, owned_video_pair):
    from app.db import utcnow

    run, video, motion = owned_video_pair
    run.parameters = {**run.parameters, "continuation_strategy": "last_frame_v1"}
    motion.trashed_at = utcnow()
    session.commit()
    runner = RecordingRunner()
    VideoExecutor()._start(runner, run, "0", "unused")
    assert runner.calls[0][2]["continuation"]["sha256"] == video.sha256
    assert "motion_context" not in runner.calls[0][2]


@pytest.mark.parametrize("strategy", ["last_frame_v1", "cached_latents_v1"])
def test_every_continuation_requires_its_owned_available_video(session, owned_video_pair, strategy):
    from app.db import utcnow

    run, video, motion = owned_video_pair
    run.parameters = {**run.parameters, "continuation_strategy": strategy}
    video.trashed_at = utcnow()
    session.commit()
    runner = RecordingRunner()
    with pytest.raises(ValueError, match="prior motion context"):
        VideoExecutor()._start(runner, run, "0", "unused")
    assert not runner.calls


@pytest.mark.parametrize("strategy", ["unknown", None, {"strategy": "pixels"}])
def test_unknown_explicit_strategy_fails_before_native_dispatch(session, owned_video_pair, strategy):
    run, video, motion = owned_video_pair
    run.parameters = {**run.parameters, "continuation_strategy": strategy}
    session.commit()
    runner = RecordingRunner()
    with pytest.raises(ValueError, match="continuation strategy"):
        VideoExecutor()._start(runner, run, "0", "unused")
    assert not runner.calls


@pytest.mark.parametrize("change", ["other_task", "failed_source"])
def test_last_frame_never_uses_an_unowned_or_unsuccessful_prior_run(session, owned_video_pair, change):
    run, video, motion = owned_video_pair
    run.parameters = {**run.parameters, "continuation_strategy": "last_frame_v1"}
    previous = session.get(Run, video.run_id)
    if change == "other_task":
        other = create_task(session, title="Other", prompt="", capability="video.long")
        previous.task_id = other.id
    else:
        previous.status = "failed"
    session.commit()
    runner = RecordingRunner()
    with pytest.raises(ValueError, match="prior motion context"):
        VideoExecutor()._start(runner, run, "0", "unused")
    assert not runner.calls
