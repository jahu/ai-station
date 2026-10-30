"""Scheduler process. Creates runs and stores telemetry. It does not execute them."""

from __future__ import annotations

import time

from app.db import control_session_factory, migrate, utcnow
from app.llama import reconcile
from app.models import Setting
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.schedule import scheduler_tick
from app.telemetry_store import record_sample


def main() -> None:
    migrate()
    from app.account_profile import prepare_profile

    with control_session_factory()() as session:
        prepare_profile(session)
        session.commit()
    factory = control_session_factory()
    runner = RunnerClient(timeout=8)
    while True:
        session = factory()
        try:
            scheduler_tick(session)
            session.commit()
            try:
                reconcile(session, runner)
                record_sample(session, {"sampled_at": utcnow().isoformat(), **runner.hardware()})
            except (RunnerUnavailable, RunnerError):
                record_sample(session, {"available": False})
            session.merge(Setting(key="scheduler_heartbeat", value={"at": utcnow().isoformat()}))
            session.commit()
        finally:
            session.close()
        time.sleep(15)


if __name__ == "__main__":
    main()
