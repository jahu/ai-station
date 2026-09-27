"""Reviewable local agent drafts and versioned lifecycle operations."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_schema import AgentSettings
from app.agent_tools import AGENT_TOOLS, effective_permissions
from app.db import session_scope, utcnow
from app.factory import draft_agent
from app.local_provider import model_endpoint
from app.models import Agent, Project, Run
from app.providers import ProviderError
from app.runs import run_dict
from app.schedule import active_run, compute_next, launch_agent
from app.serialize import agent_dict

router = APIRouter(prefix="/api/agents", tags=["agents"])
DB = Annotated[Session, Depends(session_scope)]


def definition_dict(agent):
    return {
        **agent_dict(agent),
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
        "effective_permissions": effective_permissions([name for name in agent.tools if name in AGENT_TOOLS]),
        "schedule_timezone": "UTC",
    }


def get_agent(session, agent_id):
    row = session.get(Agent, str(agent_id))
    if row is None:
        raise HTTPException(404, "Agent not found")
    return row


def validate_target(body, session):
    if body.project_id and session.get(Project, str(body.project_id)) is None:
        raise HTTPException(422, "Project does not exist")
    if body.enabled:
        try:
            model_endpoint(body.model, session)
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from exc


def apply_settings(agent, body):
    for key, value in body.model_dump().items():
        if key == "project_id" and value is not None:
            value = str(value)
        setattr(agent, key, value)
    agent.retry_policy = {"auto": False}
    agent.notification_policy = {"surface": "runs"}
    agent.next_run_at = compute_next(agent) if agent.enabled else None
    agent.updated_at = utcnow()


@router.get("/tools")
def tools():
    return [asdict(tool) for tool in AGENT_TOOLS.values()]


@router.get("")
def agents(session: DB, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return [
        definition_dict(agent)
        for agent in session.scalars(select(Agent).order_by(Agent.name, Agent.id).limit(limit).offset(offset))
    ]


@router.post("", status_code=201)
def create(body: AgentSettings, session: DB):
    validate_target(body, session)
    agent = Agent()
    apply_settings(agent, body)
    session.add(agent)
    session.commit()
    return definition_dict(agent)


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    instruction: str = Field(min_length=1, max_length=16000)
    model: str = Field(default="", max_length=200)


@router.post("/draft", status_code=201)
def draft(body: DraftBody, session: DB):
    agent = draft_agent(body.instruction, model=body.model)
    session.add(agent)
    session.commit()
    return definition_dict(agent)


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime


class AgentUpdate(AgentSettings):
    expected_updated_at: datetime


def version(agent, expected):
    if agent.updated_at != expected:
        raise HTTPException(409, "Agent definition changed. Reload before continuing.")


@router.get("/{agent_id}")
def detail(agent_id: UUID, session: DB):
    agent = get_agent(session, agent_id)
    runs = session.scalars(
        select(Run).where(Run.agent_id == agent.id).order_by(Run.created_at.desc()).limit(100)
    )
    return {**definition_dict(agent), "runs": [run_dict(run) for run in runs]}


@router.put("/{agent_id}")
def edit(agent_id: UUID, body: AgentUpdate, session: DB):
    agent = get_agent(session, agent_id)
    version(agent, body.expected_updated_at)
    if active_run(session, agent.id):
        raise HTTPException(409, "Cancel or finish the active Run before editing its agent")
    settings = AgentSettings.model_validate(body.model_dump(exclude={"expected_updated_at"}))
    validate_target(settings, session)
    apply_settings(agent, settings)
    session.commit()
    return definition_dict(agent)


class EnableBody(VersionBody):
    enabled: StrictBool


@router.post("/{agent_id}/enabled")
def set_enabled(agent_id: UUID, body: EnableBody, session: DB):
    agent = get_agent(session, agent_id)
    version(agent, body.expected_updated_at)
    from pydantic import ValidationError

    try:
        settings = AgentSettings.model_validate(
            {key: getattr(agent, key) for key in AgentSettings.model_fields} | {"enabled": body.enabled}
        )
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(error["msg"] for error in exc.errors())) from exc
    validate_target(settings, session)
    agent.enabled = body.enabled
    agent.next_run_at = compute_next(agent) if body.enabled else None
    agent.updated_at = utcnow()
    session.commit()
    return definition_dict(agent)


@router.post("/{agent_id}/run", status_code=202)
def run_now(agent_id: UUID, body: VersionBody, session: DB):
    agent = get_agent(session, agent_id)
    version(agent, body.expected_updated_at)
    try:
        run_id = launch_agent(session, agent, triggered_by="user")
    except (ValueError, ProviderError) as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return run_dict(session.get(Run, run_id))


@router.post("/{agent_id}/duplicate", status_code=201)
def duplicate(agent_id: UUID, body: VersionBody, session: DB):
    source = get_agent(session, agent_id)
    version(source, body.expected_updated_at)
    values = {key: getattr(source, key) for key in AgentSettings.model_fields}
    values.update(name=f"{source.name[:190]} (copy)", enabled=False)
    settings = AgentSettings.model_validate(values)
    copy = Agent()
    apply_settings(copy, settings)
    session.add(copy)
    session.commit()
    return definition_dict(copy)
