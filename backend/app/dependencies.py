"""Scheduling prerequisites, separate from Run provenance/parentage."""

from sqlalchemy import select

from app.events import append_event
from app.models import Run, RunDependency
from app.state import TERMINAL


def depend_on(session, run, prerequisite):
    if run.status != "queued":
        raise ValueError("Only queued Runs can acquire prerequisites")
    frontier, visited = {prerequisite.id}, set()
    while frontier:
        if run.id in frontier:
            raise ValueError("Run dependency cycle")
        visited |= frontier
        if len(visited) > 10000:
            raise ValueError("Run dependency graph is too large")
        frontier = (
            set(
                session.scalars(
                    select(RunDependency.prerequisite_id).where(RunDependency.run_id.in_(frontier))
                )
            )
            - visited
        )
    if session.get(RunDependency, (run.id, prerequisite.id)) is None:
        session.add(RunDependency(run_id=run.id, prerequisite_id=prerequisite.id))
        append_event(session, run.id, "run.dependency_added", {"prerequisite_id": prerequisite.id})
        session.flush()


def failed_prerequisites(session, run):
    return list(
        session.scalars(
            select(Run.id)
            .join(RunDependency, RunDependency.prerequisite_id == Run.id)
            .where(RunDependency.run_id == run.id, Run.status.in_(TERMINAL), Run.status != "succeeded")
        )
    )
