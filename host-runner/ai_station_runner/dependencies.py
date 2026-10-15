"""Immutable dependency-install requests for previously prepared worktrees."""

import fcntl
import json
import os
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.coding_sandbox import cursor_sandbox_binary
from ai_station_runner.config import get_settings
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.worktrees import inspect_worktree, owned_path

PERMISSIONS = {
    "filesystem_read",
    "workspace_write",
    "git_read",
    "shell_project_commands",
    "network_read",
}


class DependencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    worktree_run_id: UUID
    permissions: list[str] = Field(max_length=5)


def directory(run_id):
    return owned_path(f"runtime/dependency-runs/{UUID(run_id)}")


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 16384:
        raise GitError("Dependency request exceeds limit")
    body = DependencyRequest.model_validate_json(path.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Dependency request ownership or permissions changed")
    return body


def start_dependencies(manager, body: DependencyRequest):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Project dependency permissions are required")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        os.chmod(root / "request.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "request.json"
        if path.exists():
            if load_request(run_id) != body:
                raise GitError("Run already owns another dependency request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain dependency dispatch requires inspection") from exc
            if process["executor"] != "project_dependencies":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already belongs to a managed process")
        record = inspect_worktree(manager, str(body.worktree_run_id))
        if record["state"] != "ready" or record["project_id"] != str(body.project_id):
            raise GitError("Dependencies require a ready worktree belonging to this project")
        cursor_sandbox_binary()
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            handle.write(body.model_dump_json())
        settings = get_settings()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "PYTHONUNBUFFERED": "1",
            "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
            "AI_STATION_ALLOWED_ROOTS": ":".join(str(p.resolve()) for p in settings.roots()),
            "AI_STATION_MODEL_ROOTS": "",
            "AI_STATION_NODE_PREFIX": settings.node_prefix,
        }
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.dependency_job", run_id],
            cwd=settings.host_data_dir().resolve(),
            executor="project_dependencies",
            env=env,
        )


def dependency_report(manager, run_id: str) -> dict:
    body = load_request(run_id)
    process = manager.inspect(run_id)
    if process["executor"] != "project_dependencies" or process["alive"] or process.get("completion_pending"):
        raise GitError("Dependency process has not finished")
    if process["status"] in {"canceled", "interrupted"} or process.get("exit_code") != 0:
        raise GitError("Dependency install did not finish with a trustworthy report")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 256000:
        raise GitError("Dependency report exceeds its limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["worktree_run_id"] != str(body.worktree_run_id):
        raise GitError("Dependency report owner mismatch")
    return report
