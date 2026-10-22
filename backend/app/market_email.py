"""Operator-scoped deterministic price alerts; no model-selected messages or recipients."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.db import utcnow
from app.dependencies import depend_on
from app.email_delivery import fingerprint, message_hash, reviewed_connector
from app.events import append_event
from app.market_schema import MarketScope
from app.models import Agent, Approval, EmailDelivery, MarketAlert, MarketObservation, Run
from app.permissions import require
from app.providers import ProviderError
from app.runs import create_run

ACTION = "agent.email.enable"
TEMPLATE = "market-threshold-v1"


class MarketEmailPolicyError(ValueError):
    """Static public policy diagnostics; never provider replies or credentials."""


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def connector_revision(connector):
    # Legacy connectors have a stable initial revision. New settings/credential
    # writes rotate the nonce; a health check changes neither nonce nor scope.
    return _hash(
        {
            "configuration": fingerprint(connector),
            "revision": connector.config_json.get("email_policy_revision")
            or connector.created_at.isoformat(),
        }
    )


def rotate_connector_revision(connector):
    connector.config_json = {**connector.config_json, "email_policy_revision": str(uuid4())}


def target(session, scope):
    if scope.email is None:
        raise MarketEmailPolicyError("Select reviewed email settings")
    try:
        connector, config = reviewed_connector(session, scope.email.connector_id)
    except (HTTPException, ProviderError, ValueError, OSError) as exc:
        raise MarketEmailPolicyError("Review the enabled SMTP connection and its saved credential") from exc
    if connector_revision(connector) != scope.email.connector_revision:
        raise MarketEmailPolicyError(
            "Email settings changed; review the connector and approve this agent again"
        )
    if not set(scope.email.recipients).issubset(config.allowed_recipients):
        raise MarketEmailPolicyError("Choose recipients from the saved SMTP allowlist")
    return connector, config


def scope_payload(session, agent_id, scope):
    connector, config = target(session, scope)
    return {
        "agent_id": str(agent_id),
        "scope": scope.model_dump(mode="json"),
        "connector_id": connector.id,
        "sender": config.sender,
        "recipients": scope.email.recipients,
        "template": TEMPLATE,
    }


def latest_grant(session, agent_id):
    return session.scalar(
        select(Approval)
        .where(
            Approval.action == ACTION,
            Approval.payload["agent_id"].as_string() == str(agent_id),
        )
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


def grant(session, agent, scope, *, confirmed):
    if confirmed is not True:
        raise MarketEmailPolicyError(
            "Explicitly allow automatic price-alert email before enabling this agent"
        )
    payload = scope_payload(session, agent.id, scope)
    revoke(session, agent.id)
    now = utcnow()
    row = Approval(
        action=ACTION,
        reason="Operator enabled deterministic price alerts to these reviewed recipients.",
        risk="high",
        payload={**payload, "scope_hash": _hash(payload)},
        resolution="granted",
        requested_at=now,
        resolved_at=now,
    )
    session.add(row)
    session.flush()
    return row


def authorization(session, agent, scope=None, *, expected_id=None):
    if agent is None or not agent.enabled or agent.tools != ["market_watch"]:
        raise MarketEmailPolicyError("The price agent is paused or its reviewed scope changed")
    saved = MarketScope.model_validate(agent.market)
    scope = scope or saved
    if saved != scope:
        raise MarketEmailPolicyError("The queued price policy no longer matches this agent")
    row = latest_grant(session, agent.id)
    payload = scope_payload(session, agent.id, scope)
    if (
        row is None
        or row.resolution != "granted"
        or expected_id is not None
        and row.id != expected_id
        or row.payload != {**payload, "scope_hash": _hash(payload)}
    ):
        raise MarketEmailPolicyError("Enable and explicitly approve this agent's current email scope")
    return row


def authorization_public(session, agent):
    row = latest_grant(session, agent.id) if session is not None else None
    if row is None:
        return None
    try:
        authorization(session, agent)
        valid = True
    except ValueError:
        valid = False
    return {
        "id": row.id,
        "scope": row.payload.get("scope"),
        "requested_at": row.requested_at.isoformat(),
        "resolution": row.resolution,
        "valid": valid,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "sender": row.payload.get("sender"),
        "recipients": row.payload.get("recipients", []),
        "template": row.payload.get("template"),
    }


def alert_message(alert, observation, baseline):
    return {
        "subject": f"AI Station: {observation.instrument} moved {alert.change_percent}%",
        "body": (
            "AI Station price alert\n\n"
            f"Instrument: {observation.instrument}\n"
            f"Previous price: {baseline.price}\nCurrent price: {observation.price}\n"
            f"Change: {alert.change_percent}%\n"
            f"Previous trade time: {baseline.source_at.isoformat()}\n"
            f"Current trade time: {observation.source_at.isoformat()}\n"
            f"Source: {observation.source_url}\n\n"
            "Compared with the previous valid observation within the approved maximum gap.\n"
            f"Alert ID: {alert.id}\n"
        ),
    }


def alert_source(session, run, alert_id):
    alert = session.get(MarketAlert, alert_id)
    observation = session.get(MarketObservation, alert.observation_id) if alert else None
    baseline = session.get(MarketObservation, alert.baseline_id) if alert else None
    comparison = session.get(Run, alert.run_id) if alert else None
    if (
        alert is None
        or observation is None
        or baseline is None
        or comparison is None
        or comparison.status != "succeeded"
        or comparison.executor_type != "agent_market"
        or comparison.parameters.get("tool") != "market.compare"
        or comparison.parent_run_id != run.parent_run_id
        or comparison.task_id != run.task_id
        or comparison.agent_id != run.agent_id
        or observation.agent_id != run.agent_id
        or baseline.agent_id != run.agent_id
        or comparison.parameters.get("definition") != run.parameters.get("definition")
    ):
        raise MarketEmailPolicyError("Email has no matching successful price comparison")
    from app.market_watch import policy_key

    scope = MarketScope.model_validate(comparison.parameters["definition"]["market"])
    matched = any(
        row.get("alert_id") == alert.id
        and row.get("observation_id") == observation.id
        and row.get("baseline_id") == baseline.id
        and row.get("change_percent") == alert.change_percent
        and row.get("status") == "alert"
        for row in comparison.metadata_json.get("market_result", {}).get("rows", [])
    )
    if (
        not matched
        or observation.policy_key != policy_key(scope)
        or baseline.policy_key != observation.policy_key
        or baseline.instrument != observation.instrument
        or observation.instrument not in scope.instruments
    ):
        raise MarketEmailPolicyError("Email has no recorded threshold crossing in its reviewed scope")
    return alert, observation, baseline


def queue_alert(session, notify_run, definition, alert_id):
    from app.task_control import stopped_task

    if stopped_task(session, notify_run.task):
        raise MarketEmailPolicyError("The price workflow was stopped before email publication")
    for permission in ("email_send", "network_external"):
        require(notify_run.effective_permissions, permission)
    parent = session.get(Run, notify_run.parent_run_id)
    if (
        parent is None
        or parent.executor_type != "agent_workflow"
        or parent.status != "succeeded"
        or parent.task_id != notify_run.task_id
        or parent.agent_id != notify_run.agent_id
        or parent.parameters.get("definition") != notify_run.parameters.get("definition")
        or not parent.parameters.get("market_email_approval_id")
    ):
        raise MarketEmailPolicyError("Missing authorized price workflow")
    consent = authorization(
        session,
        session.get(Agent, notify_run.agent_id),
        definition.market,
        expected_id=parent.parameters.get("market_email_approval_id"),
    )
    alert, observation, baseline = alert_source(session, notify_run, alert_id)
    delivery_id = str(uuid5(UUID(alert.id), TEMPLATE))
    existing = session.get(EmailDelivery, delivery_id)
    if existing:
        if existing.payload.get("market_alert", {}).get("alert_id") != alert.id:
            raise MarketEmailPolicyError("Alert receipt identity is occupied by another message")
        return existing
    if notify_run.status != "running" or not -30 <= (utcnow() - observation.source_at).total_seconds() <= 300:
        raise MarketEmailPolicyError("Price alert expired before SMTP publication")
    connector, config = target(session, definition.market)
    envelope = alert_message(alert, observation, baseline)
    payload = {
        "connector_id": connector.id,
        "sender": config.sender,
        "recipients": definition.market.email.recipients,
        **envelope,
        "connector_fingerprint": fingerprint(connector),
        "market_alert": {"alert_id": alert.id, "approval_id": consent.id, "template": TEMPLATE},
    }
    child = create_run(
        session,
        notify_run.task,
        run_type="agent",
        capability="email.send",
        executor_type="email_send",
        execution_target="container",
        parameters={
            "connector_id": connector.id,
            "connector_fingerprint": fingerprint(connector),
            "smtp": config.model_dump(),
            "delivery_id": delivery_id,
            "message": {k: payload[k] for k in ("sender", "recipients", "subject", "body")},
            "market_alert": payload["market_alert"],
            "tool": "email.send",
            "deadline_at": notify_run.parameters["deadline_at"],
        },
        permissions=["email_send", "network_external"],
        retry_class="inspect",
        triggered_by=notify_run.triggered_by,
        agent_id=notify_run.agent_id,
        parent_run_id=notify_run.id,
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
    depend_on(session, child, notify_run)
    report = session.scalar(
        select(Run).where(
            Run.parent_run_id == notify_run.parent_run_id,
            Run.parameters["tool"].as_string() == "market.report",
        )
    )
    if report is None:
        raise MarketEmailPolicyError("Missing price report stage")
    depend_on(session, report, child)
    append_event(
        session,
        child.id,
        "email.policy_authorized",
        {
            "approval_id": consent.id,
            "alert_id": alert.id,
            "delivery_id": receipt.id,
        },
    )
    return receipt


def validate_submission(session, run, receipt):
    """Recompute authority and the fixed message, rather than trusting queue metadata."""
    from app.task_control import stopped_task

    if stopped_task(session, run.task):
        raise MarketEmailPolicyError("The price workflow was stopped before SMTP submission")
    reference = run.parameters.get("market_alert")
    notify = session.get(Run, run.parent_run_id)
    if (
        not isinstance(reference, dict)
        or reference != receipt.payload.get("market_alert")
        or reference.get("template") != TEMPLATE
        or notify is None
        or notify.status != "succeeded"
        or notify.executor_type != "agent_market"
        or notify.parameters.get("tool") != "market.notify"
        or notify.task_id != run.task_id
        or notify.agent_id != run.agent_id
    ):
        raise MarketEmailPolicyError("Email is missing its successful alert-publication stage")
    scope = MarketScope.model_validate(notify.parameters["definition"]["market"])
    authorization(session, session.get(Agent, run.agent_id), scope, expected_id=reference.get("approval_id"))
    parent = session.get(Run, notify.parent_run_id)
    if (
        parent is None
        or parent.executor_type != "agent_workflow"
        or parent.status != "succeeded"
        or parent.parameters.get("market_email_approval_id") != reference.get("approval_id")
        or parent.parameters.get("definition") != notify.parameters.get("definition")
    ):
        raise MarketEmailPolicyError("Alert authorization does not match its frozen workflow")
    alert, observation, baseline = alert_source(session, notify, reference.get("alert_id"))
    connector, config = target(session, scope)
    if (
        receipt.id != str(uuid5(UUID(alert.id), TEMPLATE))
        or receipt.payload["connector_id"] != connector.id
        or receipt.payload["sender"] != config.sender
        or receipt.payload["recipients"] != scope.email.recipients
        or any(receipt.payload[k] != v for k, v in alert_message(alert, observation, baseline).items())
        or not -30 <= (utcnow() - observation.source_at).total_seconds() <= 300
        or utcnow() >= datetime.fromisoformat(run.parameters["deadline_at"])
    ):
        raise MarketEmailPolicyError(
            "Alert message, target or freshness no longer matches its approved scope"
        )
