"""Bounded native Git job that removes only the recorded owned worktree."""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from ai_station_runner.gitinspect import BASE_CONFIG, Repository, git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.worktree_remove import directory, load_request
from ai_station_runner.worktrees import load_manifest, owned_path, save_manifest

TIMEOUT = 120


def _git(repository, *args):
    command = [
        "git",
        *BASE_CONFIG,
        *repository.options,
        "-C",
        str(repository.path),
        *args,
    ]
    try:
        return subprocess.run(command, env=git_environment(), timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        print("Worktree removal timed out; remaining data is preserved for inspection", file=sys.stderr)
        os.killpg(os.getpid(), signal.SIGKILL)
        raise


def _registered(repository, destination: Path) -> bool:
    listed = repository.read(["worktree", "list", "--porcelain"], check=False)
    if listed.returncode not in (0,):
        raise GitError("Could not list Git worktrees")
    known = set()
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            known.add(Path(line.removeprefix("worktree ")))
    return destination in known or destination.resolve() in known


def _write_report(run_id, report):
    path = directory(run_id) / "report.json"
    temporary = path.with_name("report.tmp")
    with temporary.open("x") as handle:
        os.chmod(temporary, 0o600)
        json.dump(report, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def execute(run_id: str) -> None:
    if os.getpgrp() != os.getpid():
        raise GitError("Worktree removal requires a separately owned process group")
    body = load_request(run_id)
    worktree_run_id = str(body.worktree_run_id)
    request_lock = owned_path(f"runtime/worktree-requests/{worktree_run_id}.lock")
    validation_lock = owned_path(f"runtime/validation-worktrees/{worktree_run_id}.lock")
    request_lock.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    validation_lock.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with request_lock.open("a") as reserved, validation_lock.open("a") as busy:
        os.chmod(request_lock, 0o600)
        os.chmod(validation_lock, 0o600)
        try:
            fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GitError("Worktree is in use; wait for the active operation") from exc
        fcntl.flock(reserved, fcntl.LOCK_EX)
        record = load_manifest(worktree_run_id)
        if (
            record["project_id"] != str(body.project_id)
            or record["repo_path"] != body.repo_path
            or record["run_id"] != worktree_run_id
        ):
            raise GitError("Worktree ownership changed")
        destination = owned_path(record["relative_path"])
        branch_present = False
        if record["state"] != "removed":
            if destination.is_symlink():
                raise GitError("Worktree path is a symlink; inspect instead of removing")
            record["state"] = "removing"
            record["removed_by_run_id"] = run_id
            save_manifest(record)
            repository = Repository(Path(record["repo_path"]), shared_group=True)
            if repository.read(["config", "--get", "core.worktree"], check=False).returncode != 1:
                raise GitError("Custom core.worktree configuration is not supported for removal")
            if (
                str(repository.path) != record["repo_path"]
                or str(repository.common_dir) != record["common_dir"]
            ):
                raise GitError("Source repository metadata changed")
            registered = _registered(repository, destination)
            if registered:
                result = _git(repository, "worktree", "remove", "--force", "--", str(destination))
                if result.returncode and (destination.exists() or destination.is_symlink()):
                    raise GitError("Git worktree removal failed; inspect remaining files")
            elif destination.exists():
                if destination.is_symlink() or not destination.is_dir():
                    raise GitError("Worktree path is not a removable owned directory")
                shutil.rmtree(destination)
            if destination.exists() or destination.is_symlink():
                raise GitError("Worktree directory still exists; inspect before repeating")
            _git(repository, "worktree", "prune")
            branch = record["branch"]
            if branch != f"ai/{record['run_id']}-workspace":
                raise GitError("Task branch does not match its owner")
            current = repository.read(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
            if current == branch:
                raise GitError("Refusing to delete a branch that is checked out")
            exists = repository.read(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
            branch_present = exists.returncode == 0
            if branch_present:
                result = _git(repository, "branch", "-D", "--", branch)
                if result.returncode:
                    raise GitError("Task branch could not be deleted; inspect the repository")
            record["state"] = "removed"
            save_manifest(record)
        report = {
            "run_id": run_id,
            "worktree_run_id": worktree_run_id,
            "project_id": record["project_id"],
            "branch": record["branch"],
            "relative_path": record["relative_path"],
            "repo_path": record["repo_path"],
            "branch_deleted": branch_present,
        }
        if not (directory(run_id) / "report.json").exists():
            _write_report(run_id, report)
        print(f"Removed worktree {record['relative_path']} and {record['branch']}", flush=True)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
