"""Bounded, read-only NVIDIA compute-process metadata; never process control."""

import csv
import io
import math
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import PurePosixPath

from ai_station_runner import nvidia


def collect():
    observed = datetime.now(UTC).isoformat()
    base = {"sampled_at": observed, "processes": [], "truncated": False}
    try:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as output:
            result = subprocess.run(
                [
                    nvidia.executable(),
                    "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                stdout=output,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
            output.seek(0)
            text = output.read(65537)
    except (OSError, subprocess.TimeoutExpired):
        return {**base, "status": "unavailable"}
    if result.returncode != 0 or len(text) > 65536:
        return {**base, "status": "unavailable"}
    records, seen, partial, truncated = [], set(), False, False
    try:
        for row in csv.reader(io.StringIO(text), strict=True, skipinitialspace=True):
            if not row:
                continue
            if len(row) != 4:
                partial = True
                continue
            uuid, pid, name, memory = (v.strip() for v in row)
            try:
                pid = int(pid)
                if not 0 < pid < 2**31 or not uuid.startswith(("GPU-", "MIG-")) or len(uuid) > 100:
                    raise ValueError()
            except ValueError:
                partial = True
                continue
            try:
                used = float(memory)
                if not math.isfinite(used) or used < 0:
                    used = None
            except ValueError:
                if memory in {"N/A", "[N/A]", "[Not Supported]"}:
                    used = None
                else:
                    partial = True
                    continue
            name = " ".join(PurePosixPath(name).name.split())[:160] or "Unknown"
            key = (uuid, pid)
            if key in seen:
                continue
            if len(records) == 128:
                truncated = True
                break
            seen.add(key)
            records.append({"gpu_uuid": uuid, "pid": pid, "name": name, "memory_used_mib": used})
    except csv.Error:
        partial = True
    return {
        **base,
        "status": "partial" if partial else "available",
        "processes": records,
        "truncated": truncated,
    }
