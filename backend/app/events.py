"""Append-only run events."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import RunEvent
from app.redact import redact_obj


def append_event(session: Session, run_id: str, event_type: str, payload: dict | None = None) -> RunEvent:
    current = session.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id))
    sequence = int(current or 0) + 1
    event = RunEvent(
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        payload=redact_obj(payload or {}),
    )
    session.add(event)
    session.flush()
    return event


def list_events(session: Session, run_id: str, after: int = 0) -> list[RunEvent]:
    return list(
        session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
            .order_by(RunEvent.sequence)
        )
    )


def event_dict(event: RunEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }
