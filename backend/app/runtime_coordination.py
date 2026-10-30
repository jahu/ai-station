"""Minimal machine facts across private Runs; never an unscoped Run lookup."""

from sqlalchemy import literal, or_, select

from app.data_access import ScopedSession
from app.models import Run
from app.state import TERMINAL


def foreign_runtime_work(session, instance, *, operations=None):
    """Only a busy boolean for this managed model, without IDs or user content.

    Ordinary ORM sessions already coordinate all Runs. Owner-scoped sessions
    need this fixed infrastructure projection before changing a shared runtime.
    """
    if not isinstance(session, ScopedSession):
        return False
    scope = session.scope
    if instance.ownership != "managed" or instance.runtime_key != "llama.cpp":
        raise ValueError("Runtime coordination requires a managed llama.cpp instance")
    if operations is not None and not set(operations) <= {"llama_load", "llama_stop", "llama_health"}:
        raise ValueError("Unknown managed model operation")
    query = (
        select(literal(1))
        .select_from(Run.__table__)
        .where(
            Run.status.not_in(TERMINAL),
            or_(Run.owner_id.is_(None), Run.owner_id != scope.user_id),
            or_(
                Run.parameters["instance_id"].as_string() == instance.id,
                Run.parameters["endpoint"].as_string() == instance.endpoint,
            ),
        )
    )
    if operations is not None:
        query = query.where(Run.executor_type.in_(operations))
    return session.connection().scalar(query.limit(1)) is not None
