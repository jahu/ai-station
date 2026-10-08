"""Typed immutable Codex requests; no caller-selected host paths or commands."""

import fcntl
import json
import os
import shutil
import sys
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from ai_station_runner.config import get_settings
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.worktrees import inspect_worktree, owned_path

PERMISSIONS = {"filesystem_read", "workspace_write", "git_read", "external_ai"}


class CodexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    worktree_run_id: UUID
    prompt: str = Field(min_length=1, max_length=10000)
    guidance: str = Field(default="", max_length=32000)
    model: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._:/ -]*$")
    files: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=10
    )
    explore: StrictBool = False
    cumulative: StrictBool = False
    permissions: list[str] = Field(max_length=4)

    @model_validator(mode="after")
    def selection(self):
        if self.explore and self.files or not self.explore and not self.files:
            raise ValueError("Choose automatic file discovery or explicit source files")
        return self


def directory(run_id: str):
    if str(UUID(run_id)) != run_id:
        raise GitError("Canonical Codex Run UUID required")
    return owned_path(f"runtime/codex-runs/{run_id}")


def load_request(run_id: str):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 256000:
        raise GitError("Codex request exceeds its limit")
    body = CodexRequest.model_validate_json(path.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Codex request owner or permissions changed")
    return body


def start_codex(manager, body: CodexRequest):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Codex requires explicit external AI and workspace permissions")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = root / "request.json"
        if request.exists():
            if load_request(run_id) != body:
                raise GitError("Run already owns another Codex request")
            try:
                result = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain Codex dispatch requires inspection") from exc
            if result["executor"] != "codex_proposal":
                raise GitError("Run belongs to another executor")
            return result
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already has an owned process")
        record = inspect_worktree(manager, str(body.worktree_run_id))
        if record["state"] != "ready" or record["project_id"] != str(body.project_id):
            raise GitError("Codex requires this project's ready owned worktree")
        if not shutil.which("codex"):
            raise GitError("Codex CLI is unavailable")
        with request.open("x") as handle:
            os.chmod(request, 0o600)
            handle.write(body.model_dump_json())
        settings = get_settings()
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "XDG_CONFIG_HOME", "CODEX_HOME", "OPENAI_API_KEY")
            if key in os.environ
        }
        env.update(
            PYTHONPATH=os.pathsep.join(sys.path),
            PYTHONUNBUFFERED="1",
            AI_STATION_DATA_HOST_PATH=str(settings.host_data_dir().resolve()),
            AI_STATION_ALLOWED_ROOTS=":".join(str(p.resolve()) for p in settings.roots()),
            AI_STATION_MODEL_ROOTS="",
        )
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.codex_job", run_id],
            cwd=settings.host_data_dir().resolve(),
            executor="codex_proposal",
            env=env,
        )


def codex_report(manager, run_id):
    body = load_request(run_id)
    process = manager.inspect(run_id)
    if (
        process["executor"] != "codex_proposal"
        or process["alive"]
        or process.get("completion_pending")
        or process.get("exit_code") != 0
        or process["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Codex has no confirmed successful completion")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 1024 * 1024:
        raise GitError("Coding report exceeds its limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["worktree_run_id"] != str(body.worktree_run_id):
        raise GitError("Coding report ownership mismatch")
    return report
