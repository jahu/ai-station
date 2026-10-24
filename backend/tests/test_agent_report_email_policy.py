"""Consent/connector policy only; no SMTP or operational email adapter is used."""

import json
from uuid import uuid4

import pytest
from app.agent_report_email import authorization, authorization_public, grant, revoke, saved_definition
from app.agent_schema import NotificationPolicy
from app.api import app
from app.market_email import rotate_connector_revision
from app.models import Agent, Approval, Connector
from fastapi.testclient import TestClient
from sqlalchemy import select


def prepared(session, *, mode="automatic"):
    with TestClient(app) as api:
        response = api.post(
            "/api/connectors",
            json={
                "key": "result-mail-" + str(uuid4()),
                "name": "Result mail",
                "kind": "email",
                "smtp": {
                    "host": "smtp.example.com",
                    "sender": "station@example.com",
                    "allowed_recipients": ["owner@example.com"],
                },
            },
        )
        assert response.status_code == 201, response.text
        connector = response.json()
        response = api.post(
            "/api/agents",
            json={
                "name": "Report",
                "goal": "Summarize the actual system observations",
                "model": "fixture",
                "tools": ["system_snapshot"],
                "notification_policy": {
                    "report_email": {
                        "connector_id": connector["id"],
                        "connector_revision": connector["email_policy_revision"],
                        "recipients": ["owner@example.com"],
                        "mode": mode,
                    }
                },
            },
        )
        assert response.status_code == 201, response.text
        aid = response.json()["id"]
    session.expire_all()
    agent = session.get(Agent, aid)
    return agent, saved_definition(agent)


def activate(session, agent, definition):
    receipt = grant(session, agent, definition, confirmed=True)
    agent.enabled = True
    session.commit()
    return receipt


def test_legacy_policy_json_and_empty_coercion_are_unchanged():
    expected = {"on_success": False, "on_failure": False, "on_approval": False}
    assert NotificationPolicy().model_dump() == expected
    assert NotificationPolicy.model_validate(None).model_dump() == expected
    assert NotificationPolicy(report_email=None).model_dump() == expected


def test_automatic_scope_needs_distinct_consent_and_binds_the_saved_agent(session):
    agent, definition = prepared(session)
    with pytest.raises(ValueError, match="Explicitly approve"):
        grant(session, agent, definition, confirmed=False)
    assert not list(session.scalars(select(Approval)))
    receipt = activate(session, agent, definition)
    assert authorization(session, agent, definition, expected_id=receipt.id).id == receipt.id
    assert authorization_public(session, agent)["valid"]
    assert "Summarize the actual system observations" not in json.dumps(receipt.payload)
    with pytest.raises(ValueError, match="explicitly approve"):
        authorization(session, agent, definition, expected_id=str(uuid4()))


def test_review_mode_does_not_create_or_inherit_an_automatic_grant(session):
    agent, definition = prepared(session, mode="review")
    agent.enabled = True
    session.commit()
    assert authorization(session, agent, definition) is None
    assert not list(session.scalars(select(Approval)))
    with pytest.raises(ValueError, match="cannot inherit"):
        authorization(session, agent, definition, expected_id=str(uuid4()))


@pytest.mark.parametrize(
    "field,value", [("goal", "Different data"), ("model", "other-model"), ("maximum_runtime", 7200)]
)
def test_changed_definition_rejects_frozen_old_scope(session, field, value):
    agent, definition = prepared(session)
    receipt = activate(session, agent, definition)
    setattr(agent, field, value)
    session.commit()
    with pytest.raises(ValueError, match="queued result"):
        authorization(session, agent, definition, expected_id=receipt.id)
    assert not authorization_public(session, agent)["valid"]


@pytest.mark.parametrize("change", ["pause", "revoke", "connector_revision", "recipient_allowlist"])
def test_revocation_and_target_changes_fail_closed_before_any_message(session, change):
    agent, definition = prepared(session)
    receipt = activate(session, agent, definition)
    connector = session.get(Connector, str(definition.notification_policy.report_email.connector_id))
    if change == "pause":
        agent.enabled = False
    elif change == "revoke":
        revoke(session, agent.id)
    elif change == "connector_revision":
        rotate_connector_revision(connector)
    else:
        connector.config_json = {
            **connector.config_json,
            "smtp": {**connector.config_json["smtp"], "allowed_recipients": ["other@example.com"]},
        }
    session.commit()
    with pytest.raises(ValueError):
        authorization(session, agent, definition, expected_id=receipt.id)


def test_new_grant_replaces_the_previous_receipt_instead_of_reviving_old_work(session):
    agent, definition = prepared(session)
    previous = activate(session, agent, definition)
    current = activate(session, agent, definition)
    assert current.id != previous.id and previous.resolution == "revoked"
    with pytest.raises(ValueError):
        authorization(session, agent, definition, expected_id=previous.id)
    assert authorization(session, agent, definition, expected_id=current.id).id == current.id
