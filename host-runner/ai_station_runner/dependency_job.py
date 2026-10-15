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
from ai_station_runner.dependency_manifest import (
    MAX_MANIFEST,
    _regular_file,
    confirm_public_indexes,
    load_specifiers,
    parse_pyproject,
    pip_plan,
)
from ai_station_runner.gitinspect import Repository, git_environment
from ai_station_runner.gitops import GitError
from ai_station_runner.project_manifests import verify_manifests
from ai_station_runner.validation_environment import component_directory
from ai_station_runner.worktrees import load_manifest, owned_path

TIMEOUT = 600
OUTPUT_LIMIT = 2 * 1024 * 1024


def execute_command(argv, workspace, env, *, deadline, capture=False):
    started = time.monotonic()
    size = 0
    output = {"stdout": bytearray(), "stderr": bytearray()}
    with subprocess.Popen(
        argv, cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as proc:
        # EOF on a pipe keeps this non-interactive. The native sandbox denies
        # fstat on inherited host device descriptors; Node aborts on /dev/null.
        proc.stdin.close()
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
                        if capture:
                            stream = "stdout" if key.fileobj is proc.stdout else "stderr"
                            output[stream].extend(chunk)
                        else:
                            key.data.write(chunk)
                            key.data.flush()
            code = proc.wait()
    result = {"exit_code": code, "duration_seconds": round(time.monotonic() - started, 3)}
    if capture:
        result.update({name: data.decode("utf-8", errors="replace") for name, data in output.items()})
    return result


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


def node_project(workspace):
    requirements, pyproject = workspace / "requirements.txt", workspace / "pyproject.toml"
    if requirements.exists() or requirements.is_symlink():
        return False
    if pyproject.exists() or pyproject.is_symlink():
        path = _regular_file(workspace, pyproject)
        if path.stat().st_size > MAX_MANIFEST:
            raise GitError("Python dependency manifest exceeds its size limit")
        if parse_pyproject(path.read_text()):
            return False
    return (workspace / "package.json").exists() or (workspace / "package.json").is_symlink()


def install(run_id):
    if os.getpid() != os.getpgrp():
        raise RuntimeError("Dependency install requires a separately owned process group")
    body = load_request(run_id)
    record = load_manifest(str(body.worktree_run_id))
    workspace = owned_path(record["relative_path"])
    worktree_root = workspace
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
    workspace = component_directory(worktree_root, body.directory)
    verify_manifests(workspace, body.manifest_snapshot, python_manifest=body.python_manifest)
    if body.ecosystem == "node" or body.ecosystem == "auto" and node_project(workspace):
        install_node(run_id, body, record, workspace, repository, worktree_root=worktree_root)
        return
    venv = workspace / ".venv"
    python = venv / "bin/python"
    if venv.is_symlink():
        raise GitError("Worktree .venv must not be a symlink")
    if venv.exists() and not python.exists():
        raise GitError("Incomplete worktree .venv; inspect instead of replacing it")
    _environment(python)
    kind, specifiers = load_specifiers(workspace, manifest=body.python_manifest)
    plan = pip_plan(workspace, Path(".venv/bin/python"), specifiers)
    if plan["network"]:
        confirm_public_indexes()
    scratch = Path(tempfile.mkdtemp(prefix=".ai-station-dependencies-", dir=worktree_root))
    env = command_environment(scratch)
    policy_path = directory(run_id) / "policy.json"
    write_policy(
        policy_path,
        worktree_root,
        repository.common_dir,
        dependency_policy(worktree_root, repository.common_dir, network=plan["network"]),
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
        "environment": f"{record['relative_path']}"
        + (f"/{body.directory}" if body.directory != "." else "")
        + "/.venv",
        "scratch_relative": str(scratch.relative_to(worktree_root)),
        **result,
    }
    path = directory(run_id) / "report.json"
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print("Dependency report saved", flush=True)


def install_node(run_id, body, record, workspace, repository, *, worktree_root=None):
    from ai_station_runner.node_dependencies import confirm_registry, package_manifest, verify_lock
    from ai_station_runner.node_lock import generate_lock
    from ai_station_runner.node_runtime import node_runtime, runtime_policy

    worktree_root = worktree_root or workspace
    parent = workspace.parent
    while parent.is_relative_to(worktree_root):
        for name in (".npmrc", "npm-shrinkwrap.json"):
            candidate = parent / name
            if candidate.exists() or candidate.is_symlink():
                raise GitError(
                    "Ancestor npm configuration overrides are not supported for component installs"
                )
        if parent == worktree_root:
            break
        parent = parent.parent
    manifest = package_manifest(workspace)
    runtime = node_runtime(worktree_root)
    deadline = time.monotonic() + TIMEOUT
    lock_exists = (workspace / "package-lock.json").exists() or (workspace / "package-lock.json").is_symlink()
    lock_info = verify_lock(workspace, manifest) if lock_exists else None
    confirm_registry()
    scratch = Path(tempfile.mkdtemp(prefix=".ai-station-dependencies-", dir=worktree_root))
    for name in ("user.npmrc", "global.npmrc"):
        (scratch / name).touch(mode=0o600)
    env = runtime.environment(command_environment(scratch))
    if workspace != worktree_root:
        env["npm_config_workspaces"] = "false"
    versions = runtime.describe(env)
    resolution = {"lock_generated": False}
    if not lock_exists:
        resolution = generate_lock(
            workspace,
            repository.common_dir,
            runtime,
            scratch,
            env,
            execute_command,
            deadline=deadline,
            policy_dir=directory(run_id),
            **({"policy_workspace": worktree_root} if workspace != worktree_root else {}),
        )
        lock_info = verify_lock(workspace, manifest)
    if (
        package_manifest(workspace)["package_sha256"] != manifest["package_sha256"]
        or verify_lock(workspace, manifest) != lock_info
    ):
        raise GitError("Node manifests changed during dependency preparation")
    policy = directory(run_id) / "npm.policy.json"
    write_policy(
        policy,
        worktree_root,
        repository.common_dir,
        runtime_policy(dependency_policy(worktree_root, repository.common_dir, network=True), runtime),
    )
    print("Managed npm ci: lifecycle scripts disabled", flush=True)
    result = execute_command(
        validation_argv(policy, runtime.argv("ci", workspace, scratch)),
        workspace,
        env,
        deadline=deadline,
    )
    report = {
        "run_id": run_id,
        "project_id": str(body.project_id),
        "worktree_run_id": str(body.worktree_run_id),
        "ecosystem": "node",
        "manifest": "package-lock.json",
        "source": "npm",
        "network": True,
        "specifiers": manifest["specifiers"],
        "environment": f"{record['relative_path']}"
        + (f"/{body.directory}" if body.directory != "." else "")
        + "/node_modules",
        "directory": body.directory,
        "scratch_relative": str(scratch.relative_to(worktree_root)),
        "package_sha256": manifest["package_sha256"],
        **lock_info,
        **versions,
        "lifecycle_scripts": False,
        **resolution,
        **result,
    }
    with (directory(run_id) / "report.json").open("x") as handle:
        os.chmod(handle.name, 0o600)
        json.dump(report, handle)
    print("Node dependency report saved", flush=True)


if __name__ == "__main__":
    try:
        install(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
