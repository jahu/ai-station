"""Read-only GitHub snapshots through the operator's existing gh session."""

import fcntl
import json
import os
import re
import shutil
import sys
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_station_runner.config import get_settings
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.worktrees import owned_path

PERMISSIONS = {"network_read", "github_read"}


class GithubReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    repository: str = Field(min_length=3, max_length=140)
    operation: Literal["overview"] = "overview"
    permissions: list[str] = Field(max_length=2)

    @field_validator("repository")
    @classmethod
    def repository_name(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
            raise ValueError("Use a github.com owner/repository name")
        if value.split("/")[1] in {".", ".."} or value.endswith(".git"):
            raise ValueError("Use a repository name without .git")
        return value


def directory(run_id):
    return owned_path(f"runtime/github-read/{UUID(run_id)}")


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 4096:
        raise ValueError("GitHub request exceeds its limit")
    body = GithubReadRequest.model_validate_json(path.read_text())
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise ValueError("GitHub request ownership or permissions changed")
    return body


def start(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("GitHub reading requires explicit GitHub and network read permissions")
    if not shutil.which("gh"):
        raise ValueError("GitHub CLI is unavailable")
    root = directory(str(body.run_id))
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "request.json"
        if path.exists():
            if load_request(str(body.run_id)) != body:
                raise ValueError("Run owns another GitHub request")
            record = manager.inspect(str(body.run_id))
            if record["executor"] != "github_read":
                raise ValueError("Run belongs to another executor")
            return record
        try:
            manager.inspect(str(body.run_id))
        except ProcessNotOwned:
            pass
        else:
            raise ValueError("Run already owns a process")
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            handle.write(body.model_dump_json())
        settings = get_settings()
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "XDG_CONFIG_HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
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
            run_id=str(body.run_id),
            argv=[sys.executable, "-m", "ai_station_runner.github_read_job", str(body.run_id)],
            cwd=root,
            executor="github_read",
            env=env,
        )


def report(manager, run_id):
    body = load_request(run_id)
    record = manager.inspect(run_id)
    if (
        record["executor"] != "github_read"
        or record["alive"]
        or record.get("completion_pending")
        or record.get("exit_code") != 0
        or record["status"] in {"canceled", "interrupted"}
    ):
        raise ValueError("GitHub snapshot has no confirmed successful completion")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 256000:
        raise ValueError("GitHub snapshot exceeds its limit")
    value = json.loads(path.read_text())
    if value.get("run_id") != run_id or value.get("repository") != body.repository:
        raise ValueError("GitHub snapshot ownership changed")
    return value
