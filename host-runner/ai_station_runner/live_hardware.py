"""Read-only admission for this CUDA-13 profile, including GPU architecture."""

import subprocess

from ai_station_runner.nvidia import executable


def compatible_gpus(hardware):
    try:
        probe = subprocess.run(
            [executable(), "--query-gpu=index,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        supported = set()
        for line in probe.stdout.splitlines():
            index, version = (value.strip() for value in line.split(","))
            major, minor = (int(value) for value in version.split("."))
            if (major, minor) >= (7, 5):
                supported.add(int(index))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [
        row
        for row in hardware.get("gpus", [])
        if int(row["index"]) in supported and (row.get("memory_total_mib") or 0) >= 4096
    ]
