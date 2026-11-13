"""Owned recurrent source binding and common media adapter; fake media only."""

import json
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.artifacts import adopt_existing
from app.config import get_settings
from app.db import utcnow
from app.models import Artifact, RunEvent
from app.runs import create_run, create_task
from app.svi_executor import GEOMETRY, PROFILE, RAM_MIB, SviExecutor, descriptor
from PIL import Image
from sqlalchemy import select


@pytest.fixture(name="pair")
def owned_pair(session):
    root = get_settings().data_dir
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "teal").save(root / "artifacts/source.png")
    source = adopt_existing(
        session,
        relative_path="artifacts/source.png",
        artifact_type="image",
        mime_type="image/png",
        original_filename="source.png",
        run_id=None,
    )
    task = create_task(session, title="Recurrent video", prompt="A sailboat turns", capability="video.long")
    parameters = {
        **GEOMETRY,
        "managed_runtime": {"profile": PROFILE, "manifest_sha256": "a" * 64, "environment_id": "b" * 64},
        "managed_video_gpu_indices": [7],
        "image_artifact_id": source.id,
        "image": descriptor(source),
        "parent_artifact_ids": [source.id],
        "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
        "prompt": "A sailboat turns",
        "negative_prompt": "",
        "seed": 173,
    }
    previous = create_run(
        session,
        task,
        run_type="video",
        capability="video.animate",
        executor_type="wan_svi_video",
        parameters=json.loads(json.dumps(parameters)),
        requested_gpu="auto",
        requested_resources={"ram_mib": RAM_MIB},
        permissions=["filesystem_read", "workspace_write"],
    )
    previous.status = "succeeded"
    (root / "artifacts/previous.mp4").write_bytes(b"fake previous video")
    video = adopt_existing(
        session,
        relative_path="artifacts/previous.mp4",
        artifact_type="video",
        mime_type="video/mp4",
        original_filename="previous.mp4",
        run_id=previous.id,
        metadata={"profile_identity": "c" * 64, "managed_runtime": parameters["managed_runtime"]},
    )
    (root / "artifacts/motion.safetensors").write_bytes(b"fake bounded tensor")
    motion = adopt_existing(
        session,
        relative_path="artifacts/motion.safetensors",
        artifact_type="document",
        mime_type="application/octet-stream",
        original_filename="motion.safetensors",
        run_id=previous.id,
        parent_artifact_ids=[video.id],
        metadata={
            "role": "svi_motion",
            "context_frames": 4,
            "profile_identity": "c" * 64,
            "internal_media": True,
        },
    )
    video.metadata_json = {**video.metadata_json, "motion_context_artifact_id": motion.id}
    current = create_run(
        session,
        task,
        run_type="video",
        capability="video.animate",
        executor_type="wan_svi_video",
        parameters={**json.loads(json.dumps(parameters)), "previous_motion_run_id": previous.id},
        requested_gpu="auto",
        requested_resources={"ram_mib": RAM_MIB},
        permissions=["filesystem_read", "workspace_write"],
    )
    session.flush()
    return SimpleNamespace(source=source, previous=previous, video=video, motion=motion, current=current)


def test_completed_owned_motion_is_frozen_once_with_lineage_and_event(session, pair):
    adapter = SviExecutor()
    adapter.validate_inputs(session, pair.current)
    saved = json.loads(json.dumps(pair.current.parameters))
    assert saved["previous_motion"] == descriptor(pair.motion)
    assert saved["svi_profile_identity"] == "c" * 64
    assert pair.motion.id in saved["parent_artifact_ids"]
    adapter.validate_inputs(session, pair.current)
    assert pair.current.parameters == saved
    events = list(
        session.scalars(
            select(RunEvent).where(
                RunEvent.run_id == pair.current.id, RunEvent.event_type == "motion.context.bound"
            )
        )
    )
    assert len(events) == 1 and events[0].payload["source_run_id"] == pair.previous.id


