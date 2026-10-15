"""Owned process wrapper; commands run with a fixed native sandbox policy."""

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

from ai_station_runner.build_archive import capture_build
from ai_station_runner.coding_sandbox import validation_argv, validation_policy, write_policy
from ai_station_runner.gitinspect import Repository
from ai_station_runner.owned_children import stop_owned_children
from ai_station_runner.project_manifests import verify_manifests
from ai_station_runner.validation import load_request, request_path
from ai_station_runner.worktrees import load_manifest, owned_path

TIMEOUT = 300
OUTPUT_LIMIT = 2 * 1024 * 1024


def execute_command(argv, workspace, env, *, deadline):
    started = time.monotonic()
    size = 0
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
                    print("Validation exceeded time/output limit; inspect logs", file=sys.stderr, flush=True)
                    # The wrapper is a verified group leader. Kill its descendants
                    # as well, including a command that leaves inherited pipes open.
                    os.killpg(os.getpid(), signal.SIGKILL)
                    raise RuntimeError("Validation limit reached")
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


def validate(run_id):
    if os.getpid() != os.getpgrp():
        raise RuntimeError("Validation requires a separately owned process group")
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
        raise RuntimeError("Worktree ownership changed before validation")
    lock_path = owned_path(f"runtime/validation-worktrees/{body.worktree_run_id}.lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = lock_path.open("a")
    os.chmod(lock_path, 0o600)
    # Keep the descriptor alive for the full job. Direct runner requests cannot
    # validate the same worktree concurrently even with different Run IDs.
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    verify_manifests(workspace, body.manifest_snapshot)
    scratch = Path(tempfile.mkdtemp(prefix=".ai-station-validation-", dir=workspace))
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    results = []
    deadline = time.monotonic() + 900
    for index, command in enumerate(body.commands):
        print(f"Validation {index + 1}/{len(body.commands)}: {command.kind} {command.argv!r}", flush=True)
        # The native helper consumes its policy file on startup. Each command
        # gets a fresh exclusive file outside the writable workspace; retain the
        # original request policy as audit evidence rather than reusing it.
        policy = request_path(run_id, "policy.json").with_name(f"{run_id}.{index}.policy.json")
        command_env = env
        command_argv = command.argv
        policy_body = validation_policy(workspace, repository.common_dir)
        if command.argv[0] in {"node", "npm"}:
            from ai_station_runner.node_runtime import node_runtime, runtime_policy

            runtime = node_runtime(workspace)
            command_env = runtime.environment(env)
            command_env["CI"] = "1"
            policy_body = runtime_policy(policy_body, runtime)
            command_argv = [
                str(runtime.node),
                *([str(runtime.npm)] if command.argv[0] == "npm" else []),
                *command.argv[1:],
            ]
        write_policy(policy, workspace, repository.common_dir, policy_body)
        result = execute_command(
            validation_argv(policy, command_argv), workspace, command_env, deadline=deadline
        )
        results.append({"kind": command.kind, "argv": command.argv, **result})
    report = {
        "run_id": run_id,
        "project_id": str(body.project_id),
        "worktree_run_id": str(body.worktree_run_id),
        "commands": results,
        "succeeded": all(result["exit_code"] == 0 for result in results),
        "scratch_relative": str(scratch.relative_to(workspace)),
    }
    build_path = request_path(run_id, "build.zip")
    if all(result["exit_code"] == 0 for result in results) and any(
        result["kind"] == "build" for result in results
    ):
        # A command can exit while a background helper retains workspace access.
        # Drain only this wrapper's verified session/group before reading output.
        stop_owned_children()
    exported = capture_build(workspace, build_path, results)
    if exported is not None:
        if exported["status"] == "ready":
            exported["relative_path"] = f"runtime/validation/{run_id}.build.zip"
        report["build_export"] = exported
    path = request_path(run_id, "report.json")
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print("Validation report saved", flush=True)


if __name__ == "__main__":
    try:
        validate(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
