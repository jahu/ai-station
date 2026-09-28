"""Portrait and speech to an inspectable local avatar video Run."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import session_scope
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact
from app.runs import create_run, create_task, run_dict

router = APIRouter(prefix="/api/avatars")


class AvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    image_artifact_id: UUID
    audio_artifact_id: UUID
    prompt: str = Field(default="A person speaking naturally, static camera.", min_length=1, max_length=2000)
    size: Literal[256, 384, 512] = 384
    frames: Literal[17, 33, 49, 65, 81] = 81
    steps: int = Field(default=8, ge=4, le=30)
    seed: int = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")


def create_avatar_run(session, body, *, task=None, parent_run_id=None):
    image = session.get(Artifact, str(body.image_artifact_id))
    audio = session.get(Artifact, str(body.audio_artifact_id))
    if image is None or image.artifact_type != "image" or image.mime_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(422, "Choose a PNG/JPEG portrait artifact")
    if audio is None or audio.artifact_type != "audio" or audio.mime_type != "audio/wav":
        raise HTTPException(422, "Choose a PCM WAV speech artifact")
    task = task or create_task(
        session, title=body.prompt[:80], prompt=body.prompt, capability="avatar.animate"
    )
    return create_run(
        session,
        task,
        run_type="video",
        capability="avatar.animate",
        executor_type="echomimic",
        permissions=["filesystem_read", "workspace_write"],
        requested_gpu=body.gpu,
        retry_class="inspect",
        parent_run_id=parent_run_id,
        parameters={
            **body.model_dump(mode="json", exclude={"image_artifact_id", "audio_artifact_id", "gpu"}),
            "image_relative": image.relative_path,
            "audio_relative": audio.relative_path,
            "parent_artifact_ids": [image.id, audio.id],
            "backend": "echomimic-v3",
        },
    )


@router.post("/runs", status_code=202)
def generate(body: AvatarRequest, session: Annotated[Session, Depends(session_scope)]):
    run = create_avatar_run(session, body)
    session.commit()
    return run_dict(run)


class AvatarExecutor(HostMediaExecutor):
    name = "echomimic"
    suffix = ".mp4"
    artifact_type = "video"
    mime_type = "video/mp4"

    def _start(self, runner, run, allocated, output):
        return runner.request(
            "POST",
            "/v1/runs/avatar",
            {
                "run_id": run.id,
                "gpu": int(allocated),
                "permissions": run.effective_permissions,
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