@pytest.mark.parametrize(
    "change",
    [
        "failed",
        "wrong_executor",
        "anchor",
        "engine",
        "image_trashed",
        "image_purging",
        "image_hash",
        "video_trashed",
        "video_purging",
        "video_owner",
        "motion_purged",
        "motion_purging",
        "motion_owner",
        "motion_lineage",
        "motion_profile",
        "motion_size",
        "motion_role",
    ],
)
def test_changed_owner_anchor_engine_availability_or_motion_provenance_is_rejected(session, pair, change):
    if change == "failed":
        pair.previous.status = "failed"
    elif change == "wrong_executor":
        pair.previous.executor_type = "experimental_svi_video"
    elif change == "anchor":
        pair.previous.parameters = {
            **pair.previous.parameters,
            "image": {**pair.previous.parameters["image"], "sha256": "d" * 64},
        }
    elif change == "engine":
        pair.previous.parameters = {
            **pair.previous.parameters,
            "managed_runtime": {**pair.previous.parameters["managed_runtime"], "environment_id": "d" * 64},
        }
    elif change == "image_hash":
        pair.source.sha256 = "d" * 64
    elif change == "image_trashed":
        pair.source.trashed_at = utcnow()
    elif change == "image_purging":
        pair.source.purge_run_id = str(uuid4())
    elif change == "video_trashed":
        pair.video.trashed_at = utcnow()
    elif change == "video_purging":
        pair.video.purge_run_id = str(uuid4())
    elif change == "video_owner":
        pair.video.owner_id = str(uuid4())
    elif change == "motion_purged":
        pair.motion.purged_at = utcnow()
    elif change == "motion_purging":
        pair.motion.purge_run_id = str(uuid4())
    elif change == "motion_owner":
        pair.motion.owner_id = str(uuid4())
    elif change == "motion_lineage":
        pair.motion.parent_artifact_ids = []
    elif change == "motion_profile":
        pair.motion.metadata_json = {**pair.motion.metadata_json, "profile_identity": "d" * 64}
    elif change == "motion_size":
        pair.motion.size_bytes = 4 * 1024**2
    else:
        pair.motion.metadata_json = {**pair.motion.metadata_json, "role": "wan_motion"}
    # These cases also model corrupt in-memory observations; never persist an
    # impossible foreign-key owner merely to exercise the application fence.
    with session.no_autoflush, pytest.raises(ValueError):
        SviExecutor().validate_inputs(session, pair.current)


@pytest.mark.parametrize("change", ["snapshot", "profile", "lineage"])
def test_a_bound_snapshot_cannot_be_rebound_during_retry(session, pair, change):
    adapter = SviExecutor()
    adapter.validate_inputs(session, pair.current)
    values = pair.current.parameters
    if change == "snapshot":
        values = {**values, "previous_motion": {**values["previous_motion"], "sha256": "d" * 64}}
    elif change == "profile":
        values = {key: value for key, value in values.items() if key != "svi_profile_identity"}
    else:
        values = {**values, "parent_artifact_ids": [pair.source.id]}
    pair.current.parameters = values
    with pytest.raises(ValueError, match="frozen"):
        adapter.validate_inputs(session, pair.current)


def test_native_payload_keeps_the_original_image_and_caps_a_workflow_child_to_one_hour(session, pair):
    adapter = SviExecutor()
    adapter.validate_inputs(session, pair.current)
    calls = []
    runner = SimpleNamespace(request=lambda *args: calls.append(args) or {"pid": 123})
    assert adapter._start(runner, pair.current, "7", "unused")["pid"] == 123
    method, route, payload = calls[0]
    assert (method, route) == ("POST", "/v1/runs/svi")
    assert payload["image"] == descriptor(pair.source)
    assert payload["previous_motion"] == descriptor(pair.motion)
    assert 0 < payload["deadline_at"] - time.time() <= 3600
    assert not {"frames", "width", "steps", "argv", "graph"} & payload.keys()


def test_missing_memory_budget_is_rejected_before_device_reservation(session, pair):
    pair.current.requested_resources = {"ram_mib": 0}
    with pytest.raises(ValueError, match="resource reservation"):
        SviExecutor().reserve_devices_from_hardware(
            session, pair.current, {"gpus": [{"index": 7, "memory_total_mib": 12288}]}
        )


def test_missing_gpu_choice_fails_instead_of_waiting_forever_for_a_resource(session, pair):
    pair.current.requested_gpu = "none"
    with pytest.raises(ValueError, match="GPU choice"):
        SviExecutor().reserve_devices_from_hardware(session, pair.current, {"gpus": []})


def test_output_adopts_four_frame_motion_metadata_and_original_lineage(session, pair):
    root = get_settings().data_dir
    run = pair.current
    SviExecutor().validate_inputs(session, run)
    relative = f"artifacts/{run.id[:2]}/{run.id[2:4]}/{run.id}"
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / (relative + ".mp4")).write_bytes(b"fake final video")
    (root / (relative + ".safetensors")).write_bytes(b"fake next context")
    import hashlib

    motion_path = root / (relative + ".safetensors")
    artifact = adopt_existing(
        session,
        relative_path=relative + ".mp4",
        artifact_type="video",
        mime_type="video/mp4",
        original_filename="result.mp4",
        run_id=run.id,
        parent_artifact_ids=run.parameters["parent_artifact_ids"],
    )
    artifact.metadata_json = {
        **GEOMETRY,
        "backend": "wan22-svi-pro-q4",
        "profile_identity": "c" * 64,
        "managed_runtime": run.parameters["managed_runtime"],
        "output_sha256": artifact.sha256,
        "motion_context": {
            "relative_path": relative + ".safetensors",
            "sha256": hashlib.sha256(motion_path.read_bytes()).hexdigest(),
            "size_bytes": motion_path.stat().st_size,
        },
    }
    SviExecutor().on_success(session, run, artifact)
    context = session.get(Artifact, artifact.metadata_json["motion_context_artifact_id"])
    assert context.metadata_json == {
        "internal_media": True,
        "role": "svi_motion",
        "context_frames": 4,
        "profile_identity": "c" * 64,
    }
    assert context.parent_artifact_ids == [artifact.id]
    assert pair.source.id in artifact.parent_artifact_ids and pair.motion.id in artifact.parent_artifact_ids
