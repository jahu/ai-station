"""Scheduler process. Creates runs and stores telemetry. It does not execute them."""

from __future__ import annotations

import time

from app.db import migrate, session_factory, utcnow
from app.runner_client import RunnerClient, RunnerUnavailable
from app.schedule import scheduler_tick
from app.telemetry_store import record_sample


def main() -> None:
    migrate()
    factory = session_factory()
    runner = RunnerClient(timeout=8)
    while True:
        session = factory()
        try:
            scheduler_tick(session)
            try:
                record_sample(session, {"sampled_at": utcnow().isoformat(), **runner.hardware()})
            except RunnerUnavailable:
                record_sample(session, {"available": False})
            session.commit()
        finally:
            session.close()
        time.sleep(15)


if __name__ == "__main__":
    main()
