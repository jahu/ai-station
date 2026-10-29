"""Durable UTC instants for timezone-aware schedules; workers execute workloads."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_coding_policy import auto_local_coding, coding_provider, external_coding
from app.agent_media_schema import fixed_media_only
from app.agent_schema import AgentSettings
from app.agent_tools import agent_tool, effective_permissions
from app.db import utcnow
from app.local_provider import model_endpoint
from app.models import Agent, Project, Run
from app.providers import ProviderError
from app.runs import create_run, create_task
from app.schedule_time import next_cron
from app.state import TERMINAL


def compute_next(agent: Agent, *, after=None):
    after = after or utcnow()
    if agent.trigger == "cron" and agent.cron_expr:
        return next_cron(agent.cron_expr, agent.schedule_timezone or "UTC", after)
    if agent.trigger == "interval" and agent.interval_seconds:
        return after + timedelta(seconds=agent.interval_seconds)
    if agent.trigger == "datetime" and agent.run_at and agent.run_at > after:
        return agent.run_at
    return None


def active_run(session, agent_id):
    return session.scalar(
        select(Run.id).where(Run.agent_id == agent_id, Run.status.not_in(TERMINAL)).limit(1)
    )


def launch_agent(
    session: Session,
    agent: Agent,
    *,
    triggered_by: str,
    definition=None,
    before_publish=None,
    avatar_appearance_recipe=...,
    avatar_whole_recipe=...,
) -> str:
    if not agent.enabled:
        raise ValueError("Enable the reviewed definition before running this agent")
    if active_run(session, agent.id):
        raise ValueError("This agent already has an active Run")
    # Activation validated the future timestamp; an already-due one-shot time is
    # expected here. Revalidate the rest of the persisted execution contract.
    definition = definition or AgentSettings.model_validate(
        {key: getattr(agent, key) for key in AgentSettings.model_fields} | {"enabled": False}
    )
    if "create_media" in definition.tools and definition.media is None:
        raise ValueError("Review media output settings before running this agent")
    from app.market_feeds import stock_permissions, validate_stock_scope

    validate_stock_scope(session, definition.market)
    if (
        not definition.model
        and not external_coding(definition.tools)
        and definition.tools != ["market_watch"]
        and not fixed_media_only(definition)
    ) or any(not agent_tool(name).operational for name in definition.tools):
        raise ValueError("Agent model or tools are not operational")
    if "web_search" in definition.tools and not definition.search_query:
        raise ValueError("web_search requires an explicit public search query")
    if "http_fetch" in definition.tools and not definition.fetch_urls:
        raise ValueError("http_fetch requires 1 to 3 explicit public URLs")
    from app.agent_workflow import planned_steps
    from app.skills import SkillError, snapshot_skills

    try:
        skill_snapshots = snapshot_skills(definition.skills)
        steps = planned_steps(definition)
    except SkillError as exc:
        raise ValueError(str(exc)) from exc
    if before_publish is not None:
        # This controller-only preparation has not changed durable state. SQLite
        # uses BEGIN IMMEDIATE even for reads; release it before Runner metadata.
        session.commit()
    if auto_local_coding(definition.tools, definition.model):
        from app.coding_model_routing import select_coding_model

        select_coding_model(session)
        endpoint = ""
    else:
        endpoint = (
            ""
            if external_coding(definition.tools)
            or definition.tools == ["market_watch"]
            or fixed_media_only(definition)
            else model_endpoint(definition.model, session)
        )
    data_inputs = None
    if "python_data" in definition.tools:
        from app.data_agents import freeze_inputs, require_runtime

        if before_publish is not None:
            session.commit()
        require_runtime()
        from app.agent_coding_policy import coding_research_steps

        data_inputs = (
            freeze_inputs(session, definition.data, research=True)
            if coding_research_steps(definition.tools)
            else freeze_inputs(session, definition.data)
        )
    media_inputs = None
    avatar_appearance = {}
    if definition.media:
        from app.agent_media import freeze_inputs as freeze_media_inputs

        media_inputs = freeze_media_inputs(session, definition.media)
        if definition.media.kind == "avatar":
            if definition.media.request.generation_profile:
                from app.whole_avatars import capabilities as whole_capabilities
                from app.whole_avatars import frozen_recipe as frozen_whole
                from app.whole_avatars import verify_recipe as verify_whole

                profile = whole_capabilities()
                recipe = (
                    verify_whole(profile, profile.get("recipe"))
                    if avatar_whole_recipe is ...
                    else frozen_whole(avatar_whole_recipe)
                )
                verify_whole(profile, recipe)
                avatar_appearance = {"avatar_whole_recipe": recipe}
            else:
                from app.avatar_appearance import frozen_recipe, select_recipe
                from app.avatars import capabilities as avatar_capabilities

                recipe = (
                    select_recipe(avatar_capabilities(), definition.media.request)
                    if avatar_appearance_recipe is ...
                    else frozen_recipe({"appearance_recipe": avatar_appearance_recipe})
                )
                avatar_appearance = {"avatar_appearance_recipe": recipe}
    market_email_approval = None
    if definition.market is not None and definition.market.email is not None:
        from app.market_email import authorization

        market_email_approval = authorization(session, agent, definition.market).id
    report_email_approval = None
    if definition.notification_policy.report_email:
        from app.agent_report_email import authorization

        grant = authorization(session, agent, definition)
        report_email_approval = grant.id if grant else None
    if before_publish is not None:
        # Internal controllers can recheck current authority after read-only
        # runtime/source preparation, before any execution graph is published.
        before_publish()
        if not agent.enabled or active_run(session, agent.id):
            raise ValueError("Agent activation or active execution changed during preparation")
    task = create_task(
        session,
        title=agent.name,
        prompt=definition.goal,
        capability="agent.workflow",
        intent="agent",
        agent_id=agent.id,
        project_id=agent.project_id,
    )
    from app.project_checks import project_check_policy

    run = create_run(
        session,
        task,
        run_type="agent",
        capability="agent.workflow",
        executor_type="agent_workflow",
        execution_target="container",
        parameters={
            "definition": definition.model_dump(mode="json"),
            **avatar_appearance,
            **({"media_inputs": media_inputs} if media_inputs is not None else {}),
            **({"data_inputs": data_inputs} if data_inputs is not None else {}),
            **(
                {
                    "coding_project_policy": project_check_policy(
                        session.get(Project, str(definition.project_id))
                    )
                }
                if coding_provider(definition.tools) is not None and definition.project_id is not None
                else {}
            ),
            "endpoint": endpoint,
            "skill_snapshots": skill_snapshots,
            **({"market_email_approval_id": market_email_approval} if market_email_approval else {}),
            **({"report_email_approval_id": report_email_approval} if report_email_approval else {}),
            "steps": steps,
        },
        permissions=effective_permissions(definition.tools)
        + stock_permissions(definition.market)
        + (
            ["email_send", "network_external"]
            if market_email_approval or definition.notification_policy.report_email
            else []
        ),
        # Result delivery is controller-owned; execution children filter these
        # notification-only grants before reaching typed native tool requests.
        retry_class="inspect",
        triggered_by=triggered_by,
    )
    run.metadata_json = {
        **run.metadata_json,
        "execution_location": "external" if external_coding(definition.tools) else "local",
    }
    now = utcnow()
    agent.last_run_at = now
    if (
        definition.require_approval
        or coding_provider(definition.tools) is not None
        and definition.workflow_mode == "gated"
    ):
        from app.approvals import request_run_approval

        request_run_approval(
            session,
            run,
            action="agent.execute",
            reason="This agent requires approval before each Run",
            payload={
                "agent_id": agent.id,
                "name": agent.name,
                "model": agent.model,
                "tools": list(agent.tools),
                "skills": list(agent.skills),
                "workflow_mode": definition.workflow_mode,
                "steps": [step["key"] for step in steps],
                "triggered_by": triggered_by,
                **(
                    {
                        "project_id": agent.project_id,
                        "execution_location": "external",
                        "coding_provider": coding_provider(definition.tools),
                        "source_scope": "Goal, reviewed guidance and relevant source from the linked project are shared with the selected external coding provider.",
                    }
                    if external_coding(definition.tools)
                    else {}
                ),
            },
        )
    else:
        agent.last_status = "queued"
    if triggered_by != "retry":
        if agent.trigger == "datetime":
            agent.enabled, agent.next_run_at = False, None
        elif triggered_by == "scheduler":
            agent.next_run_at = compute_next(agent, after=now)
    session.flush()
    return run.id


def workflow_retryable(session: Session, source: Run) -> bool:
    from app.state import RunStatus

    if source.executor_type != "agent_workflow":
        return False
    if source.status in {RunStatus.FAILED.value, RunStatus.INTERRUPTED.value}:
        return True
    if source.status != RunStatus.SUCCEEDED.value:
        return False
    if source.parameters.get("definition", {}).get("tools") == ["python_data"]:
        latest = session.scalar(
            select(Run)
            .where(Run.task_id == source.task_id, Run.executor_type == "agent_data_result")
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
        if latest is not None and latest.metadata_json.get("data_result") and latest.status == "succeeded":
            return False
    children = (
        session.scalars(select(Run).where(Run.task_id == source.task_id, Run.id != source.id))
        if coding_provider(source.parameters.get("definition", {}).get("tools", [])) is not None
        else session.scalars(select(Run).where(Run.parent_run_id == source.id))
    )
    return any(child.status in {RunStatus.FAILED.value, RunStatus.INTERRUPTED.value} for child in children)


def workflow_source(session: Session, run: Run) -> Run:
    from app.agent_workflow import workflow_parent

    return workflow_parent(session, run) or run


def retry_view(session: Session, run: Run) -> dict:
    from app.notices import retry_policy

    return {
        "allowed": (
            workflow_retryable(session, run)
            and retry_policy((run.parameters.get("definition") or {}).get("retry_policy")).mode == "manual"
            and not run.metadata_json.get("retry_run_id")
        ),
        "retry_run_id": run.metadata_json.get("retry_run_id"),
        "retry_of": run.metadata_json.get("retry_of"),
    }


def retry_workflow(session: Session, source: Run) -> str:
    from app.events import append_event
    from app.notices import retry_policy

    if source.executor_type != "agent_workflow":
        raise ValueError("Only a workflow Run can be retried")
    if not workflow_retryable(session, source):
        raise ValueError("Retry is available after failure or interruption, not after success or cancel")
    if retry_policy((source.parameters.get("definition") or {}).get("retry_policy")).mode != "manual":
        raise ValueError("This workflow's saved policy does not allow retry")
    if source.metadata_json.get("retry_run_id"):
        raise ValueError("This workflow already has a retry; inspect that Run")
    agent = session.get(Agent, source.agent_id)
    if agent is None:
        raise ValueError("Agent not found")
    definition = AgentSettings.model_validate(source.parameters.get("definition") or {})
    from app.agent_workspace import workspace_retry_definition

    definition = workspace_retry_definition(session, source, definition)
    run_id = launch_agent(
        session,
        agent,
        triggered_by="retry",
        definition=definition,
        avatar_appearance_recipe=source.parameters.get("avatar_appearance_recipe"),
        avatar_whole_recipe=source.parameters.get("avatar_whole_recipe"),
    )
    retry = session.get(Run, run_id)
    retry.metadata_json = {**retry.metadata_json, "retry_of": source.id}
    retry.parameters = {**retry.parameters, "retry_of": source.id}
    source.metadata_json = {**source.metadata_json, "retry_run_id": run_id}
    append_event(session, source.id, "workflow.retry_requested", {"retry_run_id": run_id})
    session.flush()
    return run_id


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
        if agent.owner_id is None:
            # Transitional legacy service path, removed at the account cutover.
            run_id = _schedule_one(session, agent)
        else:
            from app.data_access import DataScope, ScopedSession
            from app.data_context import bind_data_scope
            from app.models import User

            scope = DataScope(agent.owner_id, execution=True)
            with ScopedSession(
                bind=session.connection(), scope=scope, join_transaction_mode="create_savepoint"
            ) as owned:
                with bind_data_scope(scope):
                    current = owned.get(Agent, agent.id)
                    user = owned.get(User, agent.owner_id)
                    if user is None or not user.enabled or user.bootstrap_pending:
                        current.enabled, current.next_run_at, current.last_status = (
                            False,
                            None,
                            "account_disabled",
                        )
                        run_id = None
                    else:
                        run_id = _schedule_one(owned, current)
                    owned.commit()
            session.expire(agent)
        if run_id is not None:
            created.append(run_id)
    from app.worktree_expiry import expire_due_worktrees

    created.extend(expire_due_worktrees(session))
    return created


def _schedule_one(session, agent):
    from app.data_access import DataAccessError

    if active_run(session, agent.id):
        # Coalesce missed recurring slots; never overlap or accumulate backlog.
        if agent.trigger != "datetime":
            agent.next_run_at = compute_next(agent)
        return None
    try:
        with session.begin_nested():
            return launch_agent(session, agent, triggered_by="scheduler")
    except (ValueError, ProviderError, DataAccessError):
        agent.enabled, agent.next_run_at, agent.last_status = False, None, "misconfigured"
        return None
