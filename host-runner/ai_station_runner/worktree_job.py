"""Bounded native Git job, launched only as an owned process-group leader."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from ai_station_runner.gitinspect import BASE_CONFIG, Repository, git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.worktrees import load_manifest, owned_path, save_manifest

TIMEOUT = 120


def prepare(run_id: str) -> None:
    if os.getpgrp() != os.getpid():
        raise GitError("Worktree preparation requires a separately owned process group")
    record = load_manifest(run_id)
    if record["state"] != "reserved":
        raise GitError("Worktree reservation is not available for preparation")
    repository = Repository(Path(record["repo_path"]), shared_group=True)
    if repository.read(["config", "--get", "core.worktree"], check=False).returncode != 1:
        raise GitError("Custom core.worktree configuration is not supported for preparation")
    if str(repository.path) != record["repo_path"] or str(repository.common_dir) != record["common_dir"]:
        raise GitError("Source repository metadata changed")
    destination = owned_path(record["relative_path"])
    if destination.exists():
        raise GitError("Worktree destination already exists")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    record["state"] = "preparing"
    save_manifest(record)
    command = [
        "git",
        *BASE_CONFIG,
        *repository.options,
        "-c",
        "submodule.recurse=false",
        "-c",
        "core.sparseCheckout=false",
        "-c",
        "worktree.guessRemote=false",
        "-C",
        str(repository.path),
        "worktree",
        "add",
        "--no-track",
        "-b",
        record["branch"],
        "--",
        str(destination),
        record["base_commit"],
    ]
    try:
        result = subprocess.run(command, env=git_environment(), timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        print(
            "Worktree preparation timed out; partial data is preserved for inspection",
            file=sys.stderr,
            flush=True,
        )
        # This job is the verified group leader; terminate its Git descendants too.
        os.killpg(os.getpid(), signal.SIGKILL)
        raise
    if result.returncode:
        raise GitError("Git worktree creation failed; inspect logs and any partial data")
    worktree = Repository(destination, shared_group=True)
    head = worktree.read(["rev-parse", "--verify", "HEAD"]).stdout.strip()
    if (
        worktree.branch() != record["branch"]
        or worktree.common_dir != repository.common_dir
        or head != record["base_commit"]
    ):
        raise GitError("Created worktree does not match its reservation")
    if repository.path == owned_path(f"projects/{record['project_id']}"):
        subprocess.run(
            [sys.executable, "-m", "venv", str(destination / ".venv")],
            env=git_environment(),
            timeout=90,
            check=True,
        )
    record["state"] = "ready"
    save_manifest(record)
    print(f"Worktree ready: {record['relative_path']} on {record['branch']}", flush=True)


if __name__ == "__main__":
    try:
        prepare(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
