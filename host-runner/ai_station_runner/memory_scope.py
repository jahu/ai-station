"""Fixed user-level memory scopes retaining native PID/process-group ownership.

This is an internal launch prefix, not a command or systemd API. Individual
executors must explicitly choose a qualified bound; nothing falls back uncapped.
"""

import os
import shutil
from pathlib import Path
from uuid import UUID

APPROVED_LIMITS_MIB = frozenset({11264, 12288, 18432})


def available() -> bool:
    """Read-only readiness; each launched child still verifies its actual limits."""
    try:
        runtime = Path(scope_environment()["XDG_RUNTIME_DIR"])
        return bool(
            os.getuid() != 0
            and shutil.which("systemd-run")
            and (runtime / "bus").is_socket()
            and "memory" in Path("/sys/fs/cgroup/cgroup.controllers").read_text().split()
        )
    except OSError:
        return False


def scope_name(run_id: str) -> str:
    if str(UUID(run_id)) != run_id:
        raise ValueError("Memory scopes require a canonical Run UUID")
    return "ai-station-memory-" + run_id


def checked_limit(maximum_mib: int) -> int:
    if type(maximum_mib) is not int or maximum_mib not in APPROVED_LIMITS_MIB:
        raise ValueError("Choose an explicitly qualified memory bound")
    return maximum_mib


def scope_prefix(run_id: str, maximum_mib: int) -> list[str]:
    name = scope_name(run_id)
    limit = checked_limit(maximum_mib)
    binary = shutil.which("systemd-run")
    if not binary:
        raise ValueError("A user systemd memory scope is unavailable")
    # --scope execs the child without changing its session/process group. The
    # existing ProcessManager remains responsible for ownership and absolute
    # deadlines. Existing profiles retain their one-hour fuse; only the fixed
    # opt-in whole-recording candidate uses the four-hour maximum.
    runtime_seconds = 14400 if limit == 18432 else 3600
    return [
        binary,
        "--user",
        "--scope",
        "--quiet",
        "--unit=" + name,
        "--property=MemoryMax=" + str(limit) + "M",
        "--property=MemorySwapMax=0",
        "--property=CPUQuota=400%",
        "--property=RuntimeMaxSec=" + str(runtime_seconds),
        "--",
    ]


def scope_environment() -> dict[str, str]:
    # Native services may have a smaller environment than an interactive shell.
    # The caller supplies the rest of its existing fixed executor environment.
    return {
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    }


def current_group() -> Path:
    rows = Path("/proc/self/cgroup").read_text().splitlines()
    unified = next((row[3:] for row in rows if row.startswith("0::")), "")
    parts = Path(unified).parts
    if not unified.startswith("/") or ".." in parts:
        raise ValueError("A unified private memory scope is unavailable")
    return Path("/sys/fs/cgroup") / unified.lstrip("/")


def require_scope(run_id: str, maximum_mib: int) -> dict:
    """Fail before model import unless the actual kernel limits match the profile."""
    expected = checked_limit(maximum_mib)
    group = current_group()
    if group.name != scope_name(run_id) + ".scope":
        raise ValueError("The model is outside its owned memory scope")
    try:
        maximum = (group / "memory.max").read_text().strip()
        swap = (group / "memory.swap.max").read_text().strip()
    except OSError as exc:
        raise ValueError("Kernel memory bounds could not be confirmed") from exc
    if maximum != str(expected * 1024**2) or swap != "0":
        raise ValueError("Kernel RAM and zero-swap limits do not match the reviewed profile")
    return {"maximum_ram_mib": expected, "maximum_swap_mib": 0}
