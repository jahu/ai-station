"""Explicit removal of an owned worktree. Callers cannot choose the destination."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.gitinspect import git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.worktrees import load_manifest, owned_path

PERMISSIONS = {"filesystem_read", "workspace_write", "git_read", "git_write"}


class RemoveWorktreeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    project_id: UUID
    worktree_run_id: UUID
    repo_path: str = Field(min_length=1, max_length=1000)
    permissions: list[str] = Field(max_length=4)


def directory(run_id):
    return owned_path(f"runtime/worktree-remove-runs/{UUID(run_id)}")


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 16384:
        raise GitError("Worktree removal request exceeds limit")
    value = json.loads(path.read_text())
    body = RemoveWorktreeRequest.model_validate(value["request"])
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Worktree removal ownership or permissions changed")
    return body


def start_remove(manager, body: RemoveWorktreeRequest):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Worktree removal permissions are required")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        os.chmod(root / "request.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "request.json"
        if path.exists():
            if load_request(run_id) != body:
                raise GitError("Run owns another worktree removal request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain worktree removal requires inspection") from exc
            if process["executor"] != "worktree_remove":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already owns a process")
        record = load_manifest(str(body.worktree_run_id))
        if (
            record["project_id"] != str(body.project_id)
            or record["repo_path"] != body.repo_path
            or record["run_id"] != str(body.worktree_run_id)
        ):
            raise GitError("Worktree ownership does not match this removal request")
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            json.dump({"request": body.model_dump(mode="json")}, handle)
        settings = get_settings()
        env = {
            **git_environment(),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "PYTHONUNBUFFERED": "1",
            "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
            "AI_STATION_ALLOWED_ROOTS": ":".join(str(p.resolve()) for p in settings.roots()),
            "AI_STATION_MODEL_ROOTS": "",
        }
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.worktree_remove_job", run_id],
            cwd=root,
            executor="worktree_remove",
            env=env,
        )


def remove_report(manager, run_id):
    body = load_request(run_id)
    process = manager.inspect(run_id)
    if (
        process["executor"] != "worktree_remove"
        or process["alive"]
        or process.get("completion_pending")
        or process.get("exit_code") != 0
        or process["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Worktree removal has no confirmed successful completion")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 16384:
        raise GitError("Worktree removal report exceeds limit")
    report = json.loads(path.read_text())
    if (
        report["run_id"] != run_id
        or report["worktree_run_id"] != str(body.worktree_run_id)
        or report["project_id"] != str(body.project_id)
    ):
        raise GitError("Worktree removal report ownership changed")
    return report
