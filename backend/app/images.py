"""Typed image intent, bounded uploads, and artifact delivery."""

import io
import tempfile
import warnings
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.config import get_settings
from app.db import session_scope
from app.models import Artifact, Run, Task
from app.paths import PathBoundaryError, safe_join
from app.permissions import permissions_for
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict
from app.serialize import artifact_dict

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(session_scope)]
MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 64 * 1024 * 1024
FORMATS = {"PNG": (".png", "image/png"), "JPEG": (".jpg", "image/jpeg"), "WEBP": (".webp", "image/webp")}


@router.get("/images/runs/{run_id}/workflow")
def image_workflow(run_id: UUID, session: DB):
    from app.media_workflow import workflow_steps

    return workflow_steps(session, run_id, {"photo_pipe", "wan_video"})


@router.post("/images/runs/{run_id}/retry", status_code=202)
def retry_image(run_id: UUID, session: DB):
    original = session.get(Run, str(run_id))
    if original is None:
        raise HTTPException(404, "Run not found")
    if original.executor_type != "photo_pipe" or original.status not in {"failed", "canceled", "interrupted"}:
        raise HTTPException(409, "Only finished unsuccessful image runs can be retried")
    session.commit()
    try:
        info = RunnerClient().inspect_process(original.id)
        if info.get("alive"):
            raise HTTPException(409, "The original process is still running")
    except RunnerUnavailable as exc:
        raise HTTPException(409, "Runner must be reachable before retrying") from exc
    except RunnerError as exc:
        if exc.status_code != 404:
            raise HTTPException(409, "Cannot confirm original process has stopped") from exc
    session.refresh(original)
    child = session.scalar(select(Run).where(Run.parent_run_id == original.id))
    if child is not None:
        raise HTTPException(409, "This run already has a retry; inspect that run instead")
    for relative in original.parameters.get("inputs", []):
        if not safe_join(get_settings().data_dir, relative).is_file():
            raise HTTPException(422, "A source image is missing")
    task = session.get(Task, original.task_id)
    retry = create_run(
        session,
        task,
        run_type="image",
        capability=original.capability,
        executor_type="photo_pipe",
        execution_target="host",
        parameters=original.parameters,
        requested_gpu=original.requested_gpu,
        requested_resources=original.requested_resources,
        permissions=original.effective_permissions,
        retry_class="safe",
        parent_run_id=original.id,
    )
    original.metadata_json = {**original.metadata_json, "retry_run_id": retry.id}
    session.commit()
    return run_dict(retry)


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    backend: Literal["qwen", "juggernaut"] = "qwen"
    prompt: str = Field(default="", max_length=10_000)
    negative: str | None = Field(default=None, max_length=10_000)
    edit_prompt: str = Field(default="", max_length=10_000)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    steps: int | None = Field(default=None, ge=1, le=150)
    cfg: float | None = Field(default=None, ge=0, le=30, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    max_side: int | None = Field(default=None, ge=256, le=4096, multiple_of=32)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]+)$", max_length=12)
    input_artifact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    upscale_result: StrictBool = False
    video_prompt: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("gpu")
    @classmethod
    def canonical_gpu(cls, value):
        return value if value == "auto" else str(int(value))

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "upscale" and self.upscale_result:
            raise ValueError("Upscale already enlarges its source; choose it only once")
        if self.video_prompt and (self.upscale_result or self.mode == "upscale"):
            raise ValueError("Choose one follow-up: Upscale or animation after generation/editing")
        count = len(self.input_artifact_ids)
        if self.mode == "t2i" and count:
            raise ValueError("Generate does not accept source images")
        if self.mode in {"img2img", "upscale"} and count != 1:
            raise ValueError("Edit and Upscale require exactly one source image")
        if self.mode == "recompose" and count < 1:
            raise ValueError("Recompose requires at least one reference image")
        if self.mode in {"t2i", "recompose"} and not self.prompt:
            raise ValueError("A prompt is required")
        if self.mode == "img2img" and not self.edit_prompt:
            raise ValueError("An edit instruction is required")
        if self.mode != "t2i" and self.backend != "qwen":
            raise ValueError("Backend selection applies only to Generate")
        if self.mode != "t2i" or self.backend != "juggernaut":
            if self.seed is not None or self.negative:
                raise ValueError("Seed and negative prompt are supported only by Juggernaut")
        if self.mode in {"t2i", "recompose"}:
            self.width = self.width or 832
            self.height = self.height or 1216
            self.steps = self.steps or (35 if self.mode == "t2i" else 30)
            self.cfg = self.cfg if self.cfg is not None else (5.0 if self.mode == "t2i" else 6.0)
        if self.mode == "img2img":
            self.max_side = self.max_side or 1216
            self.steps = self.steps or 30
            if (self.upscale_result or self.video_prompt) and self.max_side > 2048:
                raise ValueError("Edit follow-up requires a maximum side of at most 2048")
        if self.mode == "t2i" and self.backend == "juggernaut" and self.seed is None:
            self.seed = 42
        return self


