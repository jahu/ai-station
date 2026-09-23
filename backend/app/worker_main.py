"""Worker process. Claims durable runs and dispatches executors."""

from __future__ import annotations

import os
import socket
import time
import uuid

from app.config import get_settings
from app.db import migrate, session_factory
from app.engine import tick


def worker_id() -> str:
    return os.environ.get("AI_STATION_WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4()}"


def main() -> None:
    migrate()
    settings = get_settings()
    identity = worker_id()
    factory = session_factory()
    while True:
        session = factory()
        try:
            tick(session, identity)
        finally:
            session.close()
        time.sleep(settings.heartbeat_seconds)


if __name__ == "__main__":
    main()
