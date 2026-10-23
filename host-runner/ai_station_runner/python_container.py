"""Image-owned wrapper. The generated script has no host filesystem/network access."""

import base64
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import PurePosixPath

if __package__:
    from .python_protocol import MAX_FILE, MAX_FILES, MAX_LOG, MAX_OUTPUT_TOTAL
else:
    from python_protocol import MAX_FILE, MAX_FILES, MAX_LOG, MAX_OUTPUT_TOTAL


def relative_file(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("Expected a bounded relative output filename")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
        or value == "."
        or "\\" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Expected a canonical relative output filename")
    return value


def read_output(name, root="/outputs"):
    relative_file(name)
    # Open each component without following aliases. Nonblocking opens also keep
    # a generated FIFO/device from stalling collection; only regular files pass.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(name).parts
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(child)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE:
                raise ValueError("Output must be a bounded regular file without hardlinks")
            data = bytearray()
            while chunk := os.read(child, min(65536, MAX_FILE + 1 - len(data))):
                data.extend(chunk)
                if len(data) > MAX_FILE:
                    raise ValueError("Output exceeds its size limit")
            after = os.fstat(child)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("Output changed during collection")
            return bytes(data)
        finally:
            os.close(child)
    finally:
        os.close(fd)


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}), flush=True)


def execute(request):
    if set(request) != {"maximum_runtime", "expected_outputs", "inputs"}:
        raise ValueError("Unexpected Python execution fields")
    timeout = request["maximum_runtime"]
    outputs = request["expected_outputs"]
    if (
        type(timeout) is not int
        or not 1 <= timeout <= 600
        or not isinstance(outputs, list)
        or not 1 <= len(outputs) <= MAX_FILES
        or len(set(outputs)) != len(outputs)
    ):
        raise ValueError("Invalid Python execution limits")
    for name in outputs:
        relative_file(name)
    if not isinstance(request["inputs"], dict) or len(request["inputs"]) > 8:
        raise ValueError("Invalid Python input map")
    for key, value in request["inputs"].items():
        if not isinstance(key, str) or value != "/inputs/" + key:
            raise ValueError("Python inputs must be staged files")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AI_STATION_INPUTS": json.dumps(request["inputs"]),
        "AI_STATION_OUTPUT_DIR": "/outputs",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": "/tmp/matplotlib",
    }
    deadline = time.monotonic() + timeout
    size = 0
    with subprocess.Popen(
        [sys.executable, "-I", "-u", "/inputs/script.py"],
        cwd="/outputs",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as proc:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
                selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map() or proc.poll() is None:
                    if time.monotonic() > deadline or size > MAX_LOG:
                        raise TimeoutError("Python execution exceeded time/output limit")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            size += len(chunk)
                            emit(key.data, text=chunk.decode("utf-8", errors="replace"))
                exit_code = proc.wait()
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    files = []
    total = 0
    error = None
    if exit_code == 0:
        try:
            for name in outputs:
                data = read_output(name)
                total += len(data)
                if total > MAX_OUTPUT_TOTAL:
                    raise ValueError("Python outputs exceed their total size limit")
                files.append({"name": name, "data": base64.b64encode(data).decode("ascii")})
        except (OSError, ValueError) as exc:
            error = f"Expected output unavailable: {type(exc).__name__}"
            files = []
    for item in files:
        emit("output", **item)
    emit("result", exit_code=exit_code, outputs=[item["name"] for item in files], error=error)


if __name__ == "__main__":
    try:
        line = sys.stdin.buffer.readline(16385)
        if len(line) > 16384:
            raise ValueError("Python request exceeds its limit")
        execute(json.loads(line))
    except Exception as error:
        emit("failed", error=f"{type(error).__name__}: {error}")
        raise SystemExit(1) from error
