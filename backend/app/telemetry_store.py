"""Telemetry retention: raw samples for six hours, hourly samples for 30 days."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import TelemetrySample


def record_sample(session: Session, payload: dict) -> None:
    now = utcnow()
    session.add(TelemetrySample(sampled_at=now, resolution="raw", payload=payload))
    cutoff = now - timedelta(hours=6)
    old = list(
        session.scalars(
            select(TelemetrySample).where(
                TelemetrySample.resolution == "raw",
                TelemetrySample.sampled_at < cutoff,
            )
        )
    )
    for sample in old:
        hour = sample.sampled_at.replace(minute=0, second=0, microsecond=0)
        exists = session.scalar(
            select(TelemetrySample.id).where(
                TelemetrySample.resolution == "hour",
                TelemetrySample.sampled_at == hour,
            )
        )
        if exists is None:
            session.add(TelemetrySample(sampled_at=hour, resolution="hour", payload=sample.payload))
        session.delete(sample)
    ancient = now - timedelta(days=30)
    for sample in session.scalars(
        select(TelemetrySample).where(
            TelemetrySample.resolution == "hour",
            TelemetrySample.sampled_at < ancient,
        )
    ):
        session.delete(sample)
    session.flush()


def history(session: Session, limit: int = 240) -> list[dict]:
    rows = session.scalars(
        select(TelemetrySample).order_by(TelemetrySample.sampled_at.desc()).limit(limit)
    ).all()
    return [
        {"sampled_at": row.sampled_at.isoformat(), "resolution": row.resolution, "payload": row.payload}
        for row in reversed(rows)
    ]
