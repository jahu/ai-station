"""SMTP is exercised with synthetic scope/credentials, never real external mail."""

import smtplib
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Connector, EmailDelivery, Run
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select

SECRET = "test-password-NEVER-IN-DATABASE"


def connector(api, **patch):
    body = {
        "key": "test-mail",
        "name": "Test mail",
        "kind": "email",
        "smtp": {
            "host": "smtp.example.com",
            "sender": "station@example.com",
            "allowed_recipients": ["one@example.com", "two@example.com"],
            "username": "station",
        },
        "secret": SECRET,
    }
    body.update(patch)
    response = api.post("/api/connectors", json=body)
    assert response.status_code == 201, response.text
    assert SECRET not in response.text
    return response.json()


def draft(api, row, **patch):
    body = {
        "client_request_id": str(uuid4()),
        "expected_updated_at": row["updated_at"],
        "recipients": ["one@example.com"],
        "subject": "A reviewed message",
        "body": "Public test content, no private data.",
    }
    body.update(patch)
    response = api.post(f"/api/email/connectors/{row['id']}/drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def approve(api, message):
    response = api.post(f"/api/runs/{message['run']['id']}/approval", json={"resolution": "granted"})
    assert response.status_code == 200, response.text


def step():
    with session_factory()() as session:
        tick(session, "email-test-worker")


def delivery(api, cid):
    return api.get("/api/email/deliveries?connector_id=" + cid).json()[0]


class Transport:
    def __init__(self):
        self.messages = []
        self.closed = False
        self.failure = None
        self.refused = {}
        self.on_send = None

    def noop(self):
        return 250, b"OK"

    def sendmail(self, sender, recipients, message):
        self.messages.append((sender, recipients, message))
        if self.on_send:
            self.on_send()
        if self.failure:
            raise self.failure
        return self.refused

    def close(self):
        self.closed = True


@pytest.fixture
def smtp(monkeypatch):
    transport = Transport()
    calls = []

    def connect(config, password):
        assert password == SECRET
        calls.append(config.model_dump())
        return transport

    monkeypatch.setattr("app.email_delivery.connect_smtp", connect)
    return transport, calls


def test_preview_is_not_a_send_and_approval_sends_exact_frozen_message_once(smtp):
    transport, calls = smtp
    with TestClient(app) as api:
        row = connector(api)
        message, body = draft(api, row)
        assert message["state"] == "prepared" and message["run"]["status"] == "waiting_for_approval"
        assert message["run"]["effective_permissions"] == ["email_send", "network_external"]
        step()
        assert not calls and not transport.messages
        replay = api.post(f"/api/email/connectors/{row['id']}/drafts", json=body)
        assert replay.json()["id"] == message["id"]
        assert len(api.get("/api/email/deliveries").json()) == 1
        approve(api, message)
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "accepted" and result["run"]["status"] == "succeeded"
        assert result["accepted_recipients"] == ["one@example.com"] and not result["refused_recipients"]
        assert transport.closed and len(transport.messages) == 1
        raw = transport.messages[0][2]
        assert b"To: one@example.com" in raw and body["body"].encode() in raw
        assert result["message_id"].encode() in raw
        assert api.post(f"/api/email/connectors/{row['id']}/drafts", json=body).json()["state"] == "accepted"
        step()
        assert len(transport.messages) == 1
        assert (
            api.post(f"/api/runs/{message['run']['id']}/approval", json={"resolution": "granted"}).status_code
            == 409
        )
        assert SECRET not in api.get("/api/runs/" + message["run"]["id"]).text
        assert SECRET not in api.get("/api/email/deliveries").text


def test_unknown_smtp_outcome_is_never_requeued(smtp):
    transport, _ = smtp
    transport.failure = smtplib.SMTPServerDisconnected("lost reply " + SECRET)
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "unknown" and result["run"]["status"] == "failed"
        assert result["run"]["retry_class"] == "inspect" and SECRET not in str(result)
        step()
        assert len(transport.messages) == 1


def test_partial_acceptance_preserves_accepted_recipients_without_whole_message_retry(smtp):
    transport, _ = smtp
    transport.refused = {"two@example.com": (550, b"refused " + SECRET.encode())}
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row, recipients=["one@example.com", "two@example.com"])
        approve(api, message)
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "accepted_partial" and result["run"]["status"] == "failed"
        assert result["accepted_recipients"] == ["one@example.com"] and result["refused_recipients"] == [
            "two@example.com"
        ]
        assert SECRET not in str(result)


def test_late_stop_does_not_lie_about_accepted_mail(smtp):
    transport, _ = smtp
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)

        def stop():
            with session_factory()() as session:
                request_cancel(session, session.get(Run, message["run"]["id"]))
                session.commit()

        transport.on_send = stop
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "accepted" and result["run"]["error_type"] == "EmailAcceptedAfterStop"
        assert "before Stop" in result["reason"] and len(transport.messages) == 1


def test_deny_never_connects_and_records_cancellation(smtp):
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        assert (
            api.post(f"/api/runs/{message['run']['id']}/approval", json={"resolution": "denied"}).status_code
            == 200
        )
        step()
        assert not smtp[1]
        assert delivery(api, row["id"])["state"] == "canceled"


