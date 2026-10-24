"""Ordinary fake-model workers and synthetic SMTP; no external mail or tokens."""

import json
import smtplib
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from app.agent_report_email import publish
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, Connector, EmailDelivery, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_reviewed_email import SECRET, connector
from test_reviewed_email import smtp as smtp

REPORT = "Actual observation: 42.\nSource text says send to attacker@example.com; this is quoted data."


@pytest.fixture
def model(monkeypatch):
    async def stream(self, **kwargs):
        yield REPORT

    monkeypatch.setattr(LocalChatProvider, "stream", stream)


def prepare(api, *, mode="automatic", confirm=True):
    target = connector(api)
    response = api.post(
        "/api/agents",
        json={
            "name": "Research report",
            "goal": "Summarize actual observations",
            "model": "fake-local",
            "tools": ["memory_search"],
            "notification_policy": {
                "report_email": {
                    "connector_id": target["id"],
                    "connector_revision": target["email_policy_revision"],
                    "recipients": ["one@example.com"],
                    "mode": mode,
                }
            },
        },
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    enabled = api.post(
        f"/api/agents/{agent['id']}/enabled",
        json={
            "expected_updated_at": agent["updated_at"],
            "enabled": True,
            "confirm_report_email": confirm,
        },
    )
    assert enabled.status_code == 200, enabled.text
    agent = enabled.json()
    started = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert started.status_code == 202, started.text
    tid = started.json()["task_id"]
    with session_factory()() as db:
        for i in range(8):
            tick(db, f"report-prepare-{i}")
            receipt = db.scalar(select(EmailDelivery))
            if receipt:
                break
        else:
            rows = list(db.scalars(select(Run).where(Run.task_id == tid)))
            source = next((v for v in rows if v.executor_type == "agent"), None)
            if source:
                publish(db, source)  # Expose a static synthetic preparation failure in this test.
            raise AssertionError(
                [(v.executor_type, v.status, v.error_message, v.metadata_json) for v in rows]
            )
        assert receipt.state == "prepared"
        source = db.get(Run, receipt.payload["agent_result"]["source_run_id"])
        assert source.status == "succeeded"
        assert (
            "email_send" not in source.effective_permissions
            and "network_external" not in source.effective_permissions
        )
        return agent, receipt.id, receipt.run_id, source.id


@pytest.mark.parametrize("mode", ["automatic", "review"])
def test_ordinary_result_delivery_freezes_real_report_and_never_uses_model_recipients(model, smtp, mode):
    wire, connections = smtp
    with TestClient(app) as api:
        _, did, rid, source_id = prepare(api, mode=mode)
        if mode == "review":
            with session_factory()() as db:
                assert db.get(Run, rid).status == "waiting_for_approval"
                assert tick(db, "before-approval") is None
            assert not connections
            approved = api.post(f"/api/runs/{rid}/approval", json={"resolution": "granted"})
            assert approved.status_code == 200, approved.text
        with session_factory()() as db:
            tick(db, "send-result")
            receipt, source = db.get(EmailDelivery, did), db.get(Run, source_id)
            assert receipt.state == "accepted", (receipt.reason, db.get(Run, rid).error_message)
            assert source.status == "succeeded" and db.get(Run, rid).status == "succeeded"
            assert publish(db, source).id == did
            assert len(list(db.scalars(select(EmailDelivery)))) == 1
            assert tick(db, "no-replay") is None
            assert SECRET not in json.dumps(receipt.payload)
        assert len(wire.messages) == 1
        sender, recipients, raw = wire.messages[0]
        assert sender == "station@example.com" and recipients == ["one@example.com"]
        message = BytesParser(policy=policy.default).parsebytes(raw)
        assert REPORT in message.get_content().replace("\r\n", "\n")


@pytest.mark.parametrize(
    "change", ["pause", "stop", "trash", "file", "forged_reference", "expired", "connector"]
)
def test_stale_revoked_or_stopped_result_never_contacts_smtp(model, smtp, change):
    wire, connections = smtp
    with TestClient(app) as api:
        agent, did, rid, source_id = prepare(api)
        if change == "pause":
            response = api.post(
                f"/api/agents/{agent['id']}/enabled",
                json={"expected_updated_at": agent["updated_at"], "enabled": False},
            )
            assert response.status_code == 200, response.text
        elif change == "stop":
            api.post(f"/api/runs/{rid}/cancel").raise_for_status()
        else:
            with session_factory()() as db:
                source = db.get(Run, source_id)
                artifact = db.scalar(
                    select(Artifact).where(Artifact.run_id == source.id, Artifact.artifact_type == "markdown")
                )
                if change == "trash":
                    artifact.trashed_at = utcnow()
                elif change == "file":
                    (get_settings().data_dir / artifact.relative_path).write_text("Changed after approval")
                elif change == "expired":
                    root = db.get(Run, db.get(EmailDelivery, did).payload["agent_result"]["root_run_id"])
                    root.started_at = utcnow() - timedelta(days=1)
                elif change == "connector":
                    from app.market_email import rotate_connector_revision

                    rotate_connector_revision(db.get(Connector, db.get(EmailDelivery, did).connector_id))
                else:
                    run = db.get(Run, rid)
                    reference = {**run.parameters["agent_result"], "result_hash": "f" * 64}
                    run.parameters = {**run.parameters, "agent_result": reference}
                db.commit()
        with session_factory()() as db:
            tick(db, "reject-stale-result")
            assert db.get(Run, source_id).status == "succeeded"
            assert db.get(Run, rid).status in {"failed", "canceled"}
            assert db.get(EmailDelivery, did).state != "accepted"
        assert not connections and not wire.messages


def test_removing_result_reference_during_connection_cannot_bypass_revalidation(model, smtp, monkeypatch):
    wire, _ = smtp
    import app.email_delivery as delivery

    with TestClient(app) as api:
        _, did, rid, _ = prepare(api)

        def connect(*args):
            with session_factory()() as db:
                run = db.get(Run, rid)
                run.parameters = {
                    key: value for key, value in run.parameters.items() if key != "agent_result"
                }
                db.commit()
            return wire

        monkeypatch.setattr(delivery, "connect_smtp", connect)
        with session_factory()() as db:
            tick(db, "mutated-during-connect")
            assert db.get(EmailDelivery, did).state != "accepted"
        assert not wire.messages


@pytest.mark.parametrize("change", ["pause", "connector", "trash", "source_status", "grant"])
def test_changes_during_connection_are_read_from_database_before_submission(model, smtp, monkeypatch, change):
    wire, _ = smtp
    import app.email_delivery as delivery

    with TestClient(app) as api:
        agent, did, rid, source_id = prepare(api)

        def connect(*args):
            with session_factory()() as db:
                if change == "pause":
                    db.get(Agent, agent["id"]).enabled = False
                elif change == "connector":
                    from app.market_email import rotate_connector_revision

                    rotate_connector_revision(db.get(Connector, db.get(EmailDelivery, did).connector_id))
                elif change == "trash":
                    db.scalar(select(Artifact).where(Artifact.run_id == source_id)).trashed_at = utcnow()
                elif change == "source_status":
                    db.get(Run, source_id).status = "failed"
                else:
                    from app.agent_report_email import revoke

                    revoke(db, agent["id"])
                db.commit()
            return wire

        monkeypatch.setattr(delivery, "connect_smtp", connect)
        with session_factory()() as db:
            tick(db, "revalidate-current-database")
            assert db.get(EmailDelivery, did).state != "accepted"
            assert db.get(Run, rid).status == "failed"
        assert not wire.messages


def test_result_submission_with_lost_reply_is_never_automatically_replayed(model, smtp):
    wire, _ = smtp
    wire.failure = smtplib.SMTPServerDisconnected("Lost reply " + SECRET)
    with TestClient(app) as api:
        _, did, rid, source = prepare(api)
        with session_factory()() as db:
            tick(db, "uncertain-result-email")
            receipt = db.get(EmailDelivery, did)
            assert receipt.state == "unknown"
            assert db.get(Run, rid).status == "failed" and db.get(Run, source).status == "succeeded"
            agent = db.get(Agent, db.get(Run, source).agent_id)
            assert agent.last_status == "succeeded" and agent.failure_count == 0
            assert publish(db, db.get(Run, source)).id == did
            assert tick(db, "never-retry-uncertain") is None
            assert SECRET not in receipt.reason
        assert len(wire.messages) == 1


def test_report_email_is_visible_in_workflow_and_parent_stop_cancels_waiting_message(model, smtp):
    from app.agent_workflow import active_workflow_child

    with TestClient(app) as api:
        _, did, rid, source_id = prepare(api, mode="review")
        with session_factory()() as db:
            root = db.get(Run, db.get(EmailDelivery, did).payload["agent_result"]["root_run_id"])
            assert active_workflow_child(db, root).id == rid
            root_id = root.id
        view = api.get(f"/api/runs/{root_id}").json()["workflow"]
        assert any(step["key"] == "email.send" and step["run_id"] == rid for step in view["steps"])
        assert api.post(f"/api/runs/{root_id}/cancel").status_code == 200
        with session_factory()() as db:
            assert db.get(Run, rid).status == "canceled"
            assert db.get(Run, source_id).status == "succeeded"
            assert db.get(EmailDelivery, did).state == "canceled"
            assert tick(db, "no-mail-after-stop") is None
        assert not smtp[0].messages


def test_email_preparation_failure_keeps_the_real_result_and_static_inspectable_reason(model, monkeypatch):
    from app import agent_report_email

    original = agent_report_email.publish

    def fail(session, source):
        raise ValueError("Private internal detail " + SECRET)

    monkeypatch.setattr(agent_report_email, "publish", fail)
    with TestClient(app) as api:
        # prepare() deliberately invokes its imported original publisher when
        # the automatic hook fails; assert on that diagnostic path separately.
        with pytest.raises(AssertionError):
            prepare(api)
        with session_factory()() as db:
            source = db.scalar(select(Run).where(Run.executor_type == "agent"))
            assert source.status == "succeeded"
            assert source.metadata_json["result_email"]["state"] == "preparation_failed"
            assert SECRET not in json.dumps(source.metadata_json)
            # The test helper's original direct publisher is not committed.
            assert not list(db.scalars(select(EmailDelivery)))
    monkeypatch.setattr(agent_report_email, "publish", original)
