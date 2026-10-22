"""Synthetic quote → reviewed policy → durable SMTP workflow; never external mail."""

from datetime import timedelta

import pytest
from app.api import app
from app.engine import tick
from app.models import Agent, Approval, EmailDelivery, MarketObservation, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_market_watch import complete, page
from test_reviewed_email import Transport


@pytest.fixture
def transport(monkeypatch):
    wire = Transport()
    monkeypatch.setattr("app.email_delivery.connect_smtp", lambda *_: wire)
    return wire


def settings(api):
    response = api.post(
        "/api/connectors",
        json={
            "key": "price-mail",
            "name": "Price mail",
            "kind": "email",
            "smtp": {
                "host": "smtp.example.com",
                "sender": "station@example.com",
                "allowed_recipients": ["recipient@example.com"],
            },
        },
    )
    assert response.status_code == 201, response.text
    connector = response.json()
    response = api.post(
        "/api/agents",
        json={
            "name": "Bitcoin email watch",
            "goal": "Observe BTC price",
            "tools": ["market_watch"],
            "market": {
                "threshold_percent": "5",
                "email": {
                    "connector_id": connector["id"],
                    "connector_revision": connector["email_policy_revision"],
                    "recipients": ["recipient@example.com"],
                },
            },
            "trigger": "interval",
            "interval_seconds": 60,
        },
    )
    assert response.status_code == 201, response.text
    return connector, response.json()


def enabled(api, agent, *, confirm=True):
    return api.post(
        "/api/agents/" + agent["id"] + "/enabled",
        json={
            "expected_updated_at": agent["updated_at"],
            "enabled": True,
            "confirm_market_email": confirm,
        },
    )


def prepare(session, api):
    connector, agent = settings(api)
    response = enabled(api, agent)
    assert response.status_code == 200, response.text
    session.expire_all()
    saved = session.get(Agent, agent["id"])
    session.commit()
    return connector, saved


def test_email_scope_requires_distinct_operator_consent_and_duplicate_does_not_inherit(session):
    with TestClient(app) as api:
        _, agent = settings(api)
        assert enabled(api, agent, confirm=False).status_code == 409
        assert not list(session.scalars(select(Approval)))
        session.commit()
        response = enabled(api, agent)
        assert response.status_code == 200, response.text
        current = response.json()
        consent = current["market_email_authorization"]
        assert consent["valid"] and consent["recipients"] == ["recipient@example.com"]
        assert consent["sender"] == "station@example.com"
        assert consent["scope"]["threshold_percent"] == "5" and consent["requested_at"]
        copy = api.post(
            "/api/agents/" + agent["id"] + "/duplicate",
            json={
                "expected_updated_at": current["updated_at"],
            },
        ).json()
        assert not copy["enabled"] and copy["market_email_authorization"] is None
        assert enabled(api, copy, confirm=False).status_code == 409


def test_real_worker_price_threshold_publishes_one_frozen_message_and_receipt(
    session, monkeypatch, transport
):
    from app.db import utcnow

    with TestClient(app) as api:
        _, agent = prepare(session, api)
        now = utcnow()
        first = complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=20)))
        assert all(run.status == "succeeded" for run in first), [(r.status, r.error_message) for r in first]
        assert not transport.messages and not list(session.scalars(select(EmailDelivery)))
        second = complete(session, agent, monkeypatch, page("106", 101, now - timedelta(seconds=10)))
        assert all(run.status == "succeeded" for run in second), [(r.status, r.error_message) for r in second]
        receipt = session.scalar(select(EmailDelivery))
        assert receipt.state == "accepted" and len(transport.messages) == 1
        assert receipt.payload["recipients"] == ["recipient@example.com"]
        assert "6.00000000%" in receipt.payload["body"]
        assert "http" in receipt.payload["body"] and "106" in receipt.payload["body"]
        mail_run = session.get(Run, receipt.run_id)
        assert mail_run.task_id == second[-1].task_id and mail_run.agent_id == agent.id
        assert mail_run.effective_permissions == ["email_send", "network_external"]
        assert second[-1].metadata_json["market_result"]["email_receipts"][0]["state"] == "accepted"
        complete(session, agent, monkeypatch, page("106", 101, now - timedelta(seconds=10)))
        assert len(transport.messages) == 1
        agent_id = agent.id
        session.commit()
        own = api.get("/api/email/deliveries?agent_id=" + agent_id)
        assert own.status_code == 200 and len(own.json()) == 1
        from uuid import uuid4

        assert api.get("/api/email/deliveries?agent_id=" + str(uuid4())).json() == []


