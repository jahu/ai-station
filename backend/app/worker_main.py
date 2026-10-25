"""Worker process. Claims durable runs and dispatches executors."""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import socket
import time
import uuid

from app.config import get_settings
from app.db import migrate, session_factory, sqlite_busy
from app.engine import tick


def worker_id() -> str:
    return os.environ.get("AI_STATION_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4()}"


def worker_loop(identity: str) -> None:
    """One slot owns its sessions and renews only its own Run leases."""
    settings = get_settings()
    factory = session_factory()
    while True:
        session = factory()
        try:
            tick(session, identity)
        except Exception as exc:
            session.rollback()
            if not sqlite_busy(exc):
                raise
            # A claimed Run retains its lease/inspection policy. Never replay an
            # executor or restart unrelated slots because a database was busy.
            logging.warning("SQLite busy; worker slot will inspect durable state on its next tick")
        finally:
            session.close()
        time.sleep(settings.heartbeat_seconds)


def main() -> None:
    migrate()
    slots = get_settings().worker_slots
    identity = worker_id()
    # Spawn avoids inheriting the migration connection or sharing executor state.
    context = multiprocessing.get_context("spawn")
    children = []
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for index in range(slots):
            if stopping:
                break
            slot_id = identity if slots == 1 else f"{identity}/slot-{index + 1}"
            child = context.Process(target=worker_loop, args=(slot_id,))
            child.start()
            children.append(child)
        while not stopping:
            if any(child.exitcode is not None for child in children):
                raise RuntimeError("Worker slot exited; restarting the worker group is required")
            time.sleep(0.1)
    finally:
        # Only children created here are signaled. Native jobs retain their
        # durable ownership records and follow the existing recovery policy.
        for child in children:
            if child.is_alive():
                child.terminate()
        deadline = time.monotonic() + 5
        for child in children:
            child.join(timeout=max(0, deadline - time.monotonic()))
        for child in children:
            if child.is_alive():
                child.kill()
                child.join(timeout=1)
            child.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
