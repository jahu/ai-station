"""Queued recurrent segment creation with frozen model and original-image inputs."""

import re
from copy import deepcopy
from datetime import timedelta

from fastapi import HTTPException

from app.config import get_settings
from app.db import utcnow
from app.models import Artifact, Run
from app.paths import safe_join
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task
from app.svi_executor import NAME, RAM_MIB, available_artifact, checked_recipe, descriptor, geometry


def checked_profile(body, profile, *, long=False):
    try:
        selected = geometry({"width": body.width, "height": body.height})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if (
        profile.get("available") is not True
        or profile.get("backend") != "wan22-svi-pro-q4"
        or profile.get("native_window_frames") != 81
        or profile.get("continuation_frames") != 4
        or profile.get("memory_estimate_mib") != RAM_MIB
        or any(profile.get(key) != value for key, value in selected.items() if key != "frames")
    ):
        raise HTTPException(409, "The selected SVI recipe is unavailable or has not been qualified")
    if any(
        getattr(body, key) != value
        for key, value in selected.items()
        if key not in ({"fps", "frames"} if long else {"fps"})
    ):
        raise HTTPException(422, "This SVI recipe uses its qualified geometry, 81 frames, 20 steps and CFG 5")
    if body.memory_profile != "default":
        raise HTTPException(422, "SVI uses its model-default 18-GiB workload, not the 11-GiB Wan profile")
    parameters = {
        **selected,
        "managed_runtime": profile.get("managed_runtime"),
        "managed_video_gpu_indices": profile.get("eligible_gpu_indices"),
    }
    try:
        checked_recipe(parameters, {"ram_mib": RAM_MIB})
    except ValueError:
        raise HTTPException(409, "Refresh the exact SVI engine and compatible GPU observation") from None
    if body.gpu != "auto" and int(body.gpu) not in parameters["managed_video_gpu_indices"]:
        raise HTTPException(422, "Choose a GPU compatible with the selected SVI engine")
    if body.image_artifact_id is None:
        raise HTTPException(422, "Choose an original image for recurrent video")
    result = {
        "managed_runtime": dict(parameters["managed_runtime"]),
        "managed_video_gpu_indices": list(parameters["managed_video_gpu_indices"]),
    }
    if body.model_id:
        model = profile.get("video_model")
        if (
            not isinstance(model, dict)
            or model.get("definition_id") != str(body.model_id)
            or not isinstance(model.get("binding"), dict)
            or model["binding"].get("managed_runtime") != result["managed_runtime"]
        ):
            raise HTTPException(409, "The selected SVI model differs from its capability observation")
        result["video_model"] = deepcopy(model)
    return result


def bind_previous(run, previous):
    """A new attempt binds its own preceding producer; old checkpoints stay historical."""
    old = run.parameters
    retired = old.get("previous_motion_artifact_id")
    values = {
        key: value
        for key, value in old.items()
        if key
        not in {
            "previous_motion",
            "previous_motion_artifact_id",
            "svi_profile_identity",
            "previous_motion_run_id",
        }
    }
    values["parent_artifact_ids"] = [
        identity for identity in old.get("parent_artifact_ids", []) if identity != retired
    ]
    if previous is not None:
        values["previous_motion_run_id"] = previous.id
    run.parameters = values


def reusable_checkpoint(session, run, video):
    """Resume needs the retained latent checkpoint, not just a playable old MP4."""
    motion = session.get(Artifact, video.metadata_json.get("motion_context_artifact_id", ""))
    if (
        not available_artifact(motion, run.owner_id)
        or motion.run_id != run.id
        or motion.artifact_type != "document"
        or motion.metadata_json.get("role") != "svi_motion"
        or motion.metadata_json.get("context_frames") != 4
        or motion.metadata_json.get("profile_identity") != video.metadata_json.get("profile_identity")
        or video.id not in motion.parent_artifact_ids
        or type(motion.size_bytes) is not int
        or not 0 < motion.size_bytes <= 512 * 1024
    ):
        return False
    try:
        path = safe_join(get_settings().data_dir, motion.relative_path)
        return path.is_file() and path.stat().st_size == motion.size_bytes
    except (OSError, ValueError):
        return False


def create_svi_run(
    session, body, *, task=None, parent_run_id=None, observed_profile=None, _prepare_translation=True
):
    profile = observed_profile
    if profile is None:
        try:
            profile = RunnerClient().request("GET", "/v1/video/svi/capabilities")
        except (RunnerError, RunnerUnavailable):
            raise HTTPException(409, "Connect the Host Runner to inspect SVI video") from None
    managed = checked_profile(body, profile)
    parameters = {
        **body.model_dump(mode="json", exclude={"gpu", "image_artifact_id"}),
        **geometry({"width": body.width, "height": body.height}),
        "backend": "wan22-svi-pro-q4",
        "managed_runtime": profile.get("managed_runtime"),
        "managed_video_gpu_indices": profile.get("eligible_gpu_indices"),
        "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
    }
    parameters.update(managed)
    scope = getattr(session, "scope", None)
    owner = task.owner_id if task else scope.user_id if scope else None
    source = session.get(Artifact, str(body.image_artifact_id)) if body.image_artifact_id else None
    if (
        not available_artifact(source, owner)
        or source.artifact_type != "image"
        or source.mime_type not in {"image/png", "image/jpeg"}
        or not 0 < source.size_bytes <= 20 * 1024**2
        or not re.fullmatch(r"[a-f0-9]{64}", source.sha256 or "")
    ):
        raise HTTPException(422, "Choose an available original PNG/JPEG image for SVI")
    if parent_run_id:
        from app.vision_inputs import inspected_selection

        parent = session.get(Run, parent_run_id)
        if parent is None or parent.owner_id != owner:
            raise HTTPException(422, "The video parent is unavailable")
        try:
            inspected = inspected_selection(session, parent, read_bytes=False)
            if inspected is not None and [item["artifact_id"] for item in inspected] != [source.id]:
                raise ValueError("SVI original image differs from the inspected selection")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    parameters.update(
        image_artifact_id=source.id,
        image=descriptor(source),
        parent_artifact_ids=[source.id],
    )
    task = task or create_task(
        session, title=body.prompt[:80], prompt=body.prompt, capability="video.animate"
    )
    run = create_run(
        session,
        task,
        run_type="video",
        capability="video.animate",
        executor_type=NAME,
        parameters=parameters,
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": RAM_MIB},
        retry_class="inspect",
        parent_run_id=parent_run_id,
    )
    if _prepare_translation:
        from app.media_translation import enqueue_translation

        enqueue_translation(session, run, body.translation)
    return run
