"""Owned process wrapper; pip runs with a fixed native sandbox policy."""

import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ai_station_runner.coding_sandbox import dependency_policy, validation_argv, write_policy
from ai_station_runner.dependencies import directory, load_request
from ai_station_runner.dependency_manifest import confirm_public_indexes, load_specifiers, pip_plan
from ai_station_runner.gitinspect import Repository, git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.worktrees import load_manifest, owned_path

TIMEOUT = 600
OUTPUT_LIMIT = 2 * 1024 * 1024


def execute_command(argv, workspace, env, *, deadline):
    started = time.monotonic()
    size = 0
    with subprocess.Popen(
        argv, cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as proc:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, sys.stdout.buffer)
            selector.register(proc.stderr, selectors.EVENT_READ, sys.stderr.buffer)
            while selector.get_map() or proc.poll() is None:
                if time.monotonic() - started > TIMEOUT or time.monotonic() > deadline or size > OUTPUT_LIMIT:
                    print(
                        "Dependency install exceeded time/output limit; inspect logs",
                        file=sys.stderr,
                        flush=True,
                    )
                    os.killpg(os.getpid(), signal.SIGKILL)
                    raise RuntimeError("Dependency install limit reached")
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        size += len(chunk)
                        key.data.write(chunk)
                        key.data.flush()
            code = proc.wait()
    return {"exit_code": code, "duration_seconds": round(time.monotonic() - started, 3)}


def command_environment(scratch: Path) -> dict:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LANG": "C.UTF-8",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _environment(python: Path) -> None:
    if python.exists():
        if python.is_symlink():
            return
        if python.is_file():
            return
        raise GitError("Worktree Python environment is not a usable interpreter")
    print("Creating Python environment (no package downloads)", flush=True)
    subprocess.run(
        [sys.executable, "-m", "venv", str(python.parent.parent)],
        env=git_environment(),
        check=True,
        timeout=90,
    )
    if not python.is_file() and not python.is_symlink():
        raise GitError("Python environment was not created")


def install(run_id):
    if os.getpid() != os.getpgrp():
        raise RuntimeError("Dependency install requires a separately owned process group")
    body = load_request(run_id)
    record = load_manifest(str(body.worktree_run_id))
    workspace = owned_path(record["relative_path"])
    repository = Repository(workspace, shared_group=True)
    if (
        record["state"] != "ready"
        or record["project_id"] != str(body.project_id)
        or str(repository.common_dir) != record["common_dir"]
        or repository.branch() != record["branch"]
        or repository.read(["rev-parse", "HEAD"]).stdout.strip()
        != record.get("head_commit", record["base_commit"])
    ):
        raise RuntimeError("Worktree ownership changed before dependency install")
    lock_path = owned_path(f"runtime/validation-worktrees/{body.worktree_run_id}.lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = lock_path.open("a")
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise GitError("Worktree is in use; wait for the active operation") from exc
    venv = workspace / ".venv"
    python = venv / "bin/python"
    if venv.is_symlink():
        raise GitError("Worktree .venv must not be a symlink")
    if venv.exists() and not python.exists():
        raise GitError("Incomplete worktree .venv; inspect instead of replacing it")
    _environment(python)
    kind, specifiers = load_specifiers(workspace)
    plan = pip_plan(workspace, Path(".venv/bin/python"), specifiers)
    if plan["network"]:
        confirm_public_indexes()
    scratch = Path(tempfile.mkdtemp(prefix=".ai-station-dependencies-", dir=workspace))
    env = command_environment(scratch)
    policy_path = directory(run_id) / "policy.json"
    write_policy(
        policy_path,
        workspace,
        repository.common_dir,
        dependency_policy(workspace, repository.common_dir, network=plan["network"]),
    )
    print(f"Installing {len(plan['specifiers'])} requirements from {kind} ({plan['source']})", flush=True)
    result = execute_command(
        validation_argv(policy_path, plan["argv"]),
        workspace,
        env,
        deadline=time.monotonic() + TIMEOUT,
    )
    report = {
        "run_id": run_id,
        "project_id": str(body.project_id),
        "worktree_run_id": str(body.worktree_run_id),
        "manifest": kind,
        "source": plan["source"],
        "network": plan["network"],
        "specifiers": plan["specifiers"],
        "environment": f"{record['relative_path']}/.venv",
        "scratch_relative": str(scratch.relative_to(workspace)),
        **result,
    }
    path = directory(run_id) / "report.json"
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print("Dependency report saved", flush=True)


if __name__ == "__main__":
    try:
        install(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
