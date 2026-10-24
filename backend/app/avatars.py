"""Portrait and speech to an inspectable local avatar video Run."""

import math
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session

from app.avatar_schema import AvatarMemorySettings
from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.motion_artifacts import MotionArtifacts
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict

router = APIRouter(prefix="/api/avatars")


class AvatarRequest(AvatarMemorySettings):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    speech_text: str | None = Field(default=None, min_length=1, max_length=1000)
    image_artifact_id: UUID
    audio_artifact_id: UUID
    prompt: str = Field(default="A person speaking naturally, static camera.", min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    frames: Literal[17, 33, 49, 65, 81] = 81
    steps: int = Field(default=8, ge=4, le=30)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")


@router.get("/capabilities")
def capabilities():
    try:
        runner = RunnerClient()
        profile = runner.request("GET", "/v1/avatar/capabilities")
        recommended = "default"
        if profile.get("available") and any(
            row.get("id") == "bounded_11g" and row.get("available") and row.get("ram_mib") == 11264
            for row in profile.get("memory_profiles", [])
        ):
            try:
                available = (runner.hardware().get("memory") or {}).get("available_mib")
                if type(available) in (int, float) and math.isfinite(available) and 0 <= available < 17408:
                    recommended = "bounded_11g"
            except (RunnerError, RunnerUnavailable):
                pass
        return {**profile, "recommended_memory_profile": recommended}
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Host Runner avatar integration is unavailable"}


def memory_reservation(body, observed_profile=None):
    if body.memory_profile == "default":
        return 16384
    observed_profile = capabilities() if observed_profile is None else observed_profile
    if not observed_profile.get("available") or not any(
        row.get("id") == "bounded_11g" and row.get("available") and row.get("ram_mib") == 11264
        for row in observed_profile.get("memory_profiles", [])
    ):
        raise HTTPException(409, "The reduced-RAM avatar profile is unavailable; refresh Avatars setup")
    return 11264


def create_avatar_run(session, body, *, task=None, parent_run_id=None, observed_profile=None):
    reservation = memory_reservation(body, observed_profile) if body.memory_profile != "default" else None
    image = session.get(Artifact, str(body.image_artifact_id))
    audio = session.get(Artifact, str(body.audio_artifact_id))
    if image is None or image.artifact_type != "image" or image.mime_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(422, "Choose a PNG/JPEG portrait artifact")
    if audio is None or audio.artifact_type != "audio" or audio.mime_type != "audio/wav":
        raise HTTPException(422, "Choose a PCM WAV speech artifact")
    task = task or create_task(
        session, title=body.prompt[:80], prompt=body.prompt, capability="avatar.animate"
    )
    if body.speech_text is not None:
        from app.audio import SpeechRequest, create_audio_run

        speech = create_audio_run(
            session,
            SpeechRequest(text=body.speech_text, reference_artifact_id=body.audio_artifact_id, gpu=body.gpu),
            task=task,
            parent_run_id=parent_run_id,
        )
        speech.parameters = {
            **speech.parameters,
            "avatar_after_speech": body.model_dump(mode="json", exclude={"speech_text", "audio_artifact_id"}),
        }
        return speech
    return create_run(
        session,
        task,
        run_type="video",
        capability="avatar.animate",
        executor_type="echomimic",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        requested_resources={"ram_mib": reservation} if reservation is not None else {},
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            **body.model_dump(
                mode="json", exclude={"image_artifact_id", "audio_artifact_id", "gpu", "speech_text"}
            ),
            "image_relative": image.relative_path,
            "audio_relative": audio.relative_path,
            "parent_artifact_ids": [image.id, audio.id],
            "backend": "echomimic-v3",
        },
    )


@router.get("/runs/{run_id}/workflow")
def workflow(run_id: UUID, session: Annotated[Session, Depends(session_scope)]):
    from app.media_workflow import workflow_steps

    return workflow_steps(session, run_id, {"chatterbox", "echomimic"})


@router.post("/runs", status_code=202)
def generate(body: AvatarRequest, session: Annotated[Session, Depends(session_scope)]):
    run = create_avatar_run(session, body)
    session.commit()
    return run_dict(run)


class AvatarExecutor(MotionArtifacts, HostMediaExecutor):
    name = "echomimic"
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"
    motion_role = "echo_motion"
    motion_filename = "echo-motion.safetensors"

    def validate_inputs(self, session, run):
        if run.parameters.get("media_inputs"):
            from app.agent_media import verify_published_inputs

            verify_published_inputs(session, run)

    def _start(self, runner, run, allocated, output):
        previous_reference = None
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
                    if previous
                    and previous.status == "succeeded"
                    and previous.task_id == run.task_id
                    and previous.executor_type == self.name
                    else None
                )
                if not artifact or artifact.trashed_at is not None:
                    raise ValueError("Successful preceding avatar motion is unavailable")
                motion = artifact.metadata_json.get("motion_context")
                if motion:
                    context = session.get(Artifact, artifact.metadata_json.get("motion_context_artifact_id"))
                    if not context or context.trashed_at is not None or context.run_id != previous.id:
                        raise ValueError("Restore the preceding avatar motion checkpoint before continuing")
                previous_reference = {
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                }

        return runner.request(
            "POST",
            "/v1/runs/avatar",
            {
                "run_id": run.id,
                **self.native_budget(run),
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **(
                    {"memory_profile": run.parameters["memory_profile"]}
                    if run.parameters.get("memory_profile")
                    else {}
                ),
                **(
                    {"audio_window": run.parameters["audio_window"]}
                    if run.parameters.get("audio_window")
                    else {}
                ),
                **({"previous_video": previous_reference} if previous_reference else {}),
                **(
                    {
                        "motion_context": {
                            key: motion[key] for key in ("relative_path", "sha256", "size_bytes")
                        }
                    }
                    if motion
                    else {}
                ),
                **{
                    key: run.parameters[key]
                    for key in (
                        "image_relative",
                        "audio_relative",
                        "prompt",
                        "size",
                        "frames",
                        "steps",
                        "seed",
                    )
                },
            },
        )
