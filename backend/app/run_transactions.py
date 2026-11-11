"""Claim-fenced retries of short database-only phases; never replay provider I/O."""

import asyncio

from app.db import sqlite_busy, utcnow
from app.providers import ProviderError
from app.runs import transition
from app.state import TERMINAL, RunStatus


class RunStopped(Exception):
    pass


async def database_step(session, run, claim, deadline, action):
    while True:
        try:
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim or run.status in TERMINAL:
                raise RunStopped()
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                session.commit()
                raise RunStopped()
            result = action()
            session.commit()
            return result
        except Exception as exc:
            session.rollback()
            if not sqlite_busy(exc):
                raise
            if utcnow() >= deadline:
                raise ProviderError("Run deadline exceeded during database contention") from exc
            await asyncio.sleep(0.05)