@pytest.mark.parametrize(
    "change",
    [
        {"recipients": ["outsider@example.com"]},
        {"recipients": ["one@example.com", "one@example.com"]},
        {"subject": "hello\r\nBcc: outsider@example.com"},
        {"recipients": ["one@example.com\r\nDATA"]},
        {"body": "bad\x00value"},
    ],
)
def test_invalid_envelopes_or_out_of_scope_recipients_are_rejected(change):
    with TestClient(app) as api:
        row = connector(api)
        body = {
            "client_request_id": str(uuid4()),
            "expected_updated_at": row["updated_at"],
            "recipients": ["one@example.com"],
            "subject": "Test",
            "body": "Test",
            **change,
        }
        assert api.post(f"/api/email/connectors/{row['id']}/drafts", json=body).status_code == 422
        assert not api.get("/api/email/deliveries").json()


def test_changed_payload_or_permission_cannot_send(smtp):
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
        with session_factory()() as session:
            receipt = session.get(EmailDelivery, message["id"])
            receipt.payload = {**receipt.payload, "body": "Changed after review"}
            session.commit()
        step()
        assert not smtp[1] and delivery(api, row["id"])["run"]["status"] == "failed"


def test_connector_cannot_be_changed_or_removed_while_a_message_needs_review():
    with TestClient(app) as api:
        row = connector(api)
        draft(api, row)
        assert api.patch("/api/connectors/" + row["id"], json={"name": "Mutated"}).status_code == 409
        assert api.delete("/api/connectors/" + row["id"]).status_code == 409


def test_health_checks_tls_authentication_without_submitting_a_message(smtp):
    with TestClient(app) as api:
        row = connector(api)
        check = api.post("/api/connectors/" + row["id"] + "/check")
        assert check.status_code == 202, check.text
        step()
        assert smtp[1] and not smtp[0].messages
        status = api.get("/api/connectors/" + row["id"]).json()
        assert status["health"] == "healthy" and status["status"] == "ready"


def test_crash_after_submission_started_requires_inspection_and_does_not_resend(session):
    from app.recovery import recover_stale
    from app.runs import transition
    from app.state import RunStatus

    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
    run = session.get(Run, message["run"]["id"])
    transition(session, run, RunStatus.CLAIMED, event_type="run.claimed")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    transition(session, run, RunStatus.RUNNING, event_type="executor.started")
    receipt = session.get(EmailDelivery, message["id"])
    receipt.state = "sending"
    run.lease_expires_at = utcnow() - timedelta(seconds=10)
    session.commit()

    class Runner:
        def inspect_process(self, run_id):
            return {"alive": False, "known": False}

    assert run.id in recover_stale(session, Runner())
    session.commit()
    assert receipt.state == "unknown" and run.status == "interrupted" and run.retry_class == "inspect"


def test_unavailable_credentials_fail_as_validation_not_internal_error(monkeypatch):
    with TestClient(app) as api:
        row = connector(api, secret=None, secret_ref="env:ABSENT_SMTP_TEST_KEY")
        assert api.post("/api/connectors/" + row["id"] + "/check").status_code == 409
        body = {
            "client_request_id": str(uuid4()),
            "expected_updated_at": row["updated_at"],
            "recipients": ["one@example.com"],
            "subject": "Test",
            "body": "No send",
        }
        assert api.post(f"/api/email/connectors/{row['id']}/drafts", json=body).status_code == 409


def test_stop_before_data_and_before_connection_never_submits(smtp, monkeypatch):
    transport, calls = smtp
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)

        def connect(config, password):
            with session_factory()() as session:
                request_cancel(session, session.get(Run, message["run"]["id"]))
                session.commit()
            calls.append(True)
            return transport

        monkeypatch.setattr("app.email_delivery.connect_smtp", connect)
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "canceled" and not transport.messages and transport.closed


def test_revoked_permission_does_not_connect(smtp):
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
        with session_factory()() as session:
            run = session.get(Run, message["run"]["id"])
            run.effective_permissions = []
            session.commit()
        step()
        assert not smtp[1]
        assert delivery(api, row["id"])["state"] == "failed_before_send"


def test_request_id_cannot_retarget_or_edit_an_existing_reviewed_message():
    with TestClient(app) as api:
        row = connector(api)
        message, body = draft(api, row)
        response = api.post(
            f"/api/email/connectors/{row['id']}/drafts", json={**body, "recipients": ["two@example.com"]}
        )
        assert response.status_code == 409
        assert delivery(api, row["id"])["payload"]["recipients"] == ["one@example.com"]


