"""Durable UTC scheduling. Only the worker executes agent workloads."""

from datetime import datetime, timedelta

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_schema import AgentSettings
from app.agent_tools import AGENT_TOOLS, effective_permissions
from app.db import utcnow
from app.local_provider import model_endpoint
from app.models import Agent, Run
from app.providers import ProviderError
from app.runs import create_run, create_task
from app.state import TERMINAL


def compute_next(agent: Agent, *, after=None):
    after = after or utcnow()
    if agent.trigger == "cron" and agent.cron_expr:
        return croniter(agent.cron_expr, after, max_years_between_matches=5).get_next(datetime)
    if agent.trigger == "interval" and agent.interval_seconds:
        return after + timedelta(seconds=agent.interval_seconds)
    if agent.trigger == "datetime" and agent.run_at and agent.run_at > after:
        return agent.run_at
    return None


def active_run(session, agent_id):
    return session.scalar(
        select(Run.id).where(Run.agent_id == agent_id, Run.status.not_in(TERMINAL)).limit(1)
    )


def launch_agent(session: Session, agent: Agent, *, triggered_by: str) -> str:
    if not agent.enabled:
        raise ValueError("Enable the reviewed definition before running this agent")
    if active_run(session, agent.id):
        raise ValueError("This agent already has an active Run")
    # Activation validated the future timestamp; an already-due one-shot time is
    # expected here. Revalidate the rest of the persisted execution contract.
    definition = AgentSettings.model_validate(
        {key: getattr(agent, key) for key in AgentSettings.model_fields} | {"enabled": False}
    )
    if not definition.model or any(not AGENT_TOOLS[name].operational for name in definition.tools):
        raise ValueError("Agent model or tools are not operational")
    endpoint = model_endpoint(agent.model, session)
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
        execution_target="container",
        parameters={"definition": definition.model_dump(mode="json"), "endpoint": endpoint},
        permissions=effective_permissions(agent.tools),
        retry_class="inspect",
        triggered_by=triggered_by,
    )
    now = utcnow()
    agent.last_run_at, agent.last_status = now, "queued"
    if agent.trigger == "datetime":
        agent.enabled, agent.next_run_at = False, None
    elif triggered_by == "scheduler":
        agent.next_run_at = compute_next(agent, after=now)
    session.flush()
    return run.id


def due_agents(session: Session):
    return list(
        session.scalars(
            select(Agent)
            .where(
                Agent.enabled.is_(True),
                Agent.provider == "local-openai-compatible",
                Agent.trigger != "manual",
                Agent.next_run_at.is_not(None),
                Agent.next_run_at <= utcnow(),
            )
            .order_by(Agent.next_run_at, Agent.id)
            .limit(100)
        )
    )


def scheduler_tick(session: Session) -> list[str]:
    created = []
    for agent in due_agents(session):
        if active_run(session, agent.id):
            # Coalesce missed recurring slots; never overlap or accumulate backlog.
            if agent.trigger != "datetime":
                agent.next_run_at = compute_next(agent)
            continue
        try:
            created.append(launch_agent(session, agent, triggered_by="scheduler"))
        except (ValueError, ProviderError):
            agent.enabled, agent.next_run_at, agent.last_status = False, None, "misconfigured"
    return created
