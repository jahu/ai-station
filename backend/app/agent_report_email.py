"""Reviewed result-email consent; publishing/transport are wired separately."""

from datetime import datetime, timedelta
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.agent_email_schema import TEMPLATE, consent_payload, definition_fingerprint, digest
from app.agent_schema import AgentSettings
from app.db import utcnow
from app.email_delivery import fingerprint, message_hash, reviewed_connector
from app.market_email import connector_revision
from app.models import Agent, Approval, EmailDelivery, Run
from app.providers import ProviderError

ACTION = "agent.report-email.enable"


class ReportEmailPolicyError(ValueError):
    """Only fixed public diagnostics may leave this boundary."""


def saved_definition(agent):
    if agent is None:
        raise ReportEmailPolicyError("Review a saved agent before configuring result email")
    return AgentSettings.model_validate(
        {key: getattr(agent, key) for key in AgentSettings.model_fields} | {"enabled": False}
    )


def target(session, scope):
    if scope is None:
        raise ReportEmailPolicyError("Choose reviewed result-email settings")
    try:
        connector, settings = reviewed_connector(session, scope.connector_id)
    except (HTTPException, ProviderError, ValueError, OSError) as exc:
        raise ReportEmailPolicyError("Review the enabled SMTP connector and its saved credential") from exc
    if connector_revision(connector) != scope.connector_revision:
        raise ReportEmailPolicyError("Email settings changed; review this agent's email scope again")
    if not set(scope.recipients).issubset(settings.allowed_recipients):
        raise ReportEmailPolicyError("Choose recipients from the saved SMTP allowlist")
    return connector, settings


def scope_payload(session, agent, definition):
    scope = definition.notification_policy.report_email
    _, settings = target(session, scope)
    return consent_payload(agent.id, reviewed_identity(session, agent, definition), scope, settings.sender)


def reviewed_identity(session, agent, definition):
    """A verified automatic workspace is a derivation of the reviewed scope.

    Do not renew or rewrite consent. Only the exact original definition plus
    its controller-created project can retain the original identity.
    """
    if definition.project_id is None:
        return definition
    from app.agent_workspace import workspace_retry_definition

    for root in session.scalars(
        select(Run).where(
            Run.agent_id == agent.id,
            Run.project_id == str(definition.project_id),
            Run.executor_type == "agent_workflow",
        )
    ):
        raw = root.parameters.get("definition")
        if not raw or raw.get("project_id") is not None:
            continue
        original = AgentSettings.model_validate(raw)
        try:
            derived = workspace_retry_definition(session, root, original)
        except ValueError:
            continue
        if definition_fingerprint(derived) == definition_fingerprint(definition):
            return original
    return definition


def latest_grant(session, agent_id):
    return session.scalar(
        select(Approval)
        .where(Approval.action == ACTION, Approval.payload["agent_id"].as_string() == str(agent_id))
        .order_by(Approval.requested_at.desc(), Approval.id.desc())
        .limit(1)
    )


def revoke(session, agent_id):
    for row in session.scalars(
        select(Approval).where(
            Approval.action == ACTION,
            Approval.payload["agent_id"].as_string() == str(agent_id),
            Approval.resolution == "granted",
        )
    ):
        row.resolution, row.resolved_at = "revoked", utcnow()


def grant(session, agent, definition, *, confirmed):
    scope = definition.notification_policy.report_email
    if scope is None or scope.mode != "automatic" or confirmed is not True:
        raise ReportEmailPolicyError("Explicitly approve automatic result email before enabling this agent")
    payload = scope_payload(session, agent, definition)
    revoke(session, agent.id)
    now = utcnow()
    row = Approval(
        action=ACTION,
        risk="high",
        reason="Operator approved completed agent results to these reviewed recipients.",
        payload={**payload, "scope_hash": digest(payload)},
        resolution="granted",
        requested_at=now,
        resolved_at=now,
    )
    session.add(row)
    session.flush()
    return row


def authorization(session, agent, definition=None, *, expected_id=None):
    saved = saved_definition(agent)
    definition = definition or saved
    if not agent.enabled:
        raise ReportEmailPolicyError("The result-email agent is paused")
    payload = scope_payload(session, agent, definition)
    if payload != scope_payload(session, agent, saved):
        raise ReportEmailPolicyError("The queued result no longer matches this agent's reviewed definition")
    scope = definition.notification_policy.report_email
    if scope.mode == "review":
        if expected_id is not None:
            raise ReportEmailPolicyError("A reviewed message cannot inherit an automatic delivery grant")
        return None
    row = latest_grant(session, agent.id)
    if (
        row is None
        or row.resolution != "granted"
        or expected_id is not None
        and row.id != expected_id
        or row.payload != {**payload, "scope_hash": digest(payload)}
    ):
        raise ReportEmailPolicyError("Enable and explicitly approve this agent's current result-email scope")
    return row


