"""Queued local Wan text/image video generation through the native Runner."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict

router = APIRouter(prefix="/api/video", tags=["video"])
DB = Annotated[Session, Depends(session_scope)]


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    image_artifact_id: UUID | None = None
    width: int = Field(default=1280, ge=128, le=1280, multiple_of=32)
    height: int = Field(default=704, ge=128, le=1280, multiple_of=32)
    frames: int = Field(default=49)
    steps: int = Field(default=20, ge=4, le=40)
    cfg: float = Field(default=5, ge=1, le=10, allow_inf_nan=False)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")

    @model_validator(mode="after")
    def bounds(self):
        if self.frames not in {17, 33, 49, 65, 81} or self.width * self.height > 1280 * 704:
            raise ValueError("Video frames or dimensions exceed the profile limit")
        return self


@router.get("/capabilities")
def capabilities():
    try:
        return RunnerClient().request("GET", "/v1/video/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {
            "available": False,
            "backend": "wan2.2-5b",
            "reason": "Host Runner video integration is unavailable",
        }


def create_video_run(session, body, *, task=None, parent_run_id=None):
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
    return create_run(
        session,
        task,
        run_type="video",
        capability="video.generate",
        executor_type="wan_video",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            **body.model_dump(mode="json", exclude={"gpu", "image_artifact_id"}),
            "image_relative": source.relative_path if source else None,
            "parent_artifact_ids": [source.id] if source else [],
            "backend": "wan2.2-5b",
            "fps": 24,
        },
    )


@router.post("/runs", status_code=202)
def generate(body: VideoRequest, session: DB):
    if not capabilities()["available"]:
        raise HTTPException(409, "Local video is unavailable; inspect Video setup before generating")
    run = create_video_run(session, body)
    session.commit()
    return run_dict(run)


class VideoExecutor(HostMediaExecutor):
    name = "wan_video"
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def _start(self, runner, run, allocated, output):
        continuation = None
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
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
                **({"continuation": continuation} if continuation else {}),
                **{key: run.parameters[key] for key in keys},
                **({"image_relative": None} if continuation else {}),
                **(
                    {"profile_observation": run.parameters["profile_observation"]}
                    if run.parameters.get("profile_observation") is not None
                    else {}
                ),
            },
        )
