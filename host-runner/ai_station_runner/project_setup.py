"""Managed, name-only project creation. No arbitrary paths or setup commands."""

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
from ai_station_runner.worktrees import owned_path

PERMISSIONS = {"workspace_write", "git_write"}


class ProjectSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    permissions: list[str] = Field(max_length=2)


def directory(run_id):
    return owned_path(f"runtime/project-setup/{UUID(run_id)}")


def start_setup(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Project creation requires workspace and Git write permissions")
    root = directory(str(body.run_id))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = root / "request.json"
        if request.exists():
            if ProjectSetup.model_validate_json(request.read_text()) != body:
                raise GitError("Run already owns a different project request")
            record = manager.inspect(str(body.run_id))
            if record["executor"] != "project_setup":
                raise GitError("Unexpected project owner")
            return record
        try:
            manager.inspect(str(body.run_id))
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already owns a process")
        if owned_path(f"projects/{body.project_id}").exists():
            raise GitError("Project destination already exists")
        with request.open("x") as handle:
            os.chmod(request, 0o600)
            handle.write(body.model_dump_json())
        settings = get_settings()
        env = {
            **git_environment(),
            "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
            "PYTHONPATH": os.pathsep.join(sys.path),
            "PYTHONUNBUFFERED": "1",
        }
        return manager.start(
            run_id=str(body.run_id),
            argv=[sys.executable, "-m", "ai_station_runner.project_setup_job", str(body.run_id)],
            cwd=settings.host_data_dir().resolve(),
            executor="project_setup",
            env=env,
        )


def setup_report(manager, run_id):
    record = manager.inspect(run_id)
    if (
        record["executor"] != "project_setup"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Project creation has no confirmed completion")
    body = ProjectSetup.model_validate_json((directory(run_id) / "request.json").read_text())
    report = json.loads((directory(run_id) / "report.json").read_text())
    if report["run_id"] != run_id or report["project_id"] != str(body.project_id):
        raise GitError("Project report ownership mismatch")
    return report
