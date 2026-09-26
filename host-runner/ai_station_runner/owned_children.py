"""Drain children left by a CLI before its managed wrapper exits successfully."""

import os
import signal
import time
from pathlib import Path

from ai_station_runner.processes import _identity


def stop_owned_children(grace_seconds: float = 1.0) -> None:
    leader = os.getpid()
    identity = _identity(leader)
    if not identity or identity["pgid"] != leader or identity["session"] != leader:
        raise RuntimeError("Child cleanup requires an owned process-group leader")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Safe Cursor child cleanup requires Linux pidfd support")
    started = time.monotonic()
    signaled = set()
    while True:
        children = []
        for path in Path("/proc").iterdir():
            if not path.name.isdigit() or int(path.name) == leader:
                continue
            pid = int(path.name)
            member = _identity(pid)
            if (
                member
                and member["state"] not in {"Z", "X"}
                and member["pgid"] == leader
                and member["session"] == leader
                and member["start_ticks"] >= identity["start_ticks"]
            ):
                children.append((pid, member))
        if not children:
            return
        expired = time.monotonic() - started > grace_seconds
        for pid, member in children:
            key = (pid, member["start_ticks"], expired)
            if key in signaled:
                continue
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                # The pidfd pins the target identity; a PID reuse between the
                # discovery and open must not turn into a signal to another job.
                current = _identity(pid)
                if (
                    current
                    and current["start_ticks"] == member["start_ticks"]
                    and current["pgid"] == leader
                    and current["session"] == leader
                ):
                    try:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL if expired else signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    signaled.add(key)
            finally:
                os.close(descriptor)
        if time.monotonic() - started > grace_seconds + 2:
            raise RuntimeError("Cursor left an owned child that could not be stopped")
        time.sleep(0.02)
