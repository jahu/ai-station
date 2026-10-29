"""Source-bound whole-avatar publication/resource contracts; no model execution."""

import json
import wave
from datetime import timedelta
from uuid import uuid4

import pytest
from ai_station_runner.sonic_jobs import WholeAvatarRequest as NativeRequest
from ai_station_runner.whole_avatar_timing import whole_portrait_canvas
from app import whole_avatars as whole
from app.artifacts import register_file
from app.avatar_schema import FullAvatarSettings
from app.config import get_settings
from app.db import utcnow
from app.models import ResourceLock
from app.resources import active_locks
from app.runs import create_task
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

RECIPE = {"id": whole.PROFILE, "observation": "c" * 64}
PROFILE = {
    "available": True,
    "backend": "sonic",
    "recipe": RECIPE,
    "ram_mib": 18432,
    "max_side": 768,
    "max_pixels": 512 * 768,
    "fps": 25,
    "detected_gpu_count": 2,
}


@pytest.fixture
def sources(session, tmp_path):
    portrait, audio = tmp_path / "portrait.png", tmp_path / "speech.wav"
    Image.new("RGB", (512, 768), "white").save(portrait)
    with wave.open(str(audio), "wb") as target:
        target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        target.writeframes(b"\x00" * (16321 * 2))
    values = []
    for path, kind, mime in [(portrait, "image", "image/png"), (audio, "audio", "audio/wav")]:
        values.append(
            register_file(
                session,
                source=path,
                artifact_type=kind,
                mime_type=mime,
                original_filename=path.name,
                run_id=None,
            )
        )
    return values


def settings(sources, **changes):
    return FullAvatarSettings(
        image_artifact_id=sources[0].id,
        audio_artifact_id=sources[1].id,
        generation_profile=whole.PROFILE,
        **changes,
    )


def task(session):
    return create_task(
        session, title="Whole portrait", prompt="Neutral speaking portrait", capability="avatar.long"
    )


def create(session, sources, **changes):
    return whole.create_whole_run(
        session, settings(sources, **changes), task=task(session), observed_profile=PROFILE
    )


def test_legacy_settings_serialize_exactly_without_acquiring_a_generation_choice(sources):
    body = FullAvatarSettings(image_artifact_id=sources[0].id, audio_artifact_id=sources[1].id)
    dumped = body.model_dump(mode="json")
    assert "generation_profile" not in dumped and "memory_profile" not in dumped
    assert dumped["size"] == 384 and dumped["steps"] == 8
    assert FullAvatarSettings.model_validate(dumped).model_dump(mode="json") == dumped


def test_whole_request_roundtrip_does_not_persist_misleading_echo_controls(sources):
    dumped = settings(sources).model_dump(mode="json")
    assert dumped["generation_profile"] == whole.PROFILE
    assert not {"size", "steps", "memory_profile"} & dumped.keys()
    assert FullAvatarSettings.model_validate(dumped).model_dump(mode="json") == dumped


@pytest.mark.parametrize(
    "changes", [{"size": 384}, {"size": 512}, {"steps": 8}, {"steps": 25}, {"memory_profile": "bounded_11g"}]
)
def test_echo_controls_cannot_silently_override_the_frozen_whole_recording_profile(sources, changes):
    with pytest.raises(ValidationError):
        settings(sources, **changes)


@pytest.mark.parametrize(
    "dimensions",
    [
        (32, 32),
        (32, 128),
        (128, 32),
        (768, 512),
        (512, 768),
        (1024, 768),
        (768, 1024),
        (8192, 8192),
        (4000, 2000),
    ],
)
def test_control_plane_and_native_canvas_contracts_agree(dimensions):
    assert whole.canvas(*dimensions) == whole_portrait_canvas(*dimensions)


def test_new_run_freezes_complete_audio_geometry_lineage_resources_and_profile(session, sources):
    run = create(session, sources)
    assert run.executor_type == "sonic_whole" and run.execution_target == "host" and run.status == "queued"
    assert (
        run.effective_permissions == ["filesystem_read", "workspace_write"] and run.retry_class == "inspect"
    )
    assert run.requested_resources == {"ram_mib": 18432, "gpu_count": 2}
    observation = run.parameters["observed_input"]
    assert observation["samples"] == 16321 and observation["target_frames"] == 18
    assert observation["base_frames"] == 9 and observation["endpoint_frames"] == 1
    assert (observation["width"], observation["height"]) == (512, 768)
    assert run.parameters["whole_recipe"] == RECIPE and run.parameters["steps"] == 25
    assert run.parameters["parent_artifact_ids"] == [a.id for a in sources]
    assert all(item["relative_path"].startswith("artifacts/") for item in run.parameters["whole_inputs"])
    assert str(get_settings().data_dir) not in json.dumps(run.parameters)
    whole.WholeAvatarExecutor().validate_inputs(session, run)


def test_selected_gpu_uses_single_device_and_retains_the_callers_shorter_deadline(session, sources):
    deadline = (utcnow() + timedelta(seconds=120)).isoformat()
    run = whole.create_whole_run(
        session,
        settings(sources, gpu="11"),
        task=task(session),
        observed_profile=PROFILE,
        execution_deadline_at=deadline,
    )
    assert run.parameters["execution_deadline_at"] == deadline and run.parameters["gpu_count"] == 1


