"""Runner-owned worktree reservations. Callers cannot choose destinations."""

import fcntl
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from ai_station_runner.config import get_settings
from ai_station_runner.gitinspect import Repository, git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.processes import ProcessManager, ProcessNotOwned
from ai_station_runner.security import PathBoundaryError, resolve_child


def owned_path(relative: str) -> Path:
    root = get_settings().host_data_dir().resolve()
    try:
        result = resolve_child(root, relative)
        if result != root / relative:
            raise PathBoundaryError("Symlink redirection is not allowed")
    except PathBoundaryError as exc:
        raise GitError("Worktree storage must stay at its owned path without symlink redirection") from exc
    return result


def manifest_path(run_id: str) -> Path:
    if str(UUID(run_id)) != run_id:
        raise GitError("Canonical Run UUID required")
    return owned_path(f"runtime/worktree-requests/{run_id}.json")


def load_manifest(run_id: str) -> dict:
    path = manifest_path(run_id)
    if not path.is_file():
        raise GitError("No worktree reservation exists for this Run")
    if path.stat().st_size > 16384:
        raise GitError("Invalid worktree reservation")
    record = json.loads(path.read_text())
    project_id = str(UUID(record["project_id"]))
    if (
        record["run_id"] != run_id
        or record["project_id"] != project_id
        or record["relative_path"] != f"worktrees/{project_id}/{run_id}"
        or record["branch"] != f"ai/{run_id}-workspace"
        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record["base_commit"])
        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record.get("head_commit", record["base_commit"]))
        or record["state"] not in {"reserved", "preparing", "ready", "removing", "removed"}
    ):
        raise GitError("Worktree reservation is inconsistent with its owner")
    return record


def save_manifest(record: dict) -> None:
    path = manifest_path(record["run_id"])
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.{uuid4()}.tmp")
    try:
        with temporary.open("x") as handle:
            os.chmod(temporary, 0o600)
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def reserve_and_start(
    manager: ProcessManager, *, run_id: str, project_id: str, repo_path: str, base_branch: str
) -> dict:
    if str(UUID(project_id)) != project_id:
        raise GitError("Canonical Project UUID required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", base_branch) or ".." in base_branch:
        raise GitError("Base must be a local branch name")
    path = manifest_path(run_id)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_path = owned_path(f"runtime/worktree-requests/{run_id}.lock")
    with lock_path.open("a") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = {
            "run_id": run_id,
            "project_id": project_id,
            "repo_path": repo_path,
            "base_branch": base_branch,
        }
        if path.exists():
            record = load_manifest(run_id)
            if any(record[key] != value for key, value in request.items()):
                raise GitError("Run already owns a different worktree request")
            try:
                process = manager.inspect(run_id)
            except ProcessNotOwned as exc:
                raise GitError(
                    "Worktree reservation has no recorded process; inspect before continuing"
                ) from exc
            if process["executor"] != "worktree_prepare":
                raise GitError("Run belongs to another executor")
            return process
        try:
            manager.inspect(run_id)
        except ProcessNotOwned:
            pass
        else:
            raise GitError("Run already belongs to a managed process")
        repository = Repository(Path(repo_path))
        if repository.read(["config", "--get", "core.worktree"], check=False).returncode != 1:
            raise GitError("Repositories with a custom core.worktree are not supported for preparation")
        if str(repository.path) != repo_path:
            raise GitError("Repository must match the registered canonical root")
        commit = repository.read(
            ["rev-parse", "--verify", "--end-of-options", f"refs/heads/{base_branch}^{{commit}}"]
        ).stdout.strip()
        relative = f"worktrees/{project_id}/{run_id}"
        destination = owned_path(relative)
        if destination.exists():
            raise GitError("Worktree destination already exists")
        branch = f"ai/{run_id}-workspace"
        exists = repository.read(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        if exists.returncode != 1:
            raise GitError("Task branch already exists or could not be inspected")
        record = {
            **request,
            "relative_path": relative,
            "branch": branch,
            "base_commit": commit,
            "common_dir": str(repository.common_dir),
            "state": "reserved",
        }
        save_manifest(record)
        settings = get_settings()
        env = {
            **git_environment(),
            "AI_STATION_DATA_HOST_PATH": str(settings.host_data_dir().resolve()),
            "AI_STATION_ALLOWED_ROOTS": ":".join(
                str(root.expanduser().resolve()) for root in settings.roots()
            ),
            "AI_STATION_MODEL_ROOTS": "",
            "PYTHONUNBUFFERED": "1",
        }
        return manager.start(
            run_id=run_id,
            argv=[sys.executable, "-m", "ai_station_runner.worktree_job", run_id],
            cwd=settings.host_data_dir().resolve(),
            executor="worktree_prepare",
            env=env,
        )


def inspect_worktree(manager: ProcessManager, run_id: str) -> dict:
    record = load_manifest(run_id)
    if record["state"] in {"removing", "removed"}:
        raise GitError("Owned worktree is no longer available")
    try:
        process = manager.inspect(run_id)
    except ProcessNotOwned as exc:
        raise GitError("Worktree has no recorded owner process") from exc
    if process["executor"] != "worktree_prepare":
        raise GitError("Worktree owner does not match the preparation executor")
    if record["state"] == "ready":
        destination = owned_path(record["relative_path"])
        worktree = Repository(destination)
        if (
            worktree.path != destination
            or str(worktree.common_dir) != record["common_dir"]
            or worktree.branch() != record["branch"]
            or worktree.read(["rev-parse", "--verify", "HEAD"]).stdout.strip()
            != record.get("head_commit", record["base_commit"])
        ):
            raise GitError("Prepared worktree no longer matches its ownership record")
    return record
