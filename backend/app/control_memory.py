"""Read-only CPU memory admission inside the control-plane container."""

from pathlib import Path


def available_mib(meminfo=Path("/proc/meminfo"), cgroup=Path("/sys/fs/cgroup")):
    try:
        values = {
            row.split(":", 1)[0]: row.split(":", 1)[1].strip().split()
            for row in meminfo.read_text().splitlines()
            if ":" in row
        }
        value, unit = values["MemAvailable"]
        if not value.isdigit() or unit != "kB":
            return None
        available = int(value) * 1024
        maximum = (cgroup / "memory.max").read_text().strip() if (cgroup / "memory.max").is_file() else "max"
        if maximum != "max":
            current = (cgroup / "memory.current").read_text().strip()
            if not maximum.isdigit() or not current.isdigit():
                return None
            available = min(available, max(0, int(maximum) - int(current)))
        return available // 1024**2
    except (OSError, ValueError, KeyError):
        return None
