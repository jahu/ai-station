"""Typed Host Runner API. There is no arbitrary shell endpoint."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ai_station_runner import __version__, managed_image_job
from ai_station_runner.audio import AudioRequest, start_audio
from ai_station_runner.audio import capabilities as speech_capabilities
from ai_station_runner.avatar_prepare import router as avatar_setup_router
from ai_station_runner.avatars import AvatarRequest, start_avatar
from ai_station_runner.browser_runs import BrowserRequest
from ai_station_runner.codex_runs import CodexRequest, codex_report, start_codex
from ai_station_runner.coding import CodingUnavailable, build_argv
from ai_station_runner.coding_models import coding_models
from ai_station_runner.coding_sandbox import SandboxUnavailable
from ai_station_runner.config import get_settings
from ai_station_runner.cursor_runs import CursorRequest, cursor_report, start_cursor
from ai_station_runner.dependencies import DependencyRequest, dependency_report, start_dependencies
from ai_station_runner.diagnostics import collect_diagnostics
from ai_station_runner.discovery import scan
from ai_station_runner.effects_contract import EffectsRequest
from ai_station_runner.effects_prepare import router as effects_setup_router
from ai_station_runner.fish_contract import FishRequest
from ai_station_runner.fsops import list_dir, read_file, search_files, write_file
from ai_station_runner.github_read import GithubReadRequest
from ai_station_runner.gitinspect import diff, status, validate_repo
from ai_station_runner.gitops import (
    GitError,
    add_worktree,
    apply_diff,
    commit,
    create_pull_request,
    remove_worktree,
    run_project_command,
)
from ai_station_runner.gpu_processes import collect as collect_gpu_processes
from ai_station_runner.image_jobs_api import router as image_jobs_router
from ai_station_runner.image_setup import router as image_setup_router
from ai_station_runner.krea2 import KreaFile
from ai_station_runner.krea2_native import KreaRunRequest
from ai_station_runner.krea2_native import capabilities as krea_capabilities
from ai_station_runner.krea2_native import start as start_krea
from ai_station_runner.llama_runtime import router as llama_router
from ai_station_runner.local_coding_runs import LocalCodingRequest, local_coding_report, start_local_coding
from ai_station_runner.local_model import router as local_model_router
from ai_station_runner.media_compose import ComposeRequest, start_composition
from ai_station_runner.model_verify import VerifyModel, verify_model
from ai_station_runner.music import MusicRequest
from ai_station_runner.music import capabilities as music_capabilities
from ai_station_runner.music import start as start_music
from ai_station_runner.music_prepare import router as music_setup_router
from ai_station_runner.photo import PhotoCommandError, build_photo_argv, device_for
from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from ai_station_runner.project_plan import ProjectPlanRequest, inspect_project_plan
from ai_station_runner.project_setup import ProjectSetup, setup_report, start_setup
from ai_station_runner.publication import (
    PublicationRequest,
    publication_progress,
    publication_report,
    start_publication,
)
from ai_station_runner.publication_reconcile import ReconcileRequest, reconcile_report, start_reconcile
from ai_station_runner.python_runs import PythonRequest
from ai_station_runner.reviewed_commits import CommitRequest, commit_report, start_commit
from ai_station_runner.runtime_install import router as runtime_setup_router
from ai_station_runner.runtime_observation import observe
from ai_station_runner.security import PathBoundaryError, ensure_within, resolve_child
from ai_station_runner.site_preview_runs import PreviewAction, PreviewRequest
from ai_station_runner.sonic_jobs import WholeAvatarRequest
from ai_station_runner.source_identity import SOURCE_FINGERPRINT
from ai_station_runner.speech_prepare import router as speech_setup_router
from ai_station_runner.station_image import inspect_station_image
from ai_station_runner.tailnet_api import router as tailnet_router
from ai_station_runner.telemetry import collect
from ai_station_runner.timeline_contract import TimelineRequest
from ai_station_runner.transcription import TranscriptionRequest
from ai_station_runner.validation import ValidationRequest, start_validation, validation_report
from ai_station_runner.video import VideoRequest, start_video
from ai_station_runner.video import capabilities as video_capabilities
from ai_station_runner.video_prepare import router as video_setup_router
from ai_station_runner.worktree_remove import RemoveWorktreeRequest, remove_report, start_remove
from ai_station_runner.worktrees import inspect_worktree, reserve_and_start

app = FastAPI(title="AI Station Host Runner", version=__version__)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, error):
    # Validation input can contain entire private image payloads.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "loc": list(item["loc"]),
                    "type": item["type"],
                    "msg": "Invalid model message" if "messages" in item["loc"] else item["msg"],
                }
                for item in error.errors()
            ]
        },
    )


_manager: ProcessManager | None = None
_manager_lock = threading.Lock()


def manager() -> ProcessManager:
    global _manager
    settings = get_settings()
    with _manager_lock:
        if _manager is None:
            _manager = ProcessManager(settings.host_data_dir(), settings.cancel_grace_seconds)
    return _manager


def reset_manager() -> None:
    global _manager
    _manager = None


def canonical_id(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value


RunId = Annotated[str, AfterValidator(canonical_id)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhotoBody(RequestBody):
    run_id: RunId
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    backend: Literal["qwen", "juggernaut"] = "qwen"
    prompt: str = Field(default="", max_length=10000)
    prompt_style: Literal["pipeline", "prompt", "instruction"] = "pipeline"
    negative: str | None = Field(default=None, max_length=10000)
    edit_prompt: str = Field(default="", max_length=10000)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    steps: int | None = Field(default=None, ge=1, le=150)
    cfg: float | None = Field(default=None, ge=0, le=30, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    max_side: int | None = Field(default=None, ge=256, le=4096, multiple_of=32)
    repeats: Literal[1] = 1
    gpu: str = Field(pattern=r"^[0-9]{1,12}$")
    output_relative: str
    inputs: list[str] = Field(default_factory=list, max_length=8)
    model_file: KreaFile | None = None


class CodingBody(RequestBody):
    run_id: RunId
    executor: str
    workspace_relative: str
    prompt: str
    model: str = ""


class CancelBody(RequestBody):
    run_id: RunId


class PrepareWorktreeBody(RequestBody):
    run_id: RunId
    project_id: RunId
    repo_path: str = Field(min_length=1, max_length=1000)
    base_branch: str = Field(min_length=1, max_length=200)
    permissions: list[Literal["filesystem_read", "workspace_write", "git_read", "git_write"]] = Field(
        max_length=4
    )


@app.post("/v1/runs/worktree")
def prepare_worktree(body: PrepareWorktreeBody):
    if set(body.permissions) != {"filesystem_read", "workspace_write", "git_read", "git_write"}:
        raise HTTPException(403, "Worktree preparation permissions are required")
    try:
        record = reserve_and_start(manager(), **body.model_dump(exclude={"permissions"}))
    except GitError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.post("/v1/runs/validation")
def project_validation(body: ValidationRequest):
    try:
        record = start_validation(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, SandboxUnavailable, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/validation/{run_id}")
def project_validation_report(run_id: UUID):
    try:
        return validation_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/cursor-proposal")
def cursor_proposal(body: CursorRequest):
    try:
        record = start_cursor(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/cursor-proposal/{run_id}")
def cursor_proposal_report(run_id: UUID):
    try:
        return cursor_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/local-coding-proposal")
def local_coding_proposal(body: LocalCodingRequest):
    try:
        record = start_local_coding(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/local-coding-proposal/{run_id}")
def local_coding_proposal_report(run_id: UUID):
    try:
        return local_coding_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


class ModelScanBody(RequestBody):
    run_id: RunId
    permissions: list[Literal["filesystem_read", "manage_models"]] = Field(max_length=2)


@app.post("/v1/models/verify")
def verify_installed_model(body: VerifyModel):
    return verify_model(body)


@app.post("/v1/runs/model-scan")
def start_model_scan(body: ModelScanBody):
    if set(body.permissions) != {"filesystem_read", "manage_models"}:
        raise HTTPException(403, "Model discovery permissions are required")
    settings = get_settings()
    if not settings.model_roots.strip():
        raise HTTPException(409, "No model roots are configured")
    # Roots come exclusively from host configuration, never from the request.
    env = {
        **os.environ,
        "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
        "AI_STATION_MODEL_ROOTS": settings.model_roots,
        "PYTHONUNBUFFERED": "1",
    }
    try:
        record = manager().start(
            run_id=body.run_id,
            argv=[sys.executable, "-m", "ai_station_runner.discovery_job", body.run_id],
            cwd=settings.host_data_dir().resolve(),
            executor="model_discovery",
            env=env,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": settings.runner_id}


@app.get("/v1/worktrees/{run_id}")
def worktree_inspection(run_id: UUID):
    try:
        return inspect_worktree(manager(), str(run_id))
    except GitError as exc:
        raise HTTPException(409, str(exc)) from exc


class RepoBody(RequestBody):
    repo_path: str = Field(min_length=1, max_length=4096)


class DiffBody(RepoBody):
    base: str | None = Field(default=None, max_length=200)


class WorktreeBody(BaseModel):
    repo_path: str
    relative_path: str
    branch: str
    base_branch: str


class RemoveWorktreeBody(BaseModel):
    repo_path: str
    relative_path: str
    owned: bool = False


class CommitBody(BaseModel):
    repo_path: str
    branch: str
    protected: list[str] = Field(default_factory=list)
    message: str


class ApplyBody(BaseModel):
    repo_path: str
    diff: str


class PullRequestBody(BaseModel):
    repo_path: str
    branch: str
    base: str
    title: str
    body: str = ""


class CommandBody(BaseModel):
    repo_path: str
    argv: list[str]
    kind: str = "test"
    allowed: list[list[str]]


class FsBody(BaseModel):
    root: str
    path: str = "."
    content: str = ""
    query: str = ""


def _data() -> Path:
    return get_settings().host_data_dir()


def _guard(path: Path) -> Path:
    try:
        return ensure_within(path, get_settings().roots())
    except PathBoundaryError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _child(relative: str) -> Path:
    try:
        return resolve_child(_data(), relative)
    except PathBoundaryError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "source_fingerprint": SOURCE_FINGERPRINT,
        "runner_id": get_settings().runner_id,
        "data_dir": str(_data().resolve()),
    }


@app.get("/v1/hardware")
def hardware():
    return collect(_data())


@app.get("/v1/diagnostics")
def diagnostics():
    return collect_diagnostics(get_settings())


@app.get("/v1/gpu-processes")
def gpu_process_observation():
    return collect_gpu_processes()


@app.post("/v1/models/scan")
def models_scan():
    roots = []
    for raw in get_settings().model_roots.split(":"):
        if raw.strip():
            roots.append(_guard(Path(raw.strip())))
    return {"models": scan(roots)}


@app.get("/v1/photo/capabilities")
def photo_capabilities():
    settings = get_settings()
    if not any((settings.photo_python, settings.photo_script)):
        from ai_station_runner.image_setup import catalog

        report = catalog()
        source = report["recipe"]
        diffusion = next(item for item in source["inputs"] if item["role"] == "diffusion")
        return {
            "available": report["existing_images"]["available"],
            "configuration_present": False,
            "configuration_source": "managed",
            "backend": "photo_pipe",
            "modes": ["t2i", "img2img", "recompose", "upscale"],
            "backends": ["qwen"],
            "requires_gpu": True,
            "managed_image": {
                "profile": source["profile"],
                "manifest_sha256": source["model_manifest_sha256"],
                "gpu_count": 2,
                "eligible_gpu_indices": [
                    int(gpu["index"])
                    for gpu in (report["hardware"].get("gpus") or [])
                    if (gpu.get("memory_total_mib") or 0) >= 12288
                ],
                "diffusion_sha256": diffusion["sha256"],
                "diffusion_size_bytes": diffusion["size_bytes"],
            },
        }
    python = Path(settings.photo_python).expanduser() if settings.photo_python else None
    script = Path(settings.photo_script).expanduser() if settings.photo_script else None
    configured = bool(
        python and script and python.is_file() and os.access(python, os.X_OK) and script.is_file()
    )
    return {
        "available": configured and bool(collect(_data()).get("gpus")),
        "configuration_present": configured,
        "configuration_source": "configured",
        "backend": "photo_pipe",
        "modes": ["t2i", "img2img", "recompose", "upscale"],
        "backends": ["qwen", "juggernaut"],
        "prompt_profiles": {
            "t2i": ["pipeline", "prompt"],
            "img2img": ["pipeline", "instruction"],
            "recompose": ["pipeline", "instruction"],
            "upscale": ["pipeline"],
        },
        "requires_gpu": True,
    }


@app.post("/v1/runs/photo")
def start_photo(body: PhotoBody):
    settings = get_settings()
    if not settings.photo_python or not settings.photo_script:
        raise HTTPException(status_code=409, detail="photo_pipe is not configured")
    if body.model_file:
        from ai_station_runner.config import _split

        if body.backend != "qwen" or body.mode == "upscale":
            raise HTTPException(422, "This operation does not support a Qwen checkpoint override")
        try:
            model_path = ensure_within(Path(body.model_file.path), _split(settings.model_roots))
        except PathBoundaryError as exc:
            raise HTTPException(403, "Selected checkpoint is outside model roots") from exc
        if (
            str(model_path) != body.model_file.path
            or model_path.suffix != ".gguf"
            or not model_path.is_file()
            or model_path.stat().st_size != body.model_file.size
        ):
            raise HTTPException(422, "Selected checkpoint must match an existing canonical GGUF")
    expected = f"artifacts/{body.run_id[:2]}/{body.run_id[2:4]}/{body.run_id}.png"
    if body.output_relative != expected:
        raise HTTPException(422, "Output must be the run-owned artifact path")
    output = _child(body.output_relative)
    # Reject even internal symlink redirection into database/worktree storage.
    if output != _data().resolve() / expected:
        raise HTTPException(403, "Output path must not contain symlinks")
    if int(body.gpu) not in {int(gpu["index"]) for gpu in collect(_data()).get("gpus", [])}:
        raise HTTPException(422, "GPU is not present")
    if body.mode == "t2i" and body.inputs:
        raise HTTPException(422, "Generate does not accept inputs")
    inputs = []
    for relative in body.inputs:
        source = _child(relative)
        if not relative.startswith("artifacts/") or source != _data().resolve() / relative:
            raise HTTPException(403, "Input must be an artifact without symlink redirection")
        if not source.is_file():
            raise HTTPException(422, "Input image is missing")
        from PIL import Image

        try:
            with Image.open(source) as image:
                limit = 64 * 1024 * 1024 // (16 if body.mode == "upscale" else 1)
                if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > limit:
                    raise ValueError("Image exceeds supported size or format")
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "Invalid or oversized input image") from exc
        inputs.append(str(source))
    try:
        argv = build_photo_argv(
            settings.photo_python,
            settings.photo_script,
            mode=body.mode,
            backend=body.backend,
            prompt=body.prompt,
            negative=body.negative,
            edit_prompt=body.edit_prompt,
            width=body.width,
            height=body.height,
            steps=body.steps,
            cfg=body.cfg,
            seed=body.seed,
            max_side=body.max_side,
            repeats=body.repeats,
            device=device_for(body.gpu),
            output=str(output),
            inputs=inputs,
            prompt_style=body.prompt_style,
            model_snapshot=body.model_file.model_dump() if body.model_file else None,
        )
    except PhotoCommandError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    # photo_pipe.py maps --device cuda:N itself. Do not also set CUDA_VISIBLE_DEVICES here.
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    try:
        record = manager().start(
            run_id=body.run_id,
            argv=argv,
            cwd=_data(),
            executor="photo_pipe",
            env=environment,
            **({"deadline_at": body.deadline_at} if body.deadline_at is not None else {}),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record["runner_id"] = settings.runner_id
    return record


@app.post("/v1/runs/coding")
def start_coding(body: CodingBody):
    workspace = _child(body.workspace_relative)
    try:
        argv = build_argv(body.executor, str(workspace), body.prompt, body.model)
    except CodingUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = manager().start(run_id=body.run_id, argv=argv, cwd=workspace, executor=body.executor)
    record["runner_id"] = get_settings().runner_id
    return record


@app.get("/v1/process/{run_id}")
def inspect_process(
    run_id: RunId,
    stdout_offset: Annotated[int | None, Query(ge=0)] = None,
    stderr_offset: Annotated[int | None, Query(ge=0)] = None,
):
    if managed_image_job.owns(run_id):
        return managed_image_job.inspect(
            run_id, stdout_offset=stdout_offset or 0, stderr_offset=stderr_offset or 0
        )
    try:
        return manager().inspect(run_id, stdout_offset=stdout_offset, stderr_offset=stderr_offset)
    except ProcessNotOwned as exc:
        raise HTTPException(status_code=404, detail="Process is not owned by the runner") from exc


@app.post("/v1/process/cancel")
def cancel(body: CancelBody):
    if managed_image_job.owns(body.run_id):
        return managed_image_job.cancel(body.run_id, permissions=sorted(managed_image_job.PERMISSIONS))
    try:
        return manager().cancel(body.run_id)
    except ProcessNotOwned as exc:
        raise HTTPException(status_code=404, detail="Process is not owned by the runner") from exc


@app.post("/v1/git/validate")
def git_validate(body: RepoBody):
    try:
        return validate_repo(_guard(Path(body.repo_path)))
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/status")
def git_status(body: RepoBody):
    try:
        return status(_guard(Path(body.repo_path)))
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/diff")
def git_diff(body: DiffBody):
    try:
        return diff(_guard(Path(body.repo_path)), body.base)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/worktree")
def git_worktree(body: WorktreeBody):
    dest = _child(body.relative_path)
    try:
        return add_worktree(_guard(Path(body.repo_path)), dest, body.branch, body.base_branch)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/worktree/remove")
def git_worktree_remove(body: RemoveWorktreeBody):
    dest = _child(body.relative_path)
    try:
        return remove_worktree(_guard(Path(body.repo_path)), dest, owned=body.owned)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/commit")
def git_commit(body: CommitBody):
    try:
        return commit(_guard(Path(body.repo_path)), body.branch, body.protected, body.message)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/pr")
def git_pr(body: PullRequestBody):
    try:
        return create_pull_request(
            _guard(Path(body.repo_path)),
            body.branch,
            body.base,
            body.title,
            body.body,
        )
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/git/apply")
def git_apply(body: ApplyBody):
    try:
        return apply_diff(_guard(Path(body.repo_path)), body.diff)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/project/command")
def project_command(body: CommandBody):
    try:
        return run_project_command(_guard(Path(body.repo_path)), body.argv, body.allowed)
    except GitError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/fs/read")
def fs_read(body: FsBody):
    try:
        return read_file(_guard(Path(body.root)), body.path)
    except (FileNotFoundError, PathBoundaryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/fs/write")
def fs_write(body: FsBody):
    try:
        return write_file(_guard(Path(body.root)), body.path, body.content)
    except PathBoundaryError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/v1/fs/list")
def fs_list(body: FsBody):
    try:
        return list_dir(_guard(Path(body.root)), body.path)
    except (NotADirectoryError, PathBoundaryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/fs/search")
def fs_search(body: FsBody):
    try:
        return search_files(_guard(Path(body.root)), body.query)
    except (ValueError, PathBoundaryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/runtimes/observe")
def runtime_observations():
    try:
        return observe()
    except OSError as exc:
        raise HTTPException(503, "Host process metadata is unavailable") from exc


# Retain draft adapters for the next vertical slices, but do not expose writes
# that trust client-supplied ownership, command allowlists, or branch policies.
# These routes need durable runner-side authorization before activation.
_operational = {
    "/v1/runtimes/observe",
    "/v1/runs/model-scan",
    "/v1/models/verify",
    "/v1/runs/worktree",
    "/v1/runs/validation",
    "/v1/runs/local-coding-proposal",
    "/v1/local-coding-proposal/{run_id}",
    "/v1/runs/cursor-proposal",
    "/v1/cursor-proposal/{run_id}",
    "/v1/validation/{run_id}",
    "/v1/worktrees/{run_id}",
    "/v1/runs/photo",
    "/v1/photo/capabilities",
    "/health",
    "/v1/hardware",
    "/v1/gpu-processes",
    "/v1/diagnostics",
    "/v1/process/{run_id}",
    "/v1/process/cancel",
    "/v1/git/validate",
    "/v1/git/status",
    "/v1/git/diff",
}
app.router.routes = [
    route for route in app.router.routes if not route.path.startswith("/v1/") or route.path in _operational
]

# This router contains only the two validated local-model operations.
app.include_router(local_model_router)


app.include_router(llama_router)
app.include_router(runtime_setup_router)
app.include_router(speech_setup_router)
app.include_router(image_setup_router)
app.include_router(music_setup_router)
app.include_router(video_setup_router)
app.include_router(avatar_setup_router)
app.include_router(effects_setup_router)
app.include_router(image_jobs_router)


@app.get("/v1/krea2/capabilities")
def local_krea_capabilities():
    return krea_capabilities()


@app.post("/v1/runs/krea2")
def krea_run(body: KreaRunRequest):
    record = start_krea(manager(), body)
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/station-image")
def inspect_compose_image():
    return inspect_station_image()


@app.get("/v1/audio/capabilities")
def local_speech_capabilities():
    return speech_capabilities()


@app.post("/v1/runs/audio")
def audio_run(body: AudioRequest):
    try:
        return {**start_audio(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/runs/fish-speech")
def fish_speech_run(body: FishRequest):
    from ai_station_runner.fish_runtime import start

    try:
        return {**start(manager(), body), "runner_id": get_settings().runner_id}
    except (PermissionError, PathBoundaryError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/audio/effects/capabilities")
def effects_capabilities():
    from ai_station_runner.effects_runtime import capabilities

    return capabilities()


@app.post("/v1/runs/effects")
def effects_run(body: EffectsRequest):
    from ai_station_runner.effects_runtime import start

    try:
        return {**start(manager(), body), "runner_id": get_settings().runner_id}
    except (PermissionError, PathBoundaryError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/timeline/capabilities")
def timeline_capabilities():
    from ai_station_runner.timeline_runtime import capabilities

    return capabilities()


@app.post("/v1/runs/timeline")
def timeline_run(body: TimelineRequest):
    from ai_station_runner.timeline_runtime import start

    try:
        return {**start(manager(), body), "runner_id": get_settings().runner_id}
    except (PermissionError, PathBoundaryError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/music/capabilities")
def local_music_capabilities():
    return music_capabilities()


@app.post("/v1/runs/music")
def music_run(body: MusicRequest):
    try:
        return {**start_music(manager(), body), "runner_id": get_settings().runner_id}
    except (PermissionError, PathBoundaryError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/avatar/capabilities")
def avatar_capabilities():
    from ai_station_runner.avatars import capabilities

    return capabilities()


@app.post("/v1/runs/avatar")
def avatar_run(body: AvatarRequest):
    try:
        return {**start_avatar(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/avatar/whole-capabilities")
def whole_avatar_capabilities():
    from ai_station_runner.sonic_runtime import capabilities

    return capabilities()


@app.post("/v1/runs/whole-avatar")
def whole_avatar_run(body: WholeAvatarRequest):
    from ai_station_runner.sonic_runtime import start_whole_avatar

    try:
        return {**start_whole_avatar(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/runs/reviewed-commit")
def reviewed_commit(body: CommitRequest):
    try:
        return {**start_commit(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/runs/reviewed-commit/{run_id}/report")
def reviewed_commit_report(run_id: UUID):
    try:
        return commit_report(manager(), str(run_id))
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/runs/reviewed-commit/{run_id}/publication")
def inspect_publication(run_id: UUID):
    from ai_station_runner.publication import publication_preview

    try:
        return publication_preview(manager(), str(run_id))
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/github-publication")
def publish_github(body: PublicationRequest):
    try:
        return {**start_publication(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/github-publication/{run_id}/report")
def github_publication_report(run_id: UUID):
    try:
        return publication_report(manager(), str(run_id))
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/github-publication/{run_id}/progress")
def github_publication_progress(run_id: UUID):
    try:
        return publication_progress(str(run_id))
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/publication-reconcile")
def publication_reconcile_run(body: ReconcileRequest):
    try:
        return {**start_reconcile(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/publication-reconcile/{run_id}/report")
def publication_reconcile_report(run_id: UUID):
    try:
        return reconcile_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/codex-proposal")
def codex_proposal(body: CodexRequest):
    try:
        record = start_codex(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/codex-proposal/{run_id}")
def codex_proposal_report(run_id: UUID):
    try:
        return codex_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/projects/create")
def create_owned_project(body: ProjectSetup):
    try:
        return {**start_setup(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/projects/created/{run_id}")
def created_project(run_id: UUID):
    try:
        return setup_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/coding/models/{provider}")
def coding_model_catalog(provider: str):
    if provider not in {"cursor", "codex"}:
        raise HTTPException(404, "Coding provider not found")
    return coding_models(provider)


@app.post("/v1/worktrees/plan")
def project_preparation_plan(body: ProjectPlanRequest):
    try:
        return inspect_project_plan(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/dependencies")
def project_dependencies(body: DependencyRequest):
    try:
        record = start_dependencies(manager(), body)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, SandboxUnavailable, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**record, "runner_id": get_settings().runner_id}


@app.get("/v1/runs/dependencies/{run_id}/report")
def project_dependencies_report(run_id: UUID):
    try:
        return dependency_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/worktree-remove")
def worktree_remove_run(body: RemoveWorktreeRequest):
    try:
        return {**start_remove(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (GitError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/worktree-remove/{run_id}/report")
def worktree_remove_report(run_id: UUID):
    try:
        return remove_report(manager(), str(run_id))
    except (GitError, ProcessNotOwned, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/browser/capabilities")
def browser_capabilities():
    from ai_station_runner.browser_runs import capabilities

    return capabilities()


@app.post("/v1/runs/browser")
def browser_run(body: BrowserRequest):
    from ai_station_runner.browser_runs import start_browser

    try:
        return {**start_browser(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/browser/{run_id}/report")
def browser_report_endpoint(run_id: UUID):
    from ai_station_runner.browser_runs import browser_report

    try:
        return browser_report(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/video/capabilities")
def video_available():
    return video_capabilities()


@app.post("/v1/runs/video")
def video_run(body: VideoRequest):
    try:
        return {**start_video(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/runs/effects-preview")
def compose_effects_preview(body: ComposeRequest):
    try:
        return {
            **start_composition(manager(), body, effects_preview=True),
            "runner_id": get_settings().runner_id,
        }
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/runs/media-compose")
def compose_media(body: ComposeRequest):
    try:
        return {**start_composition(manager(), body), "runner_id": get_settings().runner_id}
    except PathBoundaryError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/runs/github-read")
def github_read_run(body: GithubReadRequest):
    from ai_station_runner.github_read import start

    try:
        return {**start(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError, ProcessNotOwned) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/github-read/{run_id}/report")
def github_read_report(run_id: UUID):
    from ai_station_runner.github_read import report

    try:
        return report(manager(), str(run_id))
    except (ValueError, OSError, ProcessNotOwned) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/transcription/capabilities")
def transcription_available():
    from ai_station_runner.transcription import capabilities

    return capabilities()


@app.post("/v1/runs/transcription")
def transcription_run(body: TranscriptionRequest):
    from ai_station_runner.transcription import start

    try:
        return {**start(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, OSError, ProcessNotOwned) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/transcription/{run_id}/report")
def transcription_report(run_id: UUID):
    from ai_station_runner.transcription import report

    try:
        return report(manager(), str(run_id))
    except (ValueError, OSError, ProcessNotOwned) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/python/capabilities")
def python_capabilities():
    from ai_station_runner.python_runs import capabilities

    return capabilities()


@app.post("/v1/runs/python")
def python_run(body: PythonRequest):
    from ai_station_runner.python_runs import start_python

    try:
        return {**start_python(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, RuntimeError, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/python/{run_id}/report")
def python_report_endpoint(run_id: UUID):
    from ai_station_runner.python_runs import python_report

    try:
        return python_report(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


# Internal preview operations stay unavailable until an explicit trusted image is configured.
@app.get("/v1/site-preview/capabilities")
def site_preview_capabilities():
    from ai_station_runner.site_preview_runs import capabilities

    return {**capabilities(), "runner_id": get_settings().runner_id}


@app.post("/v1/runs/site-preview")
def site_preview_run(body: PreviewRequest):
    from ai_station_runner.site_preview_runs import start_preview

    try:
        return {**start_preview(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, RuntimeError, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/site-preview/{run_id}/state")
def site_preview_state(run_id: UUID):
    from ai_station_runner.site_preview_runs import state

    try:
        return state(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/site-preview/{run_id}/report")
def site_preview_report(run_id: UUID):
    from ai_station_runner.site_preview_runs import report

    try:
        return report(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/site-preview-action")
def site_preview_action(body: PreviewAction):
    from ai_station_runner.site_preview_runs import start_action

    try:
        return {**start_action(manager(), body), "runner_id": get_settings().runner_id}
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, RuntimeError, OSError, GitError, ProcessNotOwned) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/runs/site-preview-action/{run_id}/report")
def site_preview_action_report(run_id: UUID):
    from ai_station_runner.site_preview_runs import action_report

    try:
        return action_report(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/runs/site-preview/{run_id}/close")
def site_preview_close(run_id: UUID):
    from ai_station_runner.site_preview_runs import close_preview

    try:
        return close_preview(manager(), str(run_id))
    except (ValueError, RuntimeError, ProcessNotOwned, OSError, GitError) as exc:
        raise HTTPException(409, str(exc)) from exc


app.include_router(tailnet_router)