def test_tls_is_mandatory_for_both_transports(monkeypatch):
    from app.email_delivery import connect_smtp
    from app.email_schema import SMTPSettings

    events = []

    class Client(Transport):
        def ehlo(self):
            events.append("ehlo")
            return 250, b"fixture"

        def starttls(self, *, context):
            assert context.check_hostname and context.verify_mode == 2
            events.append("tls")

        def login(self, user, password):
            events.append("login")

    def constructor(host, port, **kwargs):
        assert host == "smtp.example.com" and port == 587
        return Client()

    monkeypatch.setattr("app.email_delivery.smtplib.SMTP", constructor)
    connect_smtp(
        SMTPSettings(
            host="smtp.example.com",
            transport="starttls",
            username="test",
            sender="one@example.com",
            allowed_recipients=["two@example.com"],
        ),
        "fixture",
    )
    assert events == ["ehlo", "tls", "ehlo", "login"]


def test_delivery_history_retains_public_server_snapshot_after_connector_removal(smtp):
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
        step()
        assert api.delete("/api/connectors/" + row["id"]).status_code == 204
        receipt = api.get("/api/email/deliveries").json()[0]
        assert receipt["connector_id"] is None
        assert receipt["run"]["parameters"]["smtp"]["host"] == "smtp.example.com"
        assert receipt["run"]["parameters"]["smtp"]["transport"] == "ssl"
        assert receipt["payload"]["recipients"] == ["one@example.com"]
        assert receipt["run"]["parameters"]["message"]["body"] == "Public test content, no private data."


def test_email_settings_reject_a_stale_version_and_do_not_change_the_saved_account():
    with TestClient(app) as api:
        row = connector(api)
        edited = api.patch(
            "/api/connectors/" + row["id"], json={"name": "Renamed", "expected_updated_at": row["updated_at"]}
        )
        assert edited.status_code == 200, edited.text
        stale = api.patch(
            "/api/connectors/" + row["id"],
            json={"name": "Stale edit", "expected_updated_at": row["updated_at"]},
        )
        assert stale.status_code == 409
        assert api.get("/api/connectors/" + row["id"]).json()["name"] == "Renamed"


def test_email_migration_preserves_existing_connectors_without_sending(session, legacy_schema):
    from alembic import command
    from app.db import alembic_config

    row = Connector(
        name="Existing HTTP", key="existing-http", kind="http", config_json={"url": "https://example.com"}
    )
    session.add(row)
    session.commit()
    cid = row.id
    legacy_schema("0029")
    command.upgrade(alembic_config(), "head")
    session.expire_all()
    assert session.get(Connector, cid).config_json == {"url": "https://example.com"}
    assert not list(session.scalars(select(EmailDelivery)))


@pytest.mark.parametrize(
    "smtp",
    [
        {"host": "http://smtp.example.com"},
        {"host": "smtp.example.com:25"},
        {"transport": "plain"},
        {"port": 25},
        {"sender": "one@example.com\r\nBcc: other@example.com"},
        {"allowed_recipients": ["one@-bad.example"]},
    ],
)
def test_invalid_or_unencrypted_smtp_configuration_is_rejected(smtp):
    with TestClient(app) as api:
        response = api.post(
            "/api/connectors",
            json={
                "key": "bad-smtp",
                "name": "Bad SMTP",
                "kind": "email",
                "smtp": {
                    "host": "smtp.example.com",
                    "sender": "station@example.com",
                    "allowed_recipients": ["one@example.com"],
                    **smtp,
                },
            },
        )
        assert response.status_code == 422, response.text


def test_smtp_authentication_errors_never_expose_the_saved_credential(monkeypatch):
    def rejected(config, password):
        raise smtplib.SMTPAuthenticationError(535, SECRET.encode())

    monkeypatch.setattr("app.email_delivery.connect_smtp", rejected)
    with TestClient(app) as api:
        row = connector(api)
        message, _ = draft(api, row)
        approve(api, message)
        step()
        result = delivery(api, row["id"])
        assert result["state"] == "failed_before_send" and "authentication" in result["reason"]
        assert (
            SECRET not in str(result)
            and SECRET not in api.get("/api/runs/" + message["run"]["id"] + "/events").text
        )


def test_replacing_smtp_credentials_invalidates_previous_health(smtp):
    with TestClient(app) as api:
        row = connector(api)
        assert api.post("/api/connectors/" + row["id"] + "/check").status_code == 202
        step()
        checked = api.get("/api/connectors/" + row["id"]).json()
        assert checked["health"] == "healthy"
        changed = api.patch(
            "/api/connectors/" + row["id"],
            json={"expected_updated_at": checked["updated_at"], "secret": "new-synthetic-password"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["health"] == "unknown" and changed.json()["last_run_id"] is None


@pytest.mark.parametrize("password", [SECRET, SECRET * 200])
def test_invalid_smtp_form_never_echoes_a_submitted_password(password):
    with TestClient(app) as api:
        response = api.post(
            "/api/connectors",
            json={
                "key": "invalid-mail",
                "name": "Invalid mail",
                "kind": "email",
                "secret": password,
                "smtp": {
                    "host": "smtp.example.com",
                    "sender": "station@example.com",
                    "allowed_recipients": ["one@example.com"],
                },
            },
        )
        assert response.status_code == 422
        assert SECRET not in response.text
        assert response.json()["detail"][0]["msg"]
        assert all("input" not in item and "ctx" not in item for item in response.json()["detail"])
