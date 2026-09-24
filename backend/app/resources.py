"""GPU and other resource locks. One heavy job per GPU."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ResourceLock, Run


class ResourceBusy(Exception):
    pass


class ResourceUnknown(Exception):
    pass


def active_locks(session: Session) -> set[str]:
    rows = session.scalars(select(ResourceLock).where(ResourceLock.released_at.is_(None))).all()
    return {row.resource_key for row in rows}


def reserve_gpu(session: Session, run: Run, available: list[int]) -> str | None:
    """Return the allocated gpu id as a string, or None when the run must stay queued.

    `none` means the run does not need a GPU. An unknown index fails the caller.
    """
    requested = (run.requested_gpu or "none").strip()
    if requested in ("", "none"):
        run.actual_gpu = None
        run.allocated_resources = {**run.allocated_resources, "gpu": "none"}
        return None
    busy = active_locks(session)
    if requested == "auto":
        if not available:
            raise ResourceUnknown("No GPUs were discovered")
        for index in available:
            key = f"gpu:{index}"
            if key not in busy:
                _grant(session, run, key, str(index))
                return str(index)
        return None
    if not requested.isdigit():
        raise ResourceUnknown(f"Unsupported GPU request: {requested}")
    if int(requested) not in available:
        raise ResourceUnknown(f"GPU {requested} is not present. Discovered: {available}")
    requested = str(int(requested))
    key = f"gpu:{requested}"
    if key in busy:
        return None
    _grant(session, run, key, requested)
    return requested


def _grant(session: Session, run: Run, key: str, gpu: str) -> None:
    session.add(ResourceLock(resource_key=key, run_id=run.id))
    run.actual_gpu = gpu
    allocated = dict(run.allocated_resources or {})
    allocated["gpu"] = gpu
    run.allocated_resources = allocated
    session.flush()


def release_run_locks(session: Session, run_id: str) -> None:
    rows = session.scalars(
        select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
    ).all()
    now = utcnow()
    for row in rows:
        row.released_at = now
    session.flush()
