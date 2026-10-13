"""Persistent, idempotent ownership of Linux process groups.

Boot id and /proc start ticks disambiguate reused PIDs after runner restarts.
An unknown exit code is never translated into successful execution.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from uuid import UUID

from ai_station_runner.security import resolve_child


class ProcessNotOwned(KeyError):
    pass


def _identity(pid: int) -> dict | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "state": fields[0],
            "pgid": int(fields[2]),
            "session": int(fields[3]),
            "start_ticks": int(fields[19]),
        }
    except (OSError, ValueError, IndexError):
        return None


def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _group_alive(record: dict) -> bool:
    if record.get("boot_id") != _boot_id() or not record.get("start_ticks"):
        return False
    leader = _identity(record["pid"])
    if leader and leader["start_ticks"] != record["start_ticks"]:
        return False
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        member = _identity(int(path.name))
        if (
            member
            and member["state"] not in {"Z", "X"}
            and member["pgid"] == record["process_group_id"]
            and member["session"] == record["pid"]
            and member["start_ticks"] >= record["start_ticks"]
        ):
            return True
    return False


class ProcessManager:
    def __init__(self, data_dir: Path, grace_seconds: float = 3.0):
        self.data_dir = data_dir.resolve()
        self.grace_seconds = grace_seconds
        self.path = resolve_child(self.data_dir, "runtime/processes.json")
        self._lock = threading.RLock()
        self._live: dict[str, subprocess.Popen] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._dump({})

    def start(
        self, *, run_id: str, argv: list[str], cwd: Path, executor: str, env: dict | None = None
    ) -> dict:
        if str(UUID(run_id)) != run_id:
            raise ValueError("Canonical UUID required")
        if not argv or any(not isinstance(part, str) or not part for part in argv):
            raise ValueError("argv must be a non-empty list of non-empty strings")
        with self._lock:
            records = self._load()
            if run_id in records:
                if records[run_id]["executor"] != executor:
                    raise ValueError("Run already belongs to a different executor")
                return self.inspect(run_id)
            log_dir = resolve_child(self.data_dir, f"runs/{run_id}")
            log_dir.mkdir(parents=True, exist_ok=True)
            out = resolve_child(log_dir, "stdout.log")
            err = resolve_child(log_dir, "stderr.log")
            with out.open("ab") as stdout, err.open("ab") as stderr:
                proc = subprocess.Popen(
                    argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True
                )
            identity = _identity(proc.pid)
            record = {
                "run_id": run_id,
                "pid": proc.pid,
                "process_group_id": proc.pid,
                "started_at": time.time(),
                "boot_id": _boot_id(),
                "start_ticks": identity["start_ticks"] if identity else None,
                "executor": executor,
                "cwd": str(cwd),
                "stdout_log": f"runs/{run_id}/stdout.log",
                "stderr_log": f"runs/{run_id}/stderr.log",
                "status": "running",
                "exit_code": None,
            }
            records[run_id] = record
            try:
                self._dump(records)
            except BaseException:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
            self._live[run_id] = proc
            threading.Thread(target=self._wait, args=(run_id, proc), daemon=True).start()
            return dict(record)

    def inspect(
        self, run_id: str, *, stdout_offset: int | None = None, stderr_offset: int | None = None
    ) -> dict:
        with self._lock:
            records = self._load()
            record = records.get(run_id)
            if record is None:
                raise ProcessNotOwned(run_id)
            alive = _group_alive(record)
            proc = self._live.get(run_id)
            completion_pending = False
            if not alive and proc is not None:
                code = proc.poll()
                completion_pending = code is None
                if code is not None:
                    record["exit_code"] = code
            if not alive and not completion_pending and record["status"] in {"running", "cancel_requested"}:
                record["status"] = (
                    "canceled"
                    if record["status"] == "cancel_requested"
                    else "exited"
                    if record["exit_code"] is not None
                    else "interrupted"
                )
                self._dump(records)
            if record["executor"] == "browser" and not alive and not completion_pending:
                from ai_station_runner.browser_runs import stop_containers

                try:
                    confirmed = stop_containers(run_id)
                except (OSError, RuntimeError, ValueError):
                    confirmed = False
                if not confirmed:
                    record["status"] = "interrupted"
                    self._dump(records)
            result = {
                **record,
                "alive": alive,
                "completion_pending": completion_pending,
                "stdout": _read(resolve_child(self.data_dir, record["stdout_log"])),
                "stderr_tail": _read(resolve_child(self.data_dir, record["stderr_log"]), 4000),
            }
            if record["executor"] == "browser" and not alive and not completion_pending:
                result["cleanup_confirmed"] = confirmed
            for stream, offset in (("stdout", stdout_offset), ("stderr", stderr_offset)):
                if offset is not None:
                    path = resolve_child(self.data_dir, record[f"{stream}_log"])
                    with path.open("rb") as handle:
                        handle.seek(offset)
                        chunk = handle.read(65536)
                    result[stream] = chunk.decode(errors="replace")
                    result[f"{stream}_offset"] = offset + len(chunk)
                    result[f"{stream}_more"] = path.stat().st_size > offset + len(chunk)
            return result

    def shutdown(self) -> None:
        with self._lock:
            run_ids = list(self._load())
        for run_id in run_ids:
            self.cancel(run_id)

    def cancel(self, run_id: str) -> dict:
        with self._lock:
            record = self.inspect(run_id)
            if record["executor"] == "browser":
                from ai_station_runner.browser_runs import cancel_browser

                cancel_browser(run_id)
            if not record["alive"]:
                return record
            records = self._load()
            records[run_id]["status"] = "cancel_requested"
            self._dump(records)
            self._signal(record, signal.SIGTERM)
        deadline = time.monotonic() + self.grace_seconds
        while time.monotonic() < deadline and _group_alive(record):
            time.sleep(0.02)
        self._signal(record, signal.SIGKILL)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and _group_alive(record):
            time.sleep(0.02)
        return self.inspect(run_id)

    @staticmethod
    def _signal(record: dict, sig: int) -> None:
        if _group_alive(record):
            try:
                os.killpg(record["process_group_id"], sig)
            except ProcessLookupError:
                pass

    def _wait(self, run_id: str, proc: subprocess.Popen) -> None:
        # Popen.wait() holds its internal waitpid lock while blocking. Concurrent
        # poll() can then return None even after /proc reports the child gone,
        # causing inspect() to persist a false interruption. Reap and publish
        # under the same short registry lock used by inspect(), never wait there.
        while True:
            with self._lock:
                code = proc.poll()
                if code is not None:
                    records = self._load()
                    records[run_id]["exit_code"] = code
                    self._dump(records)
                    self._live.pop(run_id, None)
                    return
            time.sleep(0.05)

    def _load(self) -> dict:
        # Fail closed on a corrupt registry instead of forgetting ownership.
        return json.loads(self.path.read_text())

    def _dump(self, records: dict) -> None:
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as handle:
            os.chmod(temporary, 0o600)
            json.dump(records, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)


def _read(path: Path, limit: int = 256_000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - limit))
        return handle.read(limit).decode(errors="replace")