def authorization_public(session, agent):
    if session is None or not (agent.notification_policy or {}).get("report_email"):
        return None
    definition = saved_definition(agent)
    scope = definition.notification_policy.report_email
    if scope is None:
        return None
    try:
        _, settings = target(session, scope)
    except ValueError as exc:
        return {"mode": scope.mode, "valid": False, "ready": False, "reason": str(exc)}
    envelope = {"ready": True, "sender": settings.sender, "recipients": list(scope.recipients)}
    try:
        row = authorization(session, agent, definition)
    except ValueError as exc:
        return {**envelope, "mode": scope.mode, "valid": False, "reason": str(exc)}
    return {
        **envelope,
        "id": row.id if row else None,
        "mode": scope.mode,
        "valid": True,
        "recipients": list(scope.recipients),
        "template": "agent-result-v1",
    }


def delivery_context(session, source):
    from app.agent_workflow import workflow_parent

    root = workflow_parent(session, source)
    if root and root.parameters.get("workspace_root_run_id"):
        from app.agent_workspace import validate_workspace_binding

        validate_workspace_binding(session, root)
        root = session.get(Run, root.parameters["workspace_root_run_id"])
    if (
        root is None
        or root.id == source.id
        or root.task_id != source.task_id
        or root.agent_id != source.agent_id
        or not source.agent_id
        or root.task.metadata_json.get("stop_requested_at")
    ):
        raise ReportEmailPolicyError("The completed result is not an active agent workflow outcome")
    definition = AgentSettings.model_validate(root.parameters["definition"])
    if definition.notification_policy.report_condition:
        from app.agent_alerts import may_notify

        if not may_notify(session, source, definition.notification_policy):
            raise ReportEmailPolicyError("The reviewed success notification criterion was not met")
    agent = session.get(Agent, source.agent_id)
    grant = authorization(
        session, agent, definition, expected_id=root.parameters.get("report_email_approval_id")
    )
    for permission in ("email_send", "network_external"):
        from app.permissions import require

        require(root.effective_permissions, permission)
    scope = definition.notification_policy.report_email
    if scope.mode == "automatic" and (
        grant is None or grant.id != root.parameters.get("report_email_approval_id")
    ):
        raise ReportEmailPolicyError("Automatic result delivery is missing its frozen activation grant")
    return root, definition, scope, grant


def automatic_deadline(root, source, definition):
    values = [(root.started_at or root.created_at) + timedelta(seconds=definition.maximum_runtime)]
    for raw in [
        root.parameters.get("media_deadline_at"),
        root.parameters.get("agent_coding_deadline"),
        source.parameters.get("deadline_at"),
    ]:
        if raw:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is None:
                raise ReportEmailPolicyError("Result email requires its original timezone-aware deadline")
            values.append(value)
    deadline = min(values)
    if utcnow() >= deadline:
        raise ReportEmailPolicyError("The agent budget expired before automatic result delivery")
    return deadline.isoformat()


def publish(session, source):
    from app.agent_email_results import result_snapshot
    from app.approvals import request_run_approval
    from app.events import append_event
    from app.runs import create_run
    from app.task_control import lock_task

    lock_task(session, source.task)
    root, definition, scope, grant = delivery_context(session, source)
    delivery_id = str(uuid5(UUID(root.id), TEMPLATE))
    existing = session.get(EmailDelivery, delivery_id)
    if existing:
        if existing.payload.get("agent_result", {}).get("root_run_id") != root.id:
            raise ReportEmailPolicyError("The result delivery identity is occupied by another message")
        return existing
    connector, settings = target(session, scope)
    result = result_snapshot(session, source, root, definition, scope)
    reference = {
        "root_run_id": root.id,
        "source_run_id": source.id,
        "template": TEMPLATE,
        "definition_hash": definition_fingerprint(definition),
        "result_hash": digest(result),
        "grant_id": grant.id if grant else None,
        "deadline_at": automatic_deadline(root, source, definition) if scope.mode == "automatic" else None,
    }
    envelope = {key: result["message"][key] for key in ("subject", "body")}
    payload = {
        "connector_id": connector.id,
        "sender": settings.sender,
        "recipients": list(scope.recipients),
        **envelope,
        "connector_fingerprint": fingerprint(connector),
        "agent_result": reference,
        **({"attachments": result["attachments"]} if result.get("attachments") else {}),
    }
    child = create_run(
        session,
        source.task,
        run_type="connector",
        capability="email.send",
        executor_type="email_send",
        execution_target="container",
        operation_key=f"agent-result-email:{root.id}",
        parameters={
            "tool": "email.send",
            "connector_id": connector.id,
            "connector_fingerprint": fingerprint(connector),
            "smtp": settings.model_dump(),
            "delivery_id": delivery_id,
            "message": {key: payload[key] for key in ("sender", "recipients", "subject", "body")},
            "agent_result": reference,
            **({"attachments": result["attachments"]} if result.get("attachments") else {}),
        },
        permissions=[
            "email_send",
            "network_external",
            *(["filesystem_read"] if result.get("attachments") else []),
        ],
        retry_class="inspect",
        parent_run_id=source.id,
        triggered_by=source.triggered_by,
    )
    receipt = EmailDelivery(
        id=delivery_id,
        connector_id=connector.id,
        run_id=child.id,
        payload=payload,
        payload_hash=message_hash(payload),
        message_id=f"<{delivery_id}@ai-station.local>",
        state="prepared",
    )
    session.add(receipt)
    session.flush()
    if scope.mode == "review":
        request_run_approval(
            session,
            child,
            action="email.send",
            reason="Review the complete saved agent result and recipients before sending.",
            payload={
                "delivery_id": receipt.id,
                "payload_hash": receipt.payload_hash,
                "recipients": list(scope.recipients),
                "sender": settings.sender,
                "subject": envelope["subject"],
                **({"attachments": result["attachments"]} if result.get("attachments") else {}),
            },
        )
    append_event(
        session,
        source.id,
        "agent.result_email.prepared",
        {
            "delivery_id": receipt.id,
            "run_id": child.id,
            "mode": scope.mode,
            "excerpted": result["message"]["excerpted"],
        },
    )
    source.metadata_json = {
        **source.metadata_json,
        "result_email": {"delivery_id": receipt.id, "run_id": child.id, "mode": scope.mode},
    }
    return receipt


