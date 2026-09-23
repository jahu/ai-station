"""Core executor boundary; adapters own capability-specific preparation."""

from typing import Protocol

from sqlalchemy.orm import Session

from app.models import Run


class Executor(Protocol):
    name: str

    def execute(self, session: Session, run: Run) -> str:
        """Execute a claimed run, persist events, and respect durable cancellation.

        Commit before external I/O. Never keep a database write transaction open
        while waiting on a provider or process. Return only after reaching a
        terminal state or deliberately yielding to recovery/resource scheduling.
        """
        ...
