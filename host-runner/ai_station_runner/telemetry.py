"""Host telemetry. Missing sensors stay null; they are not invented."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_previous_cpu: tuple[int, int] | None = None


def collect(data_dir: Path) -> dict:
    return {
        "gpus": gpus(),
        "cpu": cpu(),
        "memory": memory(),
        "disk": disk(data_dir),
        "load": load(),
    }


def gpus() -> list[dict]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    rows = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 9:
            continue
        rows.append(
            {
                "index": _int(parts[0]),
                "uuid": parts[1],
                "name": parts[2],
                "utilization": _float(parts[3]),
                "memory_used_mib": _float(parts[4]),
                "memory_total_mib": _float(parts[5]),
                "temperature_c": _float(parts[6]),
                "fan_percent": _float(parts[7]),
                "power_watts": _float(parts[8]),
            }
        )
    return rows


def cpu() -> dict:
    global _previous_cpu
    stat = Path("/proc/stat").read_text().splitlines()[0].split()
    values = [int(item) for item in stat[1:]]
    idle = values[3]
    total = sum(values)
    percent = None
    if _previous_cpu is not None:
        prev_idle, prev_total = _previous_cpu
        delta_total = total - prev_total
        delta_idle = idle - prev_idle
        if delta_total > 0:
            percent = round(100 * (1 - delta_idle / delta_total), 1)
    _previous_cpu = (idle, total)
    return {"utilization": percent, "temperature_c": _cpu_temperature()}


def memory() -> dict:
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.strip().split()[0])
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    return {
        "total_mib": round(total / 1024, 1),
        "used_mib": round((total - available) / 1024, 1),
        "available_mib": round(available / 1024, 1),
        "swap_used_mib": round((swap_total - swap_free) / 1024, 1),
        "swap_total_mib": round(swap_total / 1024, 1),
    }


def disk(path: Path) -> dict:
    usage = shutil.disk_usage(path if path.exists() else Path("/"))
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def load() -> dict:
    one, five, fifteen = os.getloadavg()
    return {"1": one, "5": five, "15": fifteen}


def _cpu_temperature() -> float | None:
    zones = (
        list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
        if Path("/sys/class/thermal").exists()
        else []
    )
    for zone in zones:
        try:
            raw = int(zone.read_text().strip())
        except (OSError, ValueError):
            continue
        if raw > 0:
            return round(raw / 1000, 1)
    return None


def _float(value: str) -> float | None:
    if value in {"", "[N/A]", "[Not Supported]", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
