"""Managed Cursor proposal, checked application and preserved review evidence."""

import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import time

from ai_station_runner.coding_files import apply_proposal, parse_proposal, read_selected
from ai_station_runner.cursor_adapter import prepare_cursor, proposal_result
from ai_station_runner.cursor_runs import directory, load_request
from ai_station_runner.gitinspect import Repository
from ai_station_runner.owned_children import stop_owned_children
from ai_station_runner.worktrees import load_manifest, owned_path

TIMEOUT = 300


def collect_proposal(argv, env, cwd):
    lines = []
    invalid_event = False
    buffer = b""
    size = 0
    children_drained = False
    started = time.monotonic()
    with subprocess.Popen(
        argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map() or process.poll() is None:
                if time.monotonic() - started > TIMEOUT or size > 2 * 1024 * 1024:
                    print(
                        "Cursor exceeded time/output limit; inspect preserved worktree",
                        file=sys.stderr,
                        flush=True,
                    )
                    os.killpg(os.getpid(), signal.SIGKILL)
                if process.poll() is not None and not children_drained:
                    # Some CLI helpers outlive the main CLI or retain its pipes.
                    # Stop only this wrapper's verified group before waiting for EOF.
                    stop_owned_children()
                    children_drained = True
                for key, _ in selector.select(0.1):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if key.data == "stderr":
                        print(chunk.decode("utf-8", errors="replace"), end="", file=sys.stderr, flush=True)
                        continue
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if line.strip():
                            try:
                                item = json.loads(line)
                            except ValueError:
                                invalid_event = True
                                continue
                            if not isinstance(item, dict):
                                invalid_event = True
                                continue
                            if item.get("type") != "thinking":
                                lines.append(item)
                            if item.get("type") in {"system", "connection", "retry"}:
                                print(
                                    json.dumps(
                                        {
                                            key: item.get(key)
                                            for key in ("type", "subtype", "session_id", "model")
                                        }
                                    ),
                                    flush=True,
                                )
            stop_owned_children()
            if buffer.strip():
                lines.append(json.loads(buffer))
            if process.wait() != 0:
                raise RuntimeError("Cursor exited unsuccessfully; no proposal was applied")
    if invalid_event:
        raise ValueError("Cursor returned invalid structured events; no changes applied")
    return proposal_result(lines)


def execute(run_id):
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Cursor execution requires an owned process group")
    body = load_request(run_id)
    record = load_manifest(str(body.worktree_run_id))
    workspace = owned_path(record["relative_path"])
    repo = Repository(workspace, shared_group=True)
    if (
        record["state"] != "ready"
        or record["project_id"] != str(body.project_id)
        or str(repo.common_dir) != record["common_dir"]
        or repo.branch() != record["branch"]
        or repo.read(["rev-parse", "HEAD"]).stdout.strip() != record["base_commit"]
    ):
        raise ValueError("Worktree ownership changed")
    lock_path = owned_path(f"runtime/validation-worktrees/{body.worktree_run_id}.lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = lock_path.open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    selected = read_selected(workspace, body.files)
    argv, env, provider_workspace = prepare_cursor(
        directory(run_id) / "provider",
        prompt=body.prompt,
        selected=selected,
        guidance=body.guidance,
        model=body.model,
    )
    print(f"EXTERNAL Cursor proposal for {len(selected)} selected files; tools disabled", flush=True)
    text, provider = collect_proposal(argv, env, provider_workspace)
    proposal = parse_proposal(text, selected)
    # Recheck repository identity as well as every source file after inference.
    current = Repository(workspace, shared_group=True)
    if (
        current.common_dir != repo.common_dir
        or current.branch() != record["branch"]
        or current.read(["rev-parse", "HEAD"]).stdout.strip() != record["base_commit"]
    ):
        raise ValueError("Worktree changed while Cursor was running")
    report = apply_proposal(workspace, selected, proposal)
    report.update(
        run_id=run_id,
        project_id=str(body.project_id),
        worktree_run_id=str(body.worktree_run_id),
        branch=record["branch"],
        base_commit=record["base_commit"],
        provider=provider,
        execution_location="external",
    )
    path = directory(run_id) / "report.json"
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print(
        f"Applied {len(report['files'])} file replacements; review and validation still required", flush=True
    )


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
