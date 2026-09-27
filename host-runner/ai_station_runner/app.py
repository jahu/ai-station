"""Typed Host Runner API. There is no arbitrary shell endpoint."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ai_station_runner import __version__
from ai_station_runner.coding import CodingUnavailable, build_argv
from ai_station_runner.coding_sandbox import SandboxUnavailable
from ai_station_runner.config import get_settings
from ai_station_runner.cursor_runs import CursorRequest, cursor_report, start_cursor
from ai_station_runner.diagnostics import collect_diagnostics
from ai_station_runner.discovery import scan
from ai_station_runner.fsops import list_dir, read_file, search_files, write_file
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
from ai_station_runner.llama_runtime import router as llama_router
from ai_station_runner.local_model import router as local_model_router
from ai_station_runner.photo import PhotoCommandError, build_photo_argv, device_for
from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from ai_station_runner.runtime_observation import observe
from ai_station_runner.security import PathBoundaryError, ensure_within, resolve_child
from ai_station_runner.telemetry import collect
from ai_station_runner.validation import ValidationRequest, start_validation, validation_report
from ai_station_runner.worktrees import inspect_worktree, reserve_and_start

app = FastAPI(title="AI Station Host Runner", version=__version__)
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
    mode: Literal["t2i", "img2img", "recompose", "upscale"]
    backend: Literal["qwen", "juggernaut"] = "qwen"
    prompt: str = Field(default="", max_length=10000)
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


class ModelScanBody(RequestBody):
    run_id: RunId
    permissions: list[Literal["filesystem_read", "manage_models"]] = Field(max_length=2)


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
        "runner_id": get_settings().runner_id,
        "data_dir": str(_data().resolve()),
    }


@app.get("/v1/hardware")
def hardware():
    return collect(_data())


@app.get("/v1/diagnostics")
def diagnostics():
    return collect_diagnostics(get_settings())


@app.post("/v1/models/scan")
def models_scan():
    roots = []
    for raw in get_settings().model_roots.split(":"):
        if raw.strip():
            roots.append(_guard(Path(raw.strip())))
    return {"models": scan(roots)}


@app.post("/v1/runs/photo")
def start_photo(body: PhotoBody):
    settings = get_settings()
    if not settings.photo_python or not settings.photo_script:
        raise HTTPException(status_code=409, detail="photo_pipe is not configured")
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
        )
    except PhotoCommandError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    # photo_pipe.py maps --device cuda:N itself. Do not also set CUDA_VISIBLE_DEVICES here.
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    record = manager().start(
        run_id=body.run_id, argv=argv, cwd=_data(), executor="photo_pipe", env=environment
    )
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
    try:
        return manager().inspect(run_id, stdout_offset=stdout_offset, stderr_offset=stderr_offset)
    except ProcessNotOwned as exc:
        raise HTTPException(status_code=404, detail="Process is not owned by the runner") from exc


@app.post("/v1/process/cancel")
def cancel(body: CancelBody):
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
    "/v1/runs/worktree",
    "/v1/runs/validation",
    "/v1/runs/cursor-proposal",
    "/v1/cursor-proposal/{run_id}",
    "/v1/validation/{run_id}",
    "/v1/worktrees/{run_id}",
    "/v1/runs/photo",
    "/health",
    "/v1/hardware",
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