@pytest.mark.parametrize(
    "deadline", ["invalid", "2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00", "2099-01-01T00:00:00"]
)
def test_new_execution_cannot_have_an_expired_unbounded_or_naive_deadline(session, sources, deadline):
    with pytest.raises(ValueError):
        whole.create_whole_run(
            session,
            settings(sources),
            task=task(session),
            observed_profile=PROFILE,
            execution_deadline_at=deadline,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"available": False},
        {"recipe": {**RECIPE, "observation": "f" * 64}},
        {"max_pixels": 768**2},
        {"ram_mib": 1},
        {"recipe": None},
    ],
)
def test_current_setup_cannot_replace_the_frozen_recipe_or_memory_bounds(session, sources, change):
    with pytest.raises(HTTPException) as error:
        whole.create_whole_run(
            session,
            settings(sources),
            task=task(session),
            observed_profile={**PROFILE, **change},
            recipe=RECIPE,
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize("fault", ["bytes", "trashed", "metadata", "symlink", "hardlink"])
def test_worker_rechecks_the_exact_published_sources_before_dispatch(session, sources, tmp_path, fault):
    run = create(session, sources)
    artifact = sources[0]
    path = get_settings().data_dir / artifact.relative_path
    if fault == "bytes":
        path.write_bytes(b"different")
    elif fault == "trashed":
        artifact.trashed_at = utcnow()
    elif fault == "metadata":
        artifact.mime_type = "image/webp"
    elif fault == "symlink":
        elsewhere = tmp_path / "elsewhere.png"
        elsewhere.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(elsewhere)
    else:
        import os

        os.link(path, tmp_path / "hardlink.png")
    with pytest.raises(ValueError):
        whole.WholeAvatarExecutor().validate_inputs(session, run)


def hardware(*free):
    return {
        "gpus": [{"index": index, "memory_total_mib": memory, "memory_used_mib": 0} for index, memory in free]
    }


def test_gpu_bundle_preserves_the_primary_vram_requirement_when_another_job_holds_it(session, sources):
    run = create(session, sources)
    session.add(ResourceLock(resource_key="gpu:7", run_id=str(uuid4())))
    session.flush()
    result = whole.WholeAvatarExecutor().reserve_devices_from_hardware(
        session, run, hardware((7, 12000), (11, 7000), (13, 7000))
    )
    assert result is None and active_locks(session) == {"gpu:7"}


def test_bundle_selects_a_qualified_primary_and_auxiliary_from_discovered_ids(session, sources):
    run = create(session, sources)
    allocated = whole.WholeAvatarExecutor().reserve_devices_from_hardware(
        session, run, hardware((7, 7000), (11, 12000))
    )
    assert allocated == "11" and run.allocated_resources["gpus"] == ["11", "7"]
    assert active_locks(session) == {"gpu:11", "gpu:7"}


@pytest.mark.parametrize("free", [((7, 10000), (11, 10000)), ((7, 12000), (11, 6000)), ((7, 12000),)])
def test_external_gpu_memory_pressure_waits_without_taking_partial_locks(session, sources, free):
    run = create(session, sources)
    assert whole.WholeAvatarExecutor().reserve_devices_from_hardware(session, run, hardware(*free)) is None
    assert active_locks(session) == set()


def test_native_dispatch_has_only_typed_frozen_inputs_and_allocated_devices(session, sources):
    run = create(session, sources)
    executor = whole.WholeAvatarExecutor()
    allocated = executor.reserve_devices_from_hardware(session, run, hardware((7, 12000), (11, 12000)))
    calls = []

    class Runner:
        def request(self, method, path, body):
            calls.append((method, path, body))
            return {"pid": 77}

    assert executor._start(Runner(), run, allocated, "ignored-portable-output")["pid"] == 77
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/v1/runs/whole-avatar")
    accepted = NativeRequest.model_validate(body)
    assert accepted.gpus == [7, 11] and accepted.observed_input == run.parameters["observed_input"]
    assert not {"command", "model_dir", "runtime_dir", "output", "steps"} & body.keys()


def test_progress_is_source_bound_monotonic_and_does_not_complete_the_run(session, sources):
    run = create(session, sources)
    executor = whole.WholeAvatarExecutor()
    work = get_settings().data_dir / "runs" / run.id / "whole-avatar"
    work.mkdir(parents=True)
    value = {
        "version": 1,
        "run_id": run.id,
        "recipe": RECIPE,
        "phase": "animating",
        "completed_windows": 12,
        "total_windows": 25,
    }
    (work / "progress.json").write_text(json.dumps(value))
    executor.on_inspection(session, run, {})
    assert run.metadata_json["avatar_progress"] == {
        "phase": "animating",
        "completed_windows": 12,
        "total_windows": 25,
    }
    assert run.status == "queued"
    for change in [
        {"completed_windows": 11},
        {"recipe": {**RECIPE, "observation": "f" * 64}},
        {"phase": []},
        {"phase": "finishing", "completed_windows": 12},
        {"completed_windows": True},
        {"total_windows": 100},
    ]:
        (work / "progress.json").write_text(json.dumps({**value, **change}))
        executor.on_inspection(session, run, {})
        assert run.metadata_json["avatar_progress"]["completed_windows"] == 12
