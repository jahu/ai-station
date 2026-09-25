"""Bounded Linux process observations; no commands, secrets, or ownership transfer."""

import hashlib
import time
from pathlib import Path

NAMES = {"llama-server": "llama.cpp", "ollama": "ollama", "sd-server": "stable-diffusion.cpp"}
MAX_PROCESSES = 20000
MAX_INSTANCES = 200


def read_bounded(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def observe(proc: Path = Path("/proc")) -> dict:
    boot = read_bounded(proc / "sys/kernel/random/boot_id", 100).decode().strip()
    observations = []
    complete = True
    inspected = 0
    deadline = time.monotonic() + 3
    for folder in proc.iterdir():
        if not folder.name.isdigit():
            continue
        inspected += 1
        if inspected > MAX_PROCESSES or time.monotonic() > deadline or len(observations) >= MAX_INSTANCES:
            complete = False
            break
        try:
            name = read_bounded(folder / "comm", 100).decode(errors="replace").strip()
            runtime = NAMES.get(name)
            if not runtime and name.startswith("python"):
                # Read only a bounded prefix for recognition. Never return/store argv.
                args = read_bounded(folder / "cmdline", 4096).split(b"\0")
                if len(args) > 1:
                    script = args[1].decode(errors="replace").lower().replace("\\", "/")
                    if script.endswith("/comfyui/main.py"):
                        runtime = "comfyui"
            if not runtime:
                continue
            stat = read_bounded(folder / "stat", 4096).decode()
            fields = stat[stat.rfind(")") + 2 :].split()
            if fields[0] in {"Z", "X"}:
                continue
            start_ticks = int(fields[19])
            identity = hashlib.sha256(f"{boot}:{folder.name}:{start_ticks}".encode()).hexdigest()
            observations.append(
                {
                    "identity": identity,
                    "runtime_key": runtime,
                    "pid": int(folder.name),
                    "start_ticks": start_ticks,
                }
            )
        except FileNotFoundError:
            continue  # Process exited during observation.
        except (PermissionError, OSError, ValueError, IndexError):
            complete = False
    return {"instances": observations, "complete": complete, "inspected": min(inspected, MAX_PROCESSES)}
