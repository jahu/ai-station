"""Owned Python container wrapper: bounded protocol, no host-writable mounts."""

import asyncio
import base64
import csv
import fcntl
import hashlib
import io
import json
import os
import sys
from contextlib import suppress
from pathlib import PurePosixPath

from ai_station_runner.python_protocol import MAX_FILE, MAX_LINE, MAX_LOG, MAX_OUTPUT_TOTAL
from ai_station_runner.python_runs import (
    PythonRequest,
    container_identity,
    directory,
    docker,
    inspect_container,
    load_request,
    save,
    stop_container,
)


def create_container(run_id, saved):
    root = directory(run_id)
    with (root / "container.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (root / "cancel.json").exists():
            raise InterruptedError("Python canceled before container creation")
        manifest = root / "container.json"
        if manifest.exists():
            raise ValueError("Python container dispatch is never replayed")
        name, labels = container_identity(saved)
        save(manifest, {"state": "creating", "id": None})
        args = ["create", "--pull", "never", "--name", name]
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        mount = io.StringIO()
        csv.writer(mount, lineterminator="").writerow(
            ["type=bind", f"src={root / 'inputs'}", "dst=/inputs", "readonly"]
        )
        args += [
            "--interactive",
            "--init",
            "--network",
            "none",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "512m",
            "--memory-swap",
            "512m",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=128:128",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--tmpfs",
            "/outputs:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--mount",
            mount.getvalue(),
            saved["image"],
        ]
        cid = docker(args)
        item = inspect_container(saved, cid)
        if item is None:
            raise ValueError("Python container creation identity could not be confirmed")
        save(manifest, {"state": "created", "id": item["Id"]})
        if (root / "cancel.json").exists():
            raise InterruptedError("Python canceled before execution")
        return item["Id"]


async def read_stderr(stream):
    data = bytearray()
    while chunk := await stream.read(8192):
        if len(data) < 16384:
            data.extend(chunk[: 16384 - len(data)])
    return data.decode("utf-8", errors="replace")


def collect_output(run_id, body, payload, collected):
    if set(payload) != {"event", "name", "data"} or not isinstance(payload["data"], str):
        raise ValueError("Invalid Python output envelope")
    name = payload["name"]
    if len(collected) >= len(body.expected_outputs) or name != body.expected_outputs[len(collected)]:
        raise ValueError("Unexpected or duplicate Python output")
    data = base64.b64decode(payload["data"], validate=True)
    if len(data) > MAX_FILE or sum(item["size_bytes"] for item in collected) + len(data) > MAX_OUTPUT_TOTAL:
        raise ValueError("Python output exceeds its size limit")
    root = directory(run_id)
    suffix = PurePosixPath(name).suffix.lower()
    if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
        suffix = ".bin"
    relative = f"runtime/python/{run_id}/output-{len(collected)}{suffix}"
    destination = root / f"output-{len(collected)}{suffix}"
    with destination.open("xb") as handle:
        os.chmod(handle.fileno(), 0o600)
        handle.write(data)
    collected.append(
        {
            "name": name,
            "relative_path": relative,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )


async def execute(run_id):
    saved = load_request(run_id)
    body = PythonRequest.model_validate(saved["request"])
    proc = None
    stderr_task = None
    try:
        cid = create_container(run_id, saved)
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            "--interactive",
            cid,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_LINE + 1,
        )
        stderr_task = asyncio.create_task(read_stderr(proc.stderr))
        outputs = []
        result = None
        log_size = 0
        async with asyncio.timeout(body.maximum_runtime + 20):
            request = {
                "maximum_runtime": body.maximum_runtime,
                "expected_outputs": body.expected_outputs,
                "inputs": {item.filename: "/inputs/" + item.filename for item in body.inputs},
            }
            proc.stdin.write((json.dumps(request) + "\n").encode())
            await proc.stdin.drain()
            proc.stdin.close()
            while line := await proc.stdout.readline():
                if len(line) > MAX_LINE:
                    raise ValueError("Python protocol line exceeds its limit")
                payload = json.loads(line)
                if not isinstance(payload, dict) or result is not None:
                    raise ValueError("Invalid or duplicate Python completion")
                event = payload.get("event")
                if event in {"stdout", "stderr"}:
                    if set(payload) != {"event", "text"} or not isinstance(payload["text"], str):
                        raise ValueError("Invalid Python log envelope")
                    log_size += len(payload["text"].encode("utf-8"))
                    if log_size > MAX_LOG:
                        raise ValueError("Python logs exceed their size limit")
                    print(
                        payload["text"],
                        end="",
                        file=sys.stdout if event == "stdout" else sys.stderr,
                        flush=True,
                    )
                elif event == "output":
                    collect_output(run_id, body, payload, outputs)
                elif event == "result":
                    if (
                        set(payload) != {"event", "exit_code", "outputs", "error"}
                        or type(payload["exit_code"]) is not int
                        or not -128 <= payload["exit_code"] <= 255
                        or payload["error"] is not None
                        and (not isinstance(payload["error"], str) or len(payload["error"]) > 500)
                    ):
                        raise ValueError("Invalid Python completion fields")
                    names = [item["name"] for item in outputs]
                    if payload["outputs"] != names or (
                        payload["exit_code"] == 0
                        and payload["error"] is None
                        and names != body.expected_outputs
                    ):
                        raise ValueError("Python completion omitted required outputs")
                    if (payload["exit_code"] != 0 or payload["error"]) and outputs:
                        raise ValueError("Failed Python execution cannot publish outputs")
                    result = payload
                else:
                    raise ValueError("Python wrapper failed or returned an unknown event")
            code = await proc.wait()
            errors = await stderr_task
            if code != 0 or result is None:
                raise RuntimeError(
                    "Python container did not finish with a complete result: " + errors[-2000:]
                )
        report = {
            "run_id": run_id,
            "request_digest": saved["digest"],
            "project_id": str(body.project_id),
            "worktree_run_id": str(body.worktree_run_id),
            "script_sha256": body.script_sha256,
            "exit_code": result["exit_code"],
            "error": result["error"],
            "outputs": outputs,
            "succeeded": result["exit_code"] == 0 and result["error"] is None,
        }
    finally:
        cleaned = stop_container(run_id)
        if proc is not None and proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task
        if not cleaned:
            raise RuntimeError("Python container cleanup requires inspection")
    save(directory(run_id) / "report.json", report)
    print("\nPython execution report saved", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(execute(sys.argv[1]))
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
