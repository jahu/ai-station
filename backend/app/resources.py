"""GPU and other resource locks. One heavy job per GPU."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ResourceLock, Run, Task
from app.task_control import lock_task


class ResourceBusy(Exception):
    pass


class ResourceUnknown(Exception):
    pass


RESOURCE_WAIT_KEY = "resource_wait_until"


def resource_ready_condition(now):
    waiting = (
        select(Task.id)
        .where(Task.id == Run.task_id, Task.metadata_json[RESOURCE_WAIT_KEY].as_string() > now.isoformat())
        .correlate(Run)
        .exists()
    )
    return and_(
        or_(
            and_(
                or_(Run.requested_gpu.is_(None), Run.requested_gpu.in_(("none", ""))),
                Run.executor_type != "llama_load",
            ),
            ~waiting,
        ),
        or_(Run.executor_type != "site_preview", ~waiting),
    )


def active_locks(session: Session) -> set[str]:
    # Physical availability is shared. Expose only resource keys, never another
    # account's Run IDs or workload data, and keep reservation in this transaction.
    return set(
        session.connection()
        .execute(
            select(ResourceLock.resource_key).where(
                ResourceLock.released_at.is_(None), ResourceLock.resource_key.like("gpu:%")
            )
        )
        .scalars()
    )


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


def reserve_gpu_bundle(session: Session, run: Run, available: list[int], count: int) -> str | None:
    """Reserve a primary and optional auxiliary GPU together, or reserve neither.

    Native dispatch must occur only after the containing transaction commits.
    Existing unique live resource keys arbitrate competing worker transactions.
    """
    if type(count) is not int or count not in {1, 2}:
        raise ResourceUnknown("Image execution supports one or two reserved GPUs")
    if len(set(available)) < count:
        raise ResourceUnknown(f"This image preset requires {count} discovered GPUs")
    requested = run.requested_gpu or "auto"
    if requested != "auto" and (not requested.isdigit() or int(requested) not in available):
        raise ResourceUnknown("Requested primary image GPU was not discovered")
    busy = active_locks(session)
    free = [str(index) for index in dict.fromkeys(available) if f"gpu:{index}" not in busy]
    if requested != "auto":
        requested = str(int(requested))
        if requested not in free:
            return None
        free = [requested, *(gpu for gpu in free if gpu != requested)]
    if len(free) < count:
        return None
    selected = free[:count]
    for gpu in selected:
        session.add(ResourceLock(resource_key=f"gpu:{gpu}", run_id=run.id))
    run.actual_gpu = selected[0]
    run.allocated_resources = {**run.allocated_resources, "gpu": selected[0], "gpus": selected}
    session.flush()
    return selected[0]


def release_run_locks(session: Session, run_id: str) -> None:
    rows = session.scalars(
        select(ResourceLock).where(ResourceLock.run_id == run_id, ResourceLock.released_at.is_(None))
    ).all()
    now = utcnow()
    for row in rows:
        row.released_at = now
    if any(row.resource_key.startswith("gpu:") for row in rows):
        owner = session.get(Run, run_id)
        task = session.get(Task, owner.task_id) if owner is not None else None
        if task is not None:
            lock_task(session, task)
            if RESOURCE_WAIT_KEY in task.metadata_json:
                task.metadata_json = {
                    key: value for key, value in task.metadata_json.items() if key != RESOURCE_WAIT_KEY
                }
    session.flush()


def memory_observation(session, run, available_mib, required_mib):
    """The same observed RAM and reservation inputs used by conservative admission."""
    allocations = (
        session.connection()
        .execute(
            select(Run.allocated_resources)
            .join(ResourceLock, ResourceLock.run_id == Run.id)
            .where(
                ResourceLock.resource_key.like("ram:%"),
                ResourceLock.released_at.is_(None),
                Run.id != run.id,
            )
        )
        .scalars()
    )
    reserved = sum((allocation or {}).get("ram_mib", 0) for allocation in allocations)
    return {
        "required_mib": required_mib,
        "available_mib": available_mib
        if isinstance(available_mib, (int, float)) and available_mib >= 0
        else None,
        "reserved_mib": reserved,
        "headroom_mib": 1024,
    }


def reserve_memory(session, run, available_mib, required_mib):
    """Conservative admission: observed available RAM minus other live reservations."""
    if not required_mib:
        return True
    observed = memory_observation(session, run, available_mib, required_mib)
    if observed["available_mib"] is None:
        return False
    if observed["available_mib"] - observed["reserved_mib"] - observed["headroom_mib"] < required_mib:
        return False
    owned = session.scalar(
        select(ResourceLock).where(
            ResourceLock.resource_key == "ram:" + run.id, ResourceLock.released_at.is_(None)
        )
    )
    if owned is None:
        session.add(ResourceLock(resource_key="ram:" + run.id, run_id=run.id))
    run.allocated_resources = {**run.allocated_resources, "ram_mib": required_mib}
    session.flush()
    return True


def resource_wait(run):
    """Expose the last admission observation only while this Run is still queued."""
    if run.status != "queued":
        return None
    value = run.metadata_json.get("resource_wait")
    return {**value, "run_id": run.id} if isinstance(value, dict) else None


def latest_resource_wait(runs):
    observations = [value for run in runs if (value := resource_wait(run))]
    return max(observations, key=lambda value: value["checked_at"], default=None)
