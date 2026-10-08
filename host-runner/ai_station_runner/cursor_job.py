"""Managed Cursor proposal, checked application and preserved review evidence."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time

from ai_station_runner.coding_job import execute_proposal
from ai_station_runner.cursor_adapter import prepare_cursor, proposal_result
from ai_station_runner.cursor_runs import directory, load_request
from ai_station_runner.owned_children import stop_owned_children

TIMEOUT = 300


def collect_proposal(argv, env, cwd, *, parse=proposal_result, label="Cursor", stderr=True):
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
                        f"{label} exceeded time/output limit; inspect preserved worktree",
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
                        if stderr:
                            print(
                                chunk.decode("utf-8", errors="replace"), end="", file=sys.stderr, flush=True
                            )
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
                            if item.get("type") in {
                                "system",
                                "connection",
                                "retry",
                                "thread.started",
                                "turn.started",
                                "turn.completed",
                            }:
                                print(
                                    json.dumps(
                                        {
                                            key: item.get(key)
                                            for key in (
                                                "type",
                                                "subtype",
                                                "session_id",
                                                "thread_id",
                                                "model",
                                                "usage",
                                            )
                                        }
                                    ),
                                    flush=True,
                                )
            stop_owned_children()
            if buffer.strip():
                lines.append(json.loads(buffer))
            if process.wait() != 0:
                raise RuntimeError(f"{label} exited unsuccessfully; no proposal was applied")
    if invalid_event:
        raise ValueError(f"{label} returned invalid structured events; no changes applied")
    return parse(lines)


def execute(run_id):
    body = load_request(run_id)
    root = directory(run_id)

    def generate(selected):
        argv, env, workspace = prepare_cursor(
            root / "provider", prompt=body.prompt, selected=selected, guidance=body.guidance, model=body.model
        )
        return collect_proposal(argv, env, workspace)

    execute_proposal(run_id, body, root, generate, location="external")


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
