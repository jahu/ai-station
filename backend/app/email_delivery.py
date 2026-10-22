"""Reviewed TLS SMTP with a durable, never-blindly-retried delivery journal."""

from __future__ import annotations

import hashlib
import json
import smtplib
import ssl
import tempfile
from contextlib import suppress
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals import latest_approval, request_run_approval, run_public
from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.email_schema import EmailDraft, SMTPSettings
from app.events import append_event
from app.models import Connector, EmailDelivery, Run
from app.permissions import require
from app.providers import ProviderError
from app.runs import create_run, create_task, mark_failed, transition
from app.secrets import resolve_secret
from app.state import RunStatus

router = APIRouter(prefix="/api/email", tags=["email"])
DB = Annotated[Session, Depends(session_scope)]


def fingerprint(row):
    return hashlib.sha256(
        json.dumps(
            {"smtp": row.config_json.get("smtp"), "secret_ref": row.secret_ref}, sort_keys=True
        ).encode()
    ).hexdigest()


def message_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reviewed_connector(session, connector_id):
    row = session.get(Connector, str(connector_id))
    if row is None or row.kind != "email" or not row.enabled:
        raise HTTPException(409, "Choose an enabled email connector")
    try:
        config = SMTPSettings.model_validate(row.config_json.get("smtp"))
    except ValueError as exc:
        raise HTTPException(409, "Review the SMTP configuration before continuing") from exc
    if bool(config.username) != bool(row.secret_ref):
        raise HTTPException(409, "Review SMTP credentials before continuing")
    if row.secret_ref:
        resolve_secret(row.secret_ref)
    return row, config


def delivery_dict(row, session):
    run = session.get(Run, row.run_id)
    return {
        "id": row.id,
        "connector_id": row.connector_id,
        "payload": row.payload,
        "payload_hash": row.payload_hash,
        "message_id": row.message_id,
        "state": row.state,
        "accepted_recipients": row.accepted_recipients,
        "refused_recipients": row.refused_recipients,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "run": run_public(session, run),
    }


@router.get("/deliveries")
def deliveries(session: DB, connector_id: UUID | None = None, limit: int = Query(20, ge=1, le=100)):
    query = select(EmailDelivery).order_by(EmailDelivery.created_at.desc())
    if connector_id:
        query = query.where(EmailDelivery.connector_id == str(connector_id))
    return [delivery_dict(row, session) for row in session.scalars(query.limit(limit))]


@router.post("/connectors/{connector_id}/drafts", status_code=201)
def draft(connector_id: UUID, body: EmailDraft, session: DB):
    intent = {
        "connector_id": str(connector_id),
        "recipients": body.recipients,
        "subject": body.subject,
        "body": body.body,
    }
    existing = session.get(EmailDelivery, str(body.client_request_id))
    if existing:
        if any(existing.payload.get(key) != value for key, value in intent.items()):
            raise HTTPException(409, "This request ID already belongs to a different message")
        return delivery_dict(existing, session)
    try:
        connector, config = reviewed_connector(session, connector_id)
    except ProviderError as exc:
        raise HTTPException(409, "The SMTP credential is unavailable") from exc
    if body.expected_updated_at != connector.updated_at:
        raise HTTPException(409, "Connector changed; refresh and review before preparing this message")
    if not set(body.recipients).issubset(config.allowed_recipients):
        raise HTTPException(422, "Every recipient must be in the saved connector allowlist")
    payload = {**intent, "sender": config.sender, "connector_fingerprint": fingerprint(connector)}
    digest = message_hash(payload)
    task = create_task(
        session,
        title="Review email: " + body.subject,
        prompt="Review the frozen message before approving SMTP submission.",
        capability="email.send",
    )
    run = create_run(
        session,
        task,
        run_type="connector",
        capability="email.send",
        executor_type="email_send",
        execution_target="container",
        parameters={
            "connector_id": connector.id,
            "connector_fingerprint": fingerprint(connector),
            "smtp": config.model_dump(),
            "delivery_id": str(body.client_request_id),
            "message": {key: payload[key] for key in ("sender", "recipients", "subject", "body")},
        },
        permissions=["email_send", "network_external"],
        retry_class="inspect",
    )
    row = EmailDelivery(
        id=str(body.client_request_id),
        connector_id=connector.id,
        run_id=run.id,
        payload=payload,
        payload_hash=digest,
        message_id=f"<{body.client_request_id}@ai-station.local>",
        state="prepared",
    )
    session.add(row)
    session.flush()
    request_run_approval(
        session,
        run,
        action="email.send",
        reason="Review the sender, recipients and complete message before sending.",
        payload={
            "delivery_id": row.id,
            "payload_hash": digest,
            "recipients": body.recipients,
            "sender": config.sender,
            "subject": body.subject,
        },
    )
    session.commit()
    return delivery_dict(row, session)


