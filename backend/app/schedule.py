"""Scheduler helpers. The scheduler inserts runs; it does not execute them."""

from __future__ import annotations

from datetime import timedelta

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Agent
from app.permissions import permissions_for
from app.runs import create_run, create_task


def compute_next(agent: Agent, *, after=None):
    after = after or utcnow()
    if agent.trigger == "cron" and agent.cron_expr:
        return croniter(agent.cron_expr, after).get_next(type(after))
    if agent.trigger == "interval" and agent.interval_seconds:
        return after + timedelta(seconds=agent.interval_seconds)
    if agent.trigger == "datetime":
        return None
    return None


def due_agents(session: Session) -> list[Agent]:
    now = utcnow()
    return list(
        session.scalars(
            select(Agent).where(
                Agent.enabled.is_(True),
                Agent.trigger != "manual",
                Agent.next_run_at.is_not(None),
                Agent.next_run_at <= now,
            )
        )
    )


def launch_agent(session: Session, agent: Agent, *, triggered_by: str) -> str:
    task = create_task(
        session,
        title=agent.name,
        prompt=agent.goal,
        capability="agent.execute",
        intent="agent",
        agent_id=agent.id,
        project_id=agent.project_id,
    )
    run = create_run(
        session,
        task,
        run_type="agent",
        capability="agent.execute",
        executor_type="agent",
        execution_target=agent.execution_target or "host",
        parameters={"goal": agent.goal},
        requested_gpu="none",
        permissions=permissions_for(agent.permission_profile),
        retry_class="safe",
        triggered_by=triggered_by,
        agent_id=agent.id,
        project_id=agent.project_id,
    )
    now = utcnow()
    agent.last_run_at = now
    agent.last_status = "queued"
    if agent.trigger == "datetime":
        agent.enabled = False
        agent.next_run_at = None
    else:
        agent.next_run_at = compute_next(agent, after=now)
    agent.updated_at = now
    session.flush()
    return run.id


def scheduler_tick(session: Session) -> list[str]:
    created = []
    for agent in due_agents(session):
        created.append(launch_agent(session, agent, triggered_by="scheduler"))
    return created
