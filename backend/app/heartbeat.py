"""Renew leases independently of slow providers or host requests."""

import logging
import threading
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import update

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Run, WorkerRow
from app.state import TERMINAL


@contextmanager
def keep_lease(run_id: str, worker_id: str):
    stop = threading.Event()
    settings = get_settings()
    factory = session_factory()

    def renew():
        while not stop.wait(settings.heartbeat_seconds):
            try:
                with factory() as session:
                    now = utcnow()
                    session.execute(
                        update(WorkerRow).where(WorkerRow.id == worker_id).values(last_heartbeat=now)
                    )
                    session.execute(
                        update(Run)
                        .where(Run.id == run_id, Run.worker_id == worker_id, Run.status.not_in(TERMINAL))
                        .values(lease_expires_at=now + timedelta(seconds=settings.lease_seconds))
                    )
                    session.commit()
            except Exception:
                logging.exception("Could not renew worker lease")

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=6)
