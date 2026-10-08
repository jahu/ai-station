"""Immutable reviewed-commit requests; only Runner-owned task branches."""

import fcntl
import hashlib
import json
import os
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.codex_runs import codex_report
from ai_station_runner.config import get_settings
from ai_station_runner.cursor_runs import cursor_report
from ai_station_runner.gitinspect import git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.local_coding_runs import local_coding_report
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.worktrees import inspect_worktree, owned_path

PERMISSIONS = {"filesystem_read", "git_read", "git_write"}


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    source_run_id: UUID
    project_id: UUID
    review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    message: str = Field(min_length=1, max_length=2000)
    protected_branches: list[str] = Field(max_length=100)
    permissions: list[str] = Field(max_length=3)


def digest(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def directory(run_id):
    return owned_path(f"runtime/commit-runs/{UUID(run_id)}")


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 1100000:
        raise GitError("Commit request exceeds limit")
    value = json.loads(path.read_text())
    body = CommitRequest.model_validate(value["request"])
    report = value["review"]
    if (
        str(body.run_id) != run_id
        or set(body.permissions) != PERMISSIONS
        or digest(report) != body.review_digest
    ):
        raise GitError("Commit request ownership changed")
    return body, report


def start_commit(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Reviewed commits require filesystem_read, git_read and git_write")
    run_id = str(body.run_id)
    root = directory(run_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = root / "request.json"
        if request.exists():
            if load_request(run_id)[0] != body:
                raise GitError("Run already owns another commit request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError("Uncertain commit dispatch requires inspection") from exc
            if process["executor"] != "reviewed_commit":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already owns a process")
        source_id = str(body.source_run_id)
        source = manager.inspect(source_id)
        if source["executor"] == "codex_proposal":
            review = codex_report(manager, source_id)
        elif source["executor"] == "cursor_proposal":
            review = cursor_report(manager, source_id)
        elif source["executor"] == "local_proposal":
            review = local_coding_report(manager, source_id)
        else:
            raise GitError("A completed coding proposal is required")
        record = inspect_worktree(manager, review["worktree_run_id"])
        if (
            digest(review) != body.review_digest
            or review["project_id"] != str(body.project_id)
            or record["project_id"] != str(body.project_id)
            or record["branch"] != review["branch"]
            or record["branch"] in {*body.protected_branches, "main", "master"}
            or not review["files"]
        ):
            raise GitError("Review, ownership or protected-branch policy does not match")
        with request.open("x") as handle:
            os.chmod(request, 0o600)
            json.dump({"request": body.model_dump(mode="json"), "review": review}, handle)
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
            argv=[sys.executable, "-m", "ai_station_runner.commit_job", run_id],
            cwd=root,
            executor="reviewed_commit",
            env=env,
        )


def commit_report(manager, run_id):
    body, _ = load_request(run_id)
    process = manager.inspect(run_id)
    if (
        process["executor"] != "reviewed_commit"
        or process["alive"]
        or process.get("completion_pending")
        or process.get("exit_code") != 0
        or process["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Commit has no confirmed successful completion")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 64000:
        raise GitError("Commit report exceeds limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["source_run_id"] != str(body.source_run_id):
        raise GitError("Commit report ownership changed")
    return report