def enqueue_check(session, connector):
    from app.connectors import active_check

    try:
        connector, config = reviewed_connector(session, connector.id)
    except ProviderError as exc:
        raise HTTPException(409, "The SMTP credential is unavailable") from exc
    if active_check(session, connector.id):
        raise HTTPException(409, "Finish or cancel the connector operation before checking SMTP")
    task = create_task(
        session,
        title="Check " + connector.name,
        prompt="Connect, verify TLS and authenticate SMTP. No message is sent.",
        capability="email.check",
    )
    run = create_run(
        session,
        task,
        run_type="connector",
        capability="email.check",
        executor_type="email_check",
        execution_target="container",
        parameters={
            "connector_id": connector.id,
            "connector_fingerprint": fingerprint(connector),
            "smtp": config.model_dump(),
        },
        permissions=["network_external"],
        retry_class="inspect",
    )
    connector.status = "checking"
    connector.last_run_id = run.id
    connector.updated_at = utcnow()
    session.commit()
    return run_public(session, run)


def _ehlo(client):
    code, _ = client.ehlo()
    if code != 250:
        raise smtplib.SMTPHeloError(code, b"SMTP greeting was refused")


def connect_smtp(config, password):
    context = ssl.create_default_context()
    client = None
    try:
        if config.transport == "ssl":
            client = smtplib.SMTP_SSL(
                config.host, 465, timeout=10, context=context, local_hostname="ai-station.local"
            )
            _ehlo(client)
        else:
            client = smtplib.SMTP(config.host, 587, timeout=10, local_hostname="ai-station.local")
            _ehlo(client)
            client.starttls(context=context)
            _ehlo(client)
        if config.username:
            client.login(config.username, password)
        return client
    except Exception:
        if client:
            with suppress(Exception):
                client.close()
        raise


def smtp_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP authentication failed. Review the saved credentials."
    if isinstance(exc, ssl.SSLError):
        return "SMTP TLS verification failed. Review the server hostname and certificate."
    return "SMTP operation failed. Review the connector and inspect the delivery receipt."


def sync_delivery_from_run(session, run, status):
    if run.executor_type != "email_send" or status not in {"canceled", "failed", "interrupted"}:
        return
    row = session.scalar(select(EmailDelivery).where(EmailDelivery.run_id == run.id))
    if row is None:
        return
    if row.state == "prepared":
        row.state = "canceled" if status == "canceled" else "failed_before_send"
        row.reason = row.reason or "Submission was not started."
    elif row.state == "sending":
        row.state = "unknown"
        row.reason = "SMTP acceptance could not be confirmed. Inspect before preparing another message."
    row.updated_at = utcnow()


def canceled(session, run):
    session.refresh(run)
    stopped = run.status == "cancel_requested"
    session.commit()
    if stopped:
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        session.commit()
    return stopped or run.status == "canceled"


def validated_snapshot(session, run):
    connector, config = reviewed_connector(session, run.parameters.get("connector_id"))
    if fingerprint(connector) != run.parameters.get(
        "connector_fingerprint"
    ) or config.model_dump() != run.parameters.get("smtp"):
        raise ValueError("The reviewed SMTP configuration changed; prepare a new request")
    password = resolve_secret(connector.secret_ref) if connector.secret_ref else ""
    session.commit()
    return config, password


class EmailCheckExecutor:
    name = "email_check"

    def execute(self, session, run):
        if canceled(session, run):
            return "done"
        client = None
        try:
            require(run.effective_permissions, "network_external")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            config, password = validated_snapshot(session, run)
            client = connect_smtp(config, password)
            if canceled(session, run):
                return "done"
            code, _ = client.noop()
            if code != 250:
                raise ValueError("SMTP did not confirm connection health")
            if canceled(session, run):
                return "done"
            result = {
                "host": config.host,
                "transport": config.transport,
                "tls_verified": True,
                "authenticated": bool(config.username),
                "message_sent": False,
                "checked_at": utcnow().isoformat(),
            }
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
                json.dump(result, handle)
                handle.flush()
                register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="smtp-health.json",
                    run_id=run.id,
                )
            run.metadata_json = {**run.metadata_json, "smtp_health": result}
            run.summary = (
                "SMTP connection and TLS verified; "
                + ("authentication verified. " if config.username else "no login configured. ")
                + "No message sent."
            )
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except Exception as exc:
            session.rollback()
            if not canceled(session, run):
                mark_failed(session, run, "SMTPCheckFailed", smtp_error(exc))
        finally:
            if client:
                with suppress(Exception):
                    client.close()
        return "done"


