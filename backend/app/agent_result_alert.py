"""One durable notification check for an already verified data result."""

import time
from datetime import datetime

from sqlalchemy import select

from app.agent_alerts import data_report, evaluate, frozen_definition, report_snapshot, verify_snapshot
from app.agent_schema import AgentSettings
from app.agent_workflow import workflow_parent
from app.db import utcnow
from app.dependencies import depend_on
from app.events import append_event
from app.models import Run
from app.permissions import require
from app.runs import create_run, mark_failed, transition
from app.state import RunStatus
from app.task_control import lock_task

NAME = "agent_result_alert"
PERMISSIONS = ["filesystem_read", "network_read"]


def producer(session, source):
    saved = data_report(session, source)
    python = session.get(Run, source.parameters["python_run_id"])
    generation = session.get(Run, python.parameters.get("generation_run_id"))
    if (
        generation is None
        or generation.executor_type != "agent_data_generate"
        or generation.status != "succeeded"
        or generation.task_id != source.task_id
        or generation.agent_id != source.agent_id
        or generation.project_id != source.project_id
        or python.parent_run_id != generation.id
        or generation.metadata_json.get("python_run_id") != python.id
        or generation.parameters.get("agent_data") != source.parameters.get("agent_data")
        or not generation.parameters.get("model", "").startswith("llamacpp:")
    ):
        raise ValueError("The alert must use this result's reviewed local generation model")
    return saved, generation


def publish(session, source):
    lock_task(session, source.task)
    if source.task.metadata_json.get("stop_requested_at"):
        raise ValueError("A stopped workflow cannot publish a late notification check")
    key = "result-alert:" + source.id
    prior = session.scalar(select(Run).where(Run.task_id == source.task_id, Run.operation_key == key))
    if prior is not None:
        if (
            prior.executor_type != NAME
            or prior.parent_run_id != source.id
            or prior.agent_id != source.agent_id
        ):
            raise ValueError("The result alert receipt belongs to another source")
        return prior
    saved, generation = producer(session, source)
    definition = AgentSettings.model_validate(frozen_definition(source))
    policy = definition.notification_policy
    if not policy.report_condition or not (policy.on_success or policy.report_email):
        raise ValueError("Choose a reviewed criterion and notification channel first")
    root = workflow_parent(session, source)
    for permission in PERMISSIONS:
        require(root.effective_permissions, permission)
    snapshot, _ = report_snapshot(session, source, saved["report_artifact"])
    child = create_run(
        session,
        source.task,
        run_type="agent",
        capability="agent.result.alert",
        executor_type=NAME,
        execution_target="container",
        operation_key=key,
        parent_run_id=source.id,
        permissions=PERMISSIONS,
        retry_class="inspect",
        parameters={
            "source_run_id": source.id,
            "source_report": snapshot,
            "definition": frozen_definition(source),
            "generation_run_id": generation.id,
            "model": generation.parameters["model"],
            "endpoint": generation.parameters["endpoint"],
            "agent_coding_deadline": source.parameters["agent_coding_deadline"],
        },
    )
    depend_on(session, child, source)
    # Bind/reload only the already selected model through the existing lifecycle.
    # Preparation failure belongs to this child, never to Python or its result.
    try:
        with session.begin_nested():
            if datetime.fromisoformat(child.parameters["agent_coding_deadline"]) <= utcnow():
                raise ValueError("Original agent budget expired before notification model preparation")
            from app.llama import prepare_consumer

            prepare_consumer(session, child)
    except Exception as exc:
        child.parameters = {**child.parameters, "preparation_error": str(exc)[:600]}
    child.summary = "Check the reviewed notification criterion; data result retained."
    source.metadata_json = {
        **source.metadata_json,
        "report_alert": {
            "state": "checking",
            "check_run_id": child.id,
            "criterion": policy.report_condition,
            "current_report": snapshot,
        },
    }
    append_event(session, source.id, "agent.alert.queued", {"check_run_id": child.id})
    return child


def context(session, run):
    source = session.get(Run, run.parameters.get("source_run_id"))
    if (
        source is None
        or source.executor_type != "agent_data_result"
        or source.status != "succeeded"
        or run.parent_run_id != source.id
        or run.task_id != source.task_id
        or run.agent_id != source.agent_id
        or run.project_id != source.project_id
        or run.operation_key != "result-alert:" + source.id
        or run.parameters.get("definition") != frozen_definition(source)
        or run.parameters.get("agent_coding_deadline") != source.parameters.get("agent_coding_deadline")
        or (source.metadata_json.get("report_alert") or {}).get("check_run_id") != run.id
        or run.effective_permissions != PERMISSIONS
    ):
        raise ValueError("The notification check lost its exact successful result binding")
    saved, generation = producer(session, source)
    if generation.id != run.parameters.get("generation_run_id") or generation.parameters[
        "model"
    ] != run.parameters.get("model"):
        raise ValueError("Notification model selection changed after publication")
    verify_snapshot(session, source, run.parameters["source_report"])
    remaining = (datetime.fromisoformat(run.parameters["agent_coding_deadline"]) - utcnow()).total_seconds()
    if remaining <= 0:
        raise ValueError("Original agent budget expired before notification checking")
    return (
        source,
        AgentSettings.model_validate(frozen_definition(source)),
        saved,
        time.monotonic() + remaining,
    )


class ResultAlertExecutor:
    name = NAME

    def execute(self, session, run):
        from app.agent_executor import LocalAgentExecutor

        local = LocalAgentExecutor()
        if local._canceled(session, run):
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        source = None
        try:
            source, definition, saved, deadline = context(session, run)
            if run.parameters.get("preparation_error"):
                raise ValueError(run.parameters["preparation_error"])
            from app.llama import model_endpoint

            if model_endpoint(run.parameters["model"], session) != run.parameters["endpoint"]:
                raise ValueError("The notification model endpoint is no longer its owned ready instance")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            decision = evaluate(
                session,
                source,
                definition,
                saved["report_artifact"],
                deadline,
                local._consume,
                execution_run=run,
                model=run.parameters["model"],
            )
            session.refresh(run)
            if run.status in {"cancel_requested", "canceled"}:
                if run.status == "cancel_requested":
                    transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                source.metadata_json = {
                    **source.metadata_json,
                    "report_alert": {**source.metadata_json["report_alert"], "state": "canceled"},
                }
                return "done"
            # Decision, successful check and source notice/email publication are
            # one short transaction. A stopped Task cannot send a late result.
            lock_task(session, run.task)
            if run.task.metadata_json.get("stop_requested_at"):
                raise ValueError("The workflow was stopped before notification publication")
            with session.begin_nested():
                source.metadata_json = {**source.metadata_json, "report_alert": decision}
                run.metadata_json = {**run.metadata_json, "report_alert": decision}
                run.summary = decision["reason"]
                transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
                from app.notices import emit_agent_notice

                emit_agent_notice(session, source, "succeeded")
        except Exception as exc:
            session.refresh(run)
            if local._canceled(session, run):
                return "done"
            if source is not None:
                source.metadata_json = {
                    **source.metadata_json,
                    "report_alert": {**source.metadata_json.get("report_alert", {}), "state": "failed"},
                }
            run.summary = "Notification check failed; the completed data result is retained."
            mark_failed(session, run, "ResultAlertFailed", str(exc)[:1000])
        return "done"
