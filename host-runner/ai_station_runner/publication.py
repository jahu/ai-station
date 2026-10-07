"""Reviewed GitHub publication requests, bound to an owned committed worktree."""

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
from ai_station_runner.gitinspect import Repository
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.reviewed_commits import commit_report
from ai_station_runner.worktrees import inspect_worktree, load_manifest, owned_path

PERMISSIONS = {"filesystem_read", "git_read", "git_write", "network_external"}
REPOSITORY = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}"


def github_repository(url):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)(" + REPOSITORY + r")/?", url)
    if not match:
        raise GitError("Origin must be a credential-free github.com HTTPS or SSH repository URL")
    name = match[1].removesuffix(".git")
    if name.split("/")[1] in {"", ".", ".."}:
        raise GitError("Invalid GitHub repository name")
    return name


class PublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    source_run_id: UUID
    project_id: UUID
    approval_id: UUID
    approved: Literal[True]
    repository: str = Field(pattern="^" + REPOSITORY + "$", max_length=140)
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    base: str = Field(min_length=1, max_length=200)
    protected_branches: list[str] = Field(max_length=100)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=20000)
    permissions: list[str] = Field(max_length=4)

    @field_validator("base")
    @classmethod
    def valid_base(cls, value):
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value)
            or ".." in value
            or "//" in value
            or value.endswith(("/", ".", ".lock"))
            or value in {"main", "master", "HEAD"}
        ):
            raise ValueError("Choose a non-production integration branch")
        return value

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("PR title must contain readable text")
        return value.strip()


def inspect_commit(report, *, shared_group=False):
    record = load_manifest(report["worktree_run_id"])
    repo = Repository(owned_path(record["relative_path"]), shared_group=shared_group)
    if (
        record["state"] != "ready"
        or record["project_id"] != report["project_id"]
        or record["branch"] != report["branch"]
        or repo.branch() != report["branch"]
        or not report["branch"].startswith("ai/")
        or str(repo.common_dir) != record["common_dir"]
        or record.get("head_commit") != report["commit"]
        or repo.read(["rev-parse", "HEAD"]).stdout.strip() != report["commit"]
    ):
        raise GitError("Committed task ownership or HEAD changed")
    origin = repo.read(["config", "--get", "remote.origin.url"], check=False).stdout.strip()
    repository = github_repository(origin)
    return repo, {
        "repository": repository,
        "branch": report["branch"],
        "commit": report["commit"],
        "project_id": report["project_id"],
        "worktree_run_id": report["worktree_run_id"],
    }


def publication_preview(manager, source_run_id):
    report = commit_report(manager, source_run_id)
    inspect_worktree(manager, report["worktree_run_id"])
    _, preview = inspect_commit(report)
    return {**preview, "github_cli_available": shutil.which("gh") is not None}


def directory(run_id):
    return owned_path(f"runtime/publication-runs/{UUID(run_id)}")


def load_request(run_id):
    path = directory(run_id) / "request.json"
    if path.stat().st_size > 256000:
        raise GitError("Publication request exceeds limit")
    value = json.loads(path.read_text())
    body = PublicationRequest.model_validate(value["request"])
    if str(body.run_id) != run_id or set(body.permissions) != PERMISSIONS:
        raise GitError("Publication ownership or permissions changed")
    return body, value["commit_report"]


def start_publication(manager, body):
    if set(body.permissions) != PERMISSIONS:
        raise PermissionError("Publication requires Git and explicit external-network permissions")
    if body.base in {*body.protected_branches, "main", "master"}:
        raise GitError("Publication cannot target a protected production branch")
    root = directory(str(body.run_id))
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (root / "request.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "request.json"
        if path.exists():
            if load_request(str(body.run_id))[0] != body:
                raise GitError("Run owns another publication request")
            try:
                process = manager.inspect(str(body.run_id))
            except ProcessNotOwned as exc:
                raise GitError("Uncertain publication requires inspection, not another push") from exc
            if process["executor"] != "github_publication":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(str(body.run_id))
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already owns a process")
        report = commit_report(manager, str(body.source_run_id))
        _, preview = inspect_commit(report)
        if (
            preview["repository"] != body.repository
            or preview["commit"] != body.commit
            or preview["project_id"] != str(body.project_id)
            or preview["branch"] in {*body.protected_branches, "main", "master"}
            or preview["branch"] == body.base
        ):
            raise GitError("Publication differs from the approved repository, commit or branch")
        if not shutil.which("gh"):
            raise GitError("GitHub CLI is unavailable")
        with path.open("x") as handle:
            os.chmod(path, 0o600)
            json.dump({"request": body.model_dump(mode="json"), "commit_report": report}, handle)
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
            argv=[sys.executable, "-m", "ai_station_runner.publication_job", str(body.run_id)],
            cwd=root,
            executor="github_publication",
            env=env,
        )


def publication_report(manager, run_id):
    body, _ = load_request(run_id)
    process = manager.inspect(run_id)
    if (
        process["executor"] != "github_publication"
        or process["alive"]
        or process.get("completion_pending")
        or process.get("exit_code") != 0
        or process["status"] in {"canceled", "interrupted"}
    ):
        raise GitError("Publication has no confirmed successful completion; inspect GitHub before retrying")
    path = directory(run_id) / "report.json"
    if path.stat().st_size > 32000:
        raise GitError("Publication report exceeds limit")
    report = json.loads(path.read_text())
    if report["run_id"] != run_id or report["source_run_id"] != str(body.source_run_id):
        raise GitError("Publication report ownership changed")
    return report


def publication_progress(run_id):
    load_request(run_id)
    path = directory(run_id) / "progress.json"
    if not path.exists():
        return {"run_id": run_id, "stage": "not_started"}
    if path.stat().st_size > 32000:
        raise GitError("Publication progress exceeds limit")
    value = json.loads(path.read_text())
    if value["run_id"] != run_id:
        raise GitError("Publication progress ownership changed")
    return value