class EmailSendExecutor:
    name = "email_send"

    def execute(self, session, run):
        if canceled(session, run):
            return "done"
        client = None
        row = None
        submission_started = False
        try:
            require(run.effective_permissions, "email_send")
            require(run.effective_permissions, "network_external")
            row = session.scalar(select(EmailDelivery).where(EmailDelivery.run_id == run.id))
            approval = latest_approval(session, run.id)
            if row is None or row.id != run.parameters.get("delivery_id") or row.state != "prepared":
                raise ValueError("A new reviewed message is required; this receipt cannot be replayed")
            if (
                run.parameters.get("message")
                != {key: row.payload[key] for key in ("sender", "recipients", "subject", "body")}
                or message_hash(row.payload) != row.payload_hash
                or approval is None
                or approval.resolution != "granted"
                or approval.action != "email.send"
                or approval.payload.get("payload_hash") != row.payload_hash
            ):
                raise ValueError("The frozen message does not match its explicit approval")
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            session.commit()
            config, password = validated_snapshot(session, run)
            if (
                row.payload["sender"] != config.sender
                or not set(row.payload["recipients"]).issubset(config.allowed_recipients)
                or row.payload["connector_fingerprint"] != run.parameters["connector_fingerprint"]
            ):
                raise ValueError("The message exceeds its reviewed sender or recipient scope")
            session.commit()
            message = EmailMessage(policy=SMTP)
            message["From"] = config.sender
            message["To"] = ", ".join(row.payload["recipients"])
            message["Subject"] = row.payload["subject"]
            message["Message-ID"] = row.message_id
            message["Date"] = format_datetime(row.created_at)
            message.set_content(row.payload["body"], cte="quoted-printable")
            client = connect_smtp(config, password)
            if canceled(session, run):
                return "done"
            row.state = "sending"
            row.updated_at = utcnow()
            append_event(
                session,
                run.id,
                "email.submission_started",
                {
                    "delivery_id": row.id,
                    "message_id": row.message_id,
                    "recipient_count": len(row.payload["recipients"]),
                },
            )
            session.commit()
            submission_started = True
            refused = client.sendmail(config.sender, list(row.payload["recipients"]), message.as_bytes())
            if not isinstance(refused, dict) or not set(refused).issubset(row.payload["recipients"]):
                raise ValueError("SMTP returned an unrecognized recipient outcome")
            session.refresh(run)
            row.accepted_recipients = [value for value in row.payload["recipients"] if value not in refused]
            row.refused_recipients = list(refused)
            if not row.accepted_recipients:
                raise ValueError("SMTP did not confirm any accepted recipients")
            row.state = "accepted_partial" if refused else "accepted"
            row.updated_at = utcnow()
            late_stop = run.status == "cancel_requested"
            row.reason = (
                "The server accepted the message before Stop could complete."
                if late_stop
                else "Accepted by the SMTP server; inbox delivery is not confirmed."
            )
            run.metadata_json = {
                **run.metadata_json,
                "email_delivery_id": row.id,
                "smtp_state": row.state,
                "accepted_count": len(row.accepted_recipients),
                "refused_count": len(refused),
            }
            append_event(session, run.id, "email.accepted", run.metadata_json)
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
                json.dump(
                    {
                        "delivery_id": row.id,
                        "message_id": row.message_id,
                        "state": row.state,
                        "accepted_recipients": row.accepted_recipients,
                        "refused_recipients": row.refused_recipients,
                        "reason": row.reason,
                    },
                    handle,
                )
                handle.flush()
                register_file(
                    session,
                    source=Path(handle.name),
                    artifact_type="json",
                    mime_type="application/json",
                    original_filename="smtp-receipt.json",
                    run_id=run.id,
                )
            if late_stop or refused:
                mark_failed(
                    session,
                    run,
                    "EmailAcceptedAfterStop" if late_stop else "EmailPartiallyAccepted",
                    row.reason
                    if late_stop
                    else "Some recipients were refused. Accepted recipients must not be retried.",
                )
            else:
                run.summary = "Message accepted by the SMTP server."
                transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            session.commit()
        except Exception as exc:
            session.rollback()
            if row is not None:
                session.refresh(row)
                if submission_started:
                    definitive = isinstance(
                        exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)
                    )
                    row.state = "failed_before_acceptance" if definitive else "unknown"
                    row.reason = (
                        "SMTP explicitly refused the message."
                        if definitive
                        else "SMTP acceptance could not be confirmed. Inspect before preparing another message."
                    )
                elif row.state == "prepared":
                    row.state = "failed_before_send"
                    row.reason = smtp_error(exc)
                row.updated_at = utcnow()
            session.refresh(run)
            if run.status == "cancel_requested" and not submission_started:
                if row is not None:
                    row.state, row.reason = "canceled", "Stopped before SMTP submission."
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            else:
                mark_failed(
                    session,
                    run,
                    "SMTPOutcomeUnknown"
                    if submission_started and row is not None and row.state == "unknown"
                    else "SMTPDeliveryFailed",
                    row.reason if row is not None else "The reviewed email request is invalid.",
                )
            session.commit()
        finally:
            if client:
                with suppress(Exception):
                    client.close()
        return "done"
