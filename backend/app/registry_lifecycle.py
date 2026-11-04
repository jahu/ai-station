"""Account-scoped registry tombstones without deleting historical provenance."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import inspect, select

from app.db import utcnow
from app.models import Agent, Project, Run, Task, Worktree
from app.state import TERMINAL


class RegistryDeletedError(ValueError):
    pass


class ConfirmedDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirm deletion explicitly")
        return value


class RegistryDeleteOne(ConfirmedDeletion):
    expected_updated_at: datetime


class RegistryDeleteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    expected_updated_at: datetime


class RegistryDeleteBatch(ConfirmedDeletion):
    items: list[RegistryDeleteItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Select each item only once")
        return self


def delete_registry(session, model, items):
    """Validate the whole batch before mutating; caller owns the transaction."""
    rows = []
    for item in items:
        row = session.get(model, str(item.id))
        if row is None:
            raise HTTPException(404, f"{model.__name__} not found")
        if row.deleted_at is not None:
            continue
        if row.updated_at != item.expected_updated_at:
            raise HTTPException(409, "Selection changed. Reload and review before deleting.")
        rows.append(row)
    ids = [row.id for row in rows]
    if not ids:
        return 0
    linked = []
    if model is Project:
        linked = list(
            session.scalars(select(Agent).where(Agent.project_id.in_(ids), Agent.deleted_at.is_(None)))
        )
    agent_ids = ids if model is Agent else [row.id for row in linked]
    conditions = []
    if agent_ids:
        conditions.append(Run.agent_id.in_(agent_ids))
    if model is Project:
        conditions.append(Run.project_id.in_(ids))
    from sqlalchemy import or_

    if session.scalar(select(Run.id).where(or_(*conditions), Run.status.not_in(TERMINAL)).limit(1)):
        raise HTTPException(409, "Stop or finish active work before deleting this selection.")
    from app.agent_lifecycle import pause_agent

    for agent in rows if model is Agent else linked:
        pause_agent(session, agent)
        if model is Project:
            agent.project_id = None
    now = utcnow()
    for row in rows:
        row.deleted_at = now
        row.updated_at = now
    return len(rows)


def guard_registry_references(session, _context, _instances):
    """All producers, including legacy retries, must reject removed inputs.

    Existing history keeps its references. Fixed worktree expiry is housekeeping,
    not new execution against a removed project, and retains its owned-path checks.
    """
    for row in list(session.new) + list(session.dirty):
        if isinstance(row, Agent) and row.deleted_at is not None and row.enabled:
            raise RegistryDeletedError("Agent was deleted and cannot be enabled")
        if not isinstance(row, (Task, Run, Agent, Worktree)):
            continue
        if isinstance(row, (Task, Run)) and row.capability == "coding.worktree.remove":
            continue
        state = inspect(row)
        for name, model in (("project_id", Project), ("agent_id", Agent)):
            if not hasattr(row, name):
                continue
            value = getattr(row, name)
            if not value or (row not in session.new and not state.attrs[name].history.has_changes()):
                continue
            parent = next(
                (item for item in session.new if isinstance(item, model) and item.id == value), None
            )
            if parent is None:
                parent = session.get(model, value)
            if parent is not None and parent.deleted_at is not None:
                raise RegistryDeletedError(
                    f"{model.__name__} was deleted. Choose an existing definition for new work."
                )
