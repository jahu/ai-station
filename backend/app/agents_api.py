"""Reviewable local agent drafts and versioned lifecycle operations."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_media_schema import fixed_media_only
from app.agent_schema import AgentSettings
from app.agent_tools import AGENT_TOOLS, agent_tool, effective_permissions
from app.approvals import run_public
from app.db import session_scope, utcnow
from app.factory import draft_agent
from app.local_provider import model_endpoint
from app.models import Agent, Project, Run
from app.providers import ProviderError
from app.schedule import active_run, compute_next, launch_agent
from app.schedule_time import ScheduleTimezone
from app.serialize import agent_dict

router = APIRouter(prefix="/api/agents", tags=["agents"])
DB = Annotated[Session, Depends(session_scope)]


def market_email_authorization(session, agent):
    from app.market_email import authorization_public

    return authorization_public(session, agent)


def definition_dict(agent, session=None):
    from app.data_agents import data_readiness
    from app.market_feeds import stock_permissions, stock_readiness
    from app.market_schema import MarketScope

    email_authorization = market_email_authorization(session, agent)
    return {
        **agent_dict(agent),
        "data_readiness": data_readiness(session, agent.data, agent.tools)
        if "python_data" in agent.tools
        else None,
        "market_email_authorization": email_authorization,
        "market_readiness": stock_readiness(session, agent.market),
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
        "effective_permissions": effective_permissions([name for name in agent.tools if name in AGENT_TOOLS])
        + stock_permissions(MarketScope.model_validate(agent.market) if agent.market else None)
        + (
            ["email_send", "network_external"] if email_authorization and email_authorization["valid"] else []
        ),
    }


def get_agent(session, agent_id):
    row = session.get(Agent, str(agent_id))
    if row is None:
        raise HTTPException(404, "Agent not found")
    return row


def validate_target(body, session, agent=None, *, enabling=False):
    if body.media is not None and body.enabled:
        from app.agent_media import freeze_inputs, require_profile

        try:
            require_profile(body.media)
            freeze_inputs(session, body.media)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if (
        body.market is not None
        and body.market.provider == "finnhub"
        and (not enabling or body.enabled)
        and (body.enabled or body.market.feed is not None)
    ):
        from app.market_feeds import reviewed_connector, validate_stock_scope

        try:
            if body.enabled:
                validate_stock_scope(session, body.market)
            else:
                reviewed_connector(
                    session, body.market.feed.connector_id, body.market.feed.connector_revision
                )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if body.market is not None and body.market.email is not None and (not enabling or body.enabled):
        from app.market_email import authorization, target

        try:
            target(session, body.market)
            if body.enabled and not enabling:
                authorization(session, agent, body.market)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if body.project_id and session.get(Project, str(body.project_id)) is None:
        raise HTTPException(422, "Project does not exist")
    if "python_data" in body.tools and body.enabled:
        if body.model != "auto" and not body.model.startswith("llamacpp:"):
            raise HTTPException(409, "Choose Auto or an installed llama.cpp model for data coding")
        from app.data_agents import freeze_inputs, require_runtime

        try:
            require_runtime()
            from app.agent_coding_policy import coding_research_steps

            if coding_research_steps(body.tools):
                freeze_inputs(session, body.data, research=True)
            else:
                freeze_inputs(session, body.data)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    if body.github is not None:
        from app.agent_github import reviewed_connector

        try:
            reviewed_connector(session, body.github)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    from app.agent_coding_policy import auto_local_coding, external_coding

    if (
        body.enabled
        and not external_coding(body.tools)
        and body.tools != ["market_watch"]
        and not fixed_media_only(body)
    ):
        try:
            if auto_local_coding(body.tools, body.model):
                from app.coding_model_routing import select_coding_model

                select_coding_model(session)
            else:
                model_endpoint(body.model, session)
        except ProviderError as exc:
            raise HTTPException(409, str(exc)) from exc


def apply_settings(agent, body):
    for key, value in body.model_dump().items():
        if key == "schedule_timezone" and key not in body.model_fields_set and agent.schedule_timezone:
            continue
        if key == "project_id" and value is not None:
            value = str(value)
        if key in {"github", "data", "market", "media"} and value is not None:
            value = getattr(body, key).model_dump(mode="json")
        setattr(agent, key, value)
    agent.retry_policy = body.retry_policy.model_dump()
    agent.notification_policy = body.notification_policy.model_dump()
    try:
        agent.next_run_at = compute_next(agent) if agent.enabled else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    agent.updated_at = utcnow()


@router.get("/timezones")
def schedule_timezones():
    from app.schedule_time import timezones

    return sorted(timezones())


@router.get("/tools")
def tools():
    from app.agent_media import runtime_readiness
    from app.data_agents import runtime_capability

    capability = runtime_capability()
    media = runtime_readiness() if agent_tool("create_media").operational else {}
    return [
        {
            **asdict(agent_tool(name)),
            **({"operational": capability["available"]} if name == "python_data" else {}),
            **(
                {"operational": any(value["ready"] for value in media.values()), "outputs": media}
                if name == "create_media"
                else {}
            ),
        }
        for name in AGENT_TOOLS
    ]


@router.get("")
def agents(
    session: DB,
    project_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    statement = select(Agent).order_by(Agent.name, Agent.id).limit(limit).offset(offset)
    if project_id is not None:
        statement = statement.where(Agent.project_id == str(project_id))
    return [definition_dict(agent, session) for agent in session.scalars(statement)]


@router.post("", status_code=201)
def create(body: AgentSettings, session: DB):
    validate_target(body, session)
    agent = Agent()
    apply_settings(agent, body)
    session.add(agent)
    session.commit()
    return definition_dict(agent, session)


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    instruction: str = Field(min_length=1, max_length=16000)
    model: str = Field(default="", max_length=200)
    schedule_timezone: ScheduleTimezone = "UTC"


@router.post("/draft", status_code=201)
def draft(body: DraftBody, session: DB):
    agent = draft_agent(body.instruction, model=body.model, schedule_timezone=body.schedule_timezone)
    session.add(agent)
    session.commit()
    return definition_dict(agent, session)


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
    return {**definition_dict(agent, session), "runs": [run_public(session, run) for run in runs]}


@router.put("/{agent_id}")
def edit(agent_id: UUID, body: AgentUpdate, session: DB):
    agent = get_agent(session, agent_id)
    version(agent, body.expected_updated_at)
    if active_run(session, agent.id):
        raise HTTPException(409, "Cancel or finish the active Run before editing its agent")
    values = body.model_dump(exclude={"expected_updated_at"})
    if "schedule_timezone" not in body.model_fields_set:
        values["schedule_timezone"] = agent.schedule_timezone or "UTC"
    from pydantic import ValidationError

    try:
        settings = AgentSettings.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(error["msg"] for error in exc.errors())) from exc
    validate_target(settings, session, agent)
    if not settings.enabled or settings.market is None or settings.market.email is None:
        from app.market_email import revoke

        revoke(session, agent.id)
    apply_settings(agent, settings)
    session.commit()
    return definition_dict(agent, session)


class EnableBody(VersionBody):
    enabled: StrictBool
    confirm_market_email: StrictBool = False


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
    validate_target(settings, session, agent, enabling=True)
    from app.market_email import grant, revoke

    if body.enabled and settings.market is not None and settings.market.email is not None:
        try:
            grant(session, agent, settings.market, confirmed=body.confirm_market_email)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    else:
        revoke(session, agent.id)
    agent.enabled = body.enabled
    agent.next_run_at = compute_next(agent) if body.enabled else None
    agent.updated_at = utcnow()
    session.commit()
    return definition_dict(agent, session)


@router.post("/{agent_id}/run", status_code=202)
def run_now(agent_id: UUID, body: VersionBody, session: DB):
    agent = get_agent(session, agent_id)
    version(agent, body.expected_updated_at)
    try:
        run_id = launch_agent(session, agent, triggered_by="user")
    except (ValueError, ProviderError) as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return run_public(session, session.get(Run, run_id))


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
    return definition_dict(copy, session)
