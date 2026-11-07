"""Retry short in-worker persistence without replaying provider/tool execution."""

import asyncio

from app.db import sqlite_busy, utcnow
from app.providers import ProviderError
from app.state import TERMINAL


class RunClaimLost(Exception):
    """Recovery, cancellation completion or another worker already owns the result."""


async def checkpoint(session, run, claim, deadline, action):
    while True:
        try:
            session.refresh(run)
            if (run.worker_id, run.claimed_at) != claim or run.status in TERMINAL:
                raise RunClaimLost()
            result = action()
            session.commit()
            return result
        except Exception as exc:
            session.rollback()
            if not sqlite_busy(exc):
                raise
            if utcnow() >= deadline:
                raise ProviderError(
                    "Response persistence deadline exceeded during database contention"
                ) from exc
            await asyncio.sleep(0.05)