def get_artifact(session: Session, artifact_id: UUID) -> Artifact:
    artifact = session.get(Artifact, str(artifact_id))
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    return artifact


@router.post("/images/runs", status_code=202)
def enqueue_image(body: ImageRequest, session: DB):
    if body.video_prompt:
        from app.video import capabilities

        if not capabilities()["available"]:
            raise HTTPException(409, "Local video needs setup before queuing an animated result")
    run = create_image_run(session, body)
    session.commit()
    return run_dict(run)


def create_image_run(session, body: ImageRequest, *, task=None, parent_run_id=None):
    parents = [get_artifact(session, item) for item in body.input_artifact_ids]
    for parent in parents:
        if parent.artifact_type != "image":
            raise HTTPException(422, "Source artifacts must be images")
        try:
            source = safe_join(get_settings().data_dir, parent.relative_path)
        except PathBoundaryError as exc:
            raise HTTPException(422, "Source image is outside artifact storage") from exc
        if not source.is_file():
            raise HTTPException(422, "Source image is missing from storage")
    if body.mode == "upscale":
        width = parents[0].metadata_json.get("width", 0)
        height = parents[0].metadata_json.get("height", 0)
        if not width or not height or width * height * 16 > MAX_PIXELS:
            raise HTTPException(422, "Upscale output must be at most 64 megapixels; use a smaller source")
    capability = {
        "t2i": "image.generate",
        "img2img": "image.edit",
        "recompose": "image.recompose",
        "upscale": "image.upscale",
    }[body.mode]
    prompt = body.edit_prompt if body.mode == "img2img" else body.prompt
    task = task or create_task(
        session, title=prompt[:80] or "Upscale image", prompt=prompt, capability=capability, intent="image"
    )
    parameters = body.model_dump(mode="json", exclude={"input_artifact_ids", "gpu"})
    parameters.update(
        inputs=[parent.relative_path for parent in parents],
        parent_artifact_ids=[parent.id for parent in parents],
        repeats=1,
    )
    run = create_run(
        session,
        task,
        run_type="image",
        capability=capability,
        executor_type="photo_pipe",
        execution_target="host",
        parameters=parameters,
        requested_gpu=body.gpu,
        requested_resources={"gpu": body.gpu},
        permissions=permissions_for("image_generation"),
        retry_class="safe",
        parent_run_id=parent_run_id,
    )
    return run


@router.post("/images/uploads", status_code=201)
def upload_image(session: DB, file: Annotated[UploadFile, File()]):
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Images must be at most 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS or image.width * image.height > MAX_PIXELS:
                    raise HTTPException(422, "Use PNG, JPEG, or WebP up to 64 megapixels")
                suffix, mime = FORMATS[image.format]
                metadata = {"width": image.width, "height": image.height, "source": "upload"}
                image.verify()
            # Some formats only check headers in verify(); decode before writing
            # any artifact so truncated payloads produce validation errors.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise HTTPException(422, "Invalid or oversized image") from exc
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
        temporary.write(data)
        temporary.flush()
        artifact = register_file(
            session,
            source=Path(temporary.name),
            artifact_type="image",
            mime_type=mime,
            original_filename=Path(file.filename or "image").name[:300],
            run_id=None,
            metadata=metadata,
        )
    session.commit()
    return artifact_dict(artifact)


@router.get("/artifacts/{artifact_id}")
def artifact_detail(artifact_id: UUID, session: DB):
    return artifact_dict(get_artifact(session, artifact_id))


def artifact_response(artifact: Artifact, *, thumbnail=False):
    relative = artifact.thumbnail_relative_path if thumbnail else artifact.relative_path
    try:
        path = safe_join(get_settings().data_dir, relative)
    except PathBoundaryError as exc:
        raise HTTPException(404, "Artifact file is unavailable") from exc
    if not path.is_file():
        raise HTTPException(404, "Artifact file is unavailable")
    is_image = artifact.artifact_type == "image" and artifact.mime_type in {
        item[1] for item in FORMATS.values()
    }
    return FileResponse(
        path,
        media_type="image/jpeg" if thumbnail else artifact.mime_type,
        filename=artifact.original_filename or path.name,
        content_disposition_type="inline"
        if is_image
        or (artifact.artifact_type == "audio" and artifact.mime_type == "audio/wav")
        or (artifact.artifact_type == "video" and artifact.mime_type == "video/mp4")
        else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/artifacts/{artifact_id}/file")
def artifact_file(artifact_id: UUID, session: DB):
    response = artifact_response(get_artifact(session, artifact_id))
    session.rollback()  # File delivery may outlive a short SQLite transaction.
    return response


@router.get("/artifacts/{artifact_id}/thumbnail")
def artifact_thumbnail(artifact_id: UUID, session: DB):
    response = artifact_response(get_artifact(session, artifact_id), thumbnail=True)
    session.rollback()
    return response
