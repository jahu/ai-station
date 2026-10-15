"""Immutable validation requests for previously prepared, runner-owned worktrees."""

import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.coding_sandbox import cursor_sandbox_binary, write_policy
from ai_station_runner.config import get_settings
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.project_manifests import ManifestSnapshot
from ai_station_runner.validation_environment import ValidationEnvironment
from ai_station_runner.worktrees import inspect_worktree, owned_path

PERMISSIONS = {"filesystem_read", "workspace_write", "git_read", "shell_project_commands"}


class ValidationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["test", "lint", "build"]
    argv: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def bounded_command(self):
        if any(any(ord(c) < 32 for c in arg) for arg in self.argv):
            raise ValueError("Control characters are not allowed in project commands")
        if Path(self.argv[0]).name in {"sh", "bash", "dash", "zsh", "fish", "sudo", "su"}:
            raise ValueError("Invoke a project executable directly, not a shell or privilege tool")
        if self.argv[0].startswith("-") or not self.argv[0].strip():
            raise ValueError("Project command requires an executable")
        return self


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    worktree_run_id: UUID
    commands: list[ValidationCommand] = Field(min_length=1, max_length=60)
    permissions: list[str] = Field(max_length=4)
    manifest_snapshot: ManifestSnapshot | None = None
    node_manifest_snapshot: ManifestSnapshot | None = None
    validation_environment: ValidationEnvironment | None = None

    @model_validator(mode="after")
    def bounded_request(self):
        if sum(len(arg) for cmd in self.commands for arg in cmd.argv) > 32000:
            raise ValueError("Project commands exceed the 32,000 character limit")
        if self.validation_environment:
            if self.manifest_snapshot is None:
                raise ValueError("Configured validation requires frozen manifests")
            if self.validation_environment.node_directory and self.node_manifest_snapshot is None:
                raise ValueError("Component validation requires frozen Node manifests")
        elif self.node_manifest_snapshot is not None:
            raise ValueError("Node component manifests require a validation environment")
        return self


def request_path(run_id: str, suffix: str = "json") -> Path:
    if str(UUID(run_id)) != run_id or suffix not in {
        "json",
        "lock",
        "policy.json",
        "report.json",
        "build.zip",
    }:
        raise GitError("Canonical validation owner required")
    return owned_path(f"runtime/validation/{run_id}.{suffix}")


def load_request(run_id: str) -> ValidationRequest:
    path = request_path(run_id)
    if path.stat().st_size > 256000:
        raise GitError("Invalid validation request")
    body = ValidationRequest.model_validate_json(path.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Validation request ownership or permissions changed")
    return body


def start_validation(manager, body: ValidationRequest) -> dict:
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Project validation permissions are required")
    run_id = str(body.run_id)
    path = request_path(run_id)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with request_path(run_id, "lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            if load_request(run_id) != body:
                raise GitError("Run already owns another validation request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain validation dispatch requires inspection") from exc
            if process["executor"] != "project_validation":
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
            raise GitError("Validation requires a ready worktree belonging to this project")
        cursor_sandbox_binary()  # Fail closed before reserving if helper is absent.
        workspace = owned_path(record["relative_path"])
        write_policy(request_path(run_id, "policy.json"), workspace, Path(record["common_dir"]))
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            handle.write(body.model_dump_json())
        settings = get_settings()
        # The orchestration process needs the installed Python package. The actual
        # project process gets a separate minimal environment inside the sandbox.
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
            argv=[sys.executable, "-m", "ai_station_runner.validation_job", run_id],
            cwd=settings.host_data_dir().resolve(),
            executor="project_validation",
            env=env,
        )


def validation_report(manager, run_id: str) -> dict:
    body = load_request(run_id)
    process = manager.inspect(run_id)
    if process["executor"] != "project_validation" or process["alive"] or process.get("completion_pending"):
        raise GitError("Validation process has not finished")
    if process["status"] in {"canceled", "interrupted"} or process.get("exit_code") != 0:
        raise GitError("Validation did not finish with a trustworthy report")
    path = request_path(run_id, "report.json")
    if path.stat().st_size > 256000:
        raise GitError("Validation report exceeds its limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["worktree_run_id"] != str(body.worktree_run_id):
        raise GitError("Validation report owner mismatch")
    return report