def validate_submission(session, run, receipt):
    from app.agent_email_results import result_snapshot

    # This is also called after SMTP connection. The worker session deliberately
    # retains ORM identities across commits; discard cached authority then read
    # current consent, connector, source, Task and receipt again.
    session.flush()
    session.expire_all()
    reference = run.parameters.get("agent_result")
    if (
        not isinstance(reference, dict)
        or set(reference)
        != {
            "root_run_id",
            "source_run_id",
            "template",
            "definition_hash",
            "result_hash",
            "grant_id",
            "deadline_at",
        }
        or "market_alert" in run.parameters
        or reference != receipt.payload.get("agent_result")
        or reference.get("template") != TEMPLATE
    ):
        raise ReportEmailPolicyError("The result-email reference is invalid or mixed with another policy")
    source = session.get(Run, reference["source_run_id"])
    if (
        source is None
        or run.parent_run_id != source.id
        or run.task_id != source.task_id
        or run.agent_id != source.agent_id
        or receipt.id != run.parameters.get("delivery_id")
    ):
        raise ReportEmailPolicyError("The frozen message does not belong to its source result")
    root, definition, scope, grant = delivery_context(session, source)
    if (
        root.id != reference["root_run_id"]
        or definition_fingerprint(definition) != reference["definition_hash"]
        or (grant.id if grant else None) != reference["grant_id"]
        or receipt.id != str(uuid5(UUID(root.id), TEMPLATE))
        or run.operation_key != f"agent-result-email:{root.id}"
    ):
        raise ReportEmailPolicyError("The frozen result-email consent no longer matches this workflow")
    deadline = automatic_deadline(root, source, definition) if scope.mode == "automatic" else None
    if reference["deadline_at"] != deadline:
        raise ReportEmailPolicyError("The result email cannot replace its original delivery budget")
    connector, settings = target(session, scope)
    try:
        result = result_snapshot(session, source, root, definition, scope)
    except (ValueError, OSError) as exc:
        raise ReportEmailPolicyError("The completed result changed or is no longer available") from exc
    if result.get("attachments"):
        from app.permissions import require

        require(run.effective_permissions, "filesystem_read")
    if (
        receipt.payload.get("attachments") != result.get("attachments")
        or run.parameters.get("attachments") != result.get("attachments")
        or digest(result) != reference["result_hash"]
        or receipt.connector_id != connector.id
        or receipt.payload["sender"] != settings.sender
        or receipt.payload["recipients"] != scope.recipients
        or message_hash(receipt.payload) != receipt.payload_hash
        or run.parameters.get("message")
        != {key: receipt.payload[key] for key in ("sender", "recipients", "subject", "body")}
        or receipt.payload.get("connector_fingerprint") != fingerprint(connector)
        or run.parameters.get("connector_fingerprint") != fingerprint(connector)
        or any(receipt.payload[key] != result["message"][key] for key in ("subject", "body"))
    ):
        raise ReportEmailPolicyError("The frozen email differs from its verified result or reviewed envelope")
    if scope.mode == "review":
        from app.approvals import latest_approval

        approval = latest_approval(session, run.id)
        if (
            approval is None
            or approval.resolution != "granted"
            or approval.action != "email.send"
            or approval.payload.get("payload_hash") != receipt.payload_hash
            or approval.payload.get("attachments") != result.get("attachments")
        ):
            raise ReportEmailPolicyError("The complete result message needs its own current approval")
    return scope.mode