def test_health_check_preserves_consent_but_settings_rotation_requires_review(session, transport):
    with TestClient(app) as api:
        connector, agent = prepare(session, api)
        original = connector["email_policy_revision"]
        assert api.post("/api/connectors/" + connector["id"] + "/check").status_code == 202
        tick(session, "health-worker")
        session.commit()
        updated = api.get("/api/connectors/" + connector["id"]).json()
        assert updated["email_policy_revision"] == original and not transport.messages
        assert api.get("/api/agents/" + agent.id).json()["market_email_authorization"]["valid"]
        changed = api.patch(
            "/api/connectors/" + connector["id"],
            json={
                "expected_updated_at": updated["updated_at"],
                "smtp": updated["smtp"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["email_policy_revision"] != original
        row = api.get("/api/agents/" + agent.id).json()
        assert not row["market_email_authorization"]["valid"]
        assert (
            api.post(
                "/api/agents/" + agent.id + "/run", json={"expected_updated_at": row["updated_at"]}
            ).status_code
            == 409
        )
        assert not transport.messages


def pending_alert(session, api, monkeypatch):
    from app.db import utcnow
    from app.schedule import launch_agent

    _, agent = prepare(session, api)
    now = utcnow()
    complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=20)))

    async def fetch(url, **kwargs):
        return page("106", 101, now - timedelta(seconds=10))

    monkeypatch.setattr("app.http_fetch.fetch_public", fetch)
    parent_id = launch_agent(session, agent, triggered_by="user")
    session.commit()
    for _ in range(4):
        assert tick(session, "publish-worker")
    receipt = session.scalar(select(EmailDelivery))
    assert receipt and receipt.state == "prepared"
    rid, aid = receipt.run_id, agent.id
    session.commit()
    return rid, aid, parent_id


@pytest.mark.parametrize("change", ["pause", "re_enable", "permission", "wrong_grant", "stale", "stop"])
def test_revocation_or_invalid_scope_prevents_pending_smtp(session, monkeypatch, transport, change):
    from app.db import utcnow
    from app.runs import request_cancel

    with TestClient(app) as api:
        rid, aid, _ = pending_alert(session, api, monkeypatch)
        if change in {"pause", "re_enable"}:
            agent = api.get("/api/agents/" + aid).json()
            response = api.post(
                "/api/agents/" + aid + "/enabled",
                json={
                    "expected_updated_at": agent["updated_at"],
                    "enabled": False,
                },
            )
            assert response.status_code == 200, response.text
            if change == "re_enable":
                assert enabled(api, response.json()).status_code == 200
        else:
            run = session.get(Run, rid)
            if change == "permission":
                run.effective_permissions = []
            elif change == "wrong_grant":
                run.parameters = {
                    **run.parameters,
                    "market_alert": {
                        **run.parameters["market_alert"],
                        "approval_id": "wrong-grant",
                    },
                }
            elif change == "stale":
                future = utcnow() + timedelta(minutes=6)
                monkeypatch.setattr("app.market_email.utcnow", lambda: future)
            else:
                request_cancel(session, run)
            session.commit()
        for _ in range(6):
            if not tick(session, "submit-worker"):
                break
        session.expire_all()
        receipt = session.scalar(select(EmailDelivery))
        assert not transport.messages
        assert receipt.state in {"failed_before_send", "canceled"}
        assert session.get(Run, rid).status in {"failed", "canceled"}


def test_unknown_submission_is_not_repeated_by_another_price_check(session, monkeypatch, transport):
    import smtplib

    with TestClient(app) as api:
        rid, aid, _ = pending_alert(session, api, monkeypatch)
        transport.failure = smtplib.SMTPServerDisconnected("synthetic lost acceptance reply")
        for _ in range(6):
            if not tick(session, "submit-worker"):
                break
        session.expire_all()
        assert session.scalar(select(EmailDelivery)).state == "unknown"
        assert len(transport.messages) == 1
        observed = session.scalar(select(MarketObservation).order_by(MarketObservation.source_at.desc()))
        repeated = complete(
            session, session.get(Agent, aid), monkeypatch, page("106", 101, observed.source_at)
        )
        assert all(run.status == "succeeded" for run in repeated), [
            (run.status, run.error_message) for run in repeated
        ]
        assert len(transport.messages) == 1


def test_in_app_baseline_hash_does_not_change_when_email_is_added():
    from uuid import uuid4

    from app.market_schema import MarketScope
    from app.market_watch import policy_key

    before = MarketScope()
    after = MarketScope(
        email={
            "connector_id": str(uuid4()),
            "connector_revision": "a" * 64,
            "recipients": ["recipient@example.com"],
        }
    )
    assert policy_key(before) == policy_key(after)


def test_pause_remains_available_after_smtp_connection_was_removed(session):
    with TestClient(app) as api:
        connector, agent = prepare(session, api)
        assert api.delete("/api/connectors/" + connector["id"]).status_code == 204
        row = api.get("/api/agents/" + agent.id).json()
        response = api.post(
            "/api/agents/" + agent.id + "/enabled",
            json={
                "expected_updated_at": row["updated_at"],
                "enabled": False,
            },
        )
        assert response.status_code == 200, response.text
        assert not response.json()["enabled"]
        assert response.json()["market_email_authorization"]["resolution"] == "revoked"


def test_below_threshold_and_cooldown_do_not_create_extra_mail(session, monkeypatch, transport):
    from app.db import utcnow

    with TestClient(app) as api:
        _, agent = prepare(session, api)
        now = utcnow()
        for price, trade, delta, expected in [
            ("100", 100, 30, 0),
            ("101", 101, 20, 0),
            ("110", 102, 10, 1),
            ("120", 103, 1, 1),
        ]:
            runs = complete(session, agent, monkeypatch, page(price, trade, now - timedelta(seconds=delta)))
            assert all(run.status == "succeeded" for run in runs), [(r.status, r.error_message) for r in runs]
            assert len(transport.messages) == expected
