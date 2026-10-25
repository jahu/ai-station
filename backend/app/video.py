"""Queued local Wan text/image video generation through the native Runner."""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.motion_artifacts import MotionArtifacts
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict
from app.video_schema import VideoRequest as VideoRequest

router = APIRouter(prefix="/api/video", tags=["video"])
DB = Annotated[Session, Depends(session_scope)]


def recommended_profile(profile, available_mib):
    standard = profile.get("memory_estimate_mib")
    bounded = any(
        row.get("id") == "bounded_11g" and row.get("available") and row.get("ram_mib") == 11264
        for row in profile.get("memory_profiles", [])
    )
    if (
        profile.get("available")
        and bounded
        and type(standard) in (int, float)
        and math.isfinite(standard)
        and standard > 11264
        and type(available_mib) in (int, float)
        and math.isfinite(available_mib)
        and 0 <= available_mib < standard + 1024
    ):
        return "bounded_11g"
    return "default"


@router.get("/capabilities")
def capabilities():
    try:
        runner = RunnerClient()
        profile = runner.request("GET", "/v1/video/capabilities")
        available = None
        if profile.get("available") and any(
            row.get("available") for row in profile.get("memory_profiles", [])
        ):
            try:
                available = (runner.hardware().get("memory") or {}).get("available_mib")
            except (RunnerError, RunnerUnavailable):
                pass
        return {**profile, "recommended_memory_profile": recommended_profile(profile, available)}
    except (RunnerError, RunnerUnavailable):
        return {
            "available": False,
            "backend": "wan2.2-5b",
            "reason": "Host Runner video integration is unavailable",
        }


def memory_reservation(body, observed_profile):
    if body.memory_profile == "default":
        return observed_profile.get("memory_estimate_mib", 16384)
    selected = next(
        (
            item
            for item in observed_profile.get("memory_profiles", [])
            if item.get("id") == body.memory_profile
        ),
        None,
    )
    if (
        not observed_profile.get("available")
        or not selected
        or not selected.get("available")
        or selected.get("ram_mib") != 11264
    ):
        raise HTTPException(409, "The reduced-RAM video profile is unavailable; refresh Video setup")
    return selected["ram_mib"]


def create_video_run(
    session, body, *, task=None, parent_run_id=None, observed_profile=None, _prepare_translation=True
):
    reservation = None
    if body.memory_profile != "default":
        observed_profile = capabilities() if observed_profile is None else observed_profile
        reservation = memory_reservation(body, observed_profile)
    source = None
    if body.image_artifact_id:
        source = session.get(Artifact, str(body.image_artifact_id))
        if (
            source is None
            or source.trashed_at is not None
            or source.artifact_type != "image"
            or source.mime_type not in {"image/png", "image/jpeg"}
        ):
            raise HTTPException(422, "Choose a PNG/JPEG first-frame image")
    task = task or create_task(
        session, title=body.prompt[:80], prompt=body.prompt, capability="video.generate"
    )
    parameters = {
        **body.model_dump(mode="json", exclude={"gpu", "image_artifact_id"}),
        "image_relative": source.relative_path if source else None,
        "parent_artifact_ids": [source.id] if source else [],
        "backend": "wan2.2-5b",
        "fps": 24,
        **(
            {"profile_observation": observed_profile["profile_observation"]}
            if reservation is not None
            else {}
        ),
    }
    from app.vision_inputs import pin_media_inputs

    pin_media_inputs(session, parent_run_id, parameters)
    run = create_run(
        session,
        task,
        run_type="video",
        capability="video.generate",
        executor_type="wan_video",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": reservation} if reservation is not None else {},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters=parameters,
    )
    if _prepare_translation:
        from app.media_translation import enqueue_translation

        enqueue_translation(session, run, body.translation)
    return run


@router.post("/runs", status_code=202)
def generate(body: VideoRequest, session: DB):
    observed = capabilities()
    if not observed["available"]:
        raise HTTPException(409, "Local video is unavailable; inspect Video setup before generating")
    run = create_video_run(session, body, observed_profile=observed)
    session.commit()
    return run_dict(run)


class VideoExecutor(MotionArtifacts, HostMediaExecutor):
    name = "wan_video"
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def validate_inputs(self, session, run):
        from app.media_translation import validate_media_translation

        validate_media_translation(session, run)
        if run.parameters.get("media_inputs"):
            from app.agent_media import verify_published_inputs

            verify_published_inputs(session, run)

    def _start(self, runner, run, allocated, output):
        strategy = run.parameters.get("continuation_strategy", "cached_latents_v1")
        if strategy not in ("cached_latents_v1", "last_frame_v1"):
            raise ValueError("Unknown frozen video continuation strategy")
        continuation = None
        motion = None
        if run.parameters.get("previous_video_run_id"):
            from sqlalchemy import select

            from app.db import session_factory
            from app.models import Run

            with session_factory()() as session:
                previous = session.get(Run, run.parameters["previous_video_run_id"])
                artifact = (
                    session.scalar(
                        select(Artifact).where(
                            Artifact.run_id == previous.id, Artifact.artifact_type == "video"
                        )
                    )
                    if previous and previous.status == "succeeded" and previous.task_id == run.task_id
                    else None
                )
                if not artifact or artifact.trashed_at is not None:
                    raise ValueError("Successful prior motion context is unavailable")
                motion = (
                    artifact.metadata_json.get("motion_context") if strategy == "cached_latents_v1" else None
                )
                if motion:
                    context = session.get(Artifact, artifact.metadata_json.get("motion_context_artifact_id"))
                    if not context or context.trashed_at is not None or context.run_id != previous.id:
                        raise ValueError("Restore the preceding motion checkpoint before continuing")
                continuation = {
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                }

        keys = (
            "prompt",
            "negative_prompt",
            "image_relative",
            "width",
            "height",
            "frames",
            "steps",
            "cfg",
            "seed",
        )
        return runner.request(
            "POST",
            "/v1/runs/video",
            {
                "run_id": run.id,
                **self.native_budget(run),
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **({"continuation": continuation} if continuation else {}),
                **({"continuation_frames": 1} if continuation and strategy == "last_frame_v1" else {}),
                **(
                    {"motion_context": {k: motion[k] for k in ("relative_path", "sha256", "size_bytes")}}
                    if motion
                    else {}
                ),
                **{key: run.parameters[key] for key in keys},
                **(
                    {"memory_profile": run.parameters["memory_profile"]}
                    if run.parameters.get("memory_profile")
                    else {}
                ),
                **({"image_relative": None} if continuation else {}),
                **(
                    {"profile_observation": run.parameters["profile_observation"]}
                    if run.parameters.get("profile_observation") is not None
                    else {}
                ),
            },
        )
