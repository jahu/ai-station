"""Ordinary-worker alerts never replace reports or widen notification authority."""

import json

import pytest
from app.agent_alerts import SYSTEM
from app.agent_email_results import artifact_content
from app.agent_schema import NotificationPolicy
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, MemoryEntry, Notice, Run, RunEvent
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select

CRITERION = "Notify only about a significant new local model release, not repeated findings."
REPORT = "A verified synthetic release is available: Example Model v2."


def create(client, **extra):
    response = client.post(
        "/api/agents",
        json={
            "name": "Release watcher",
            "goal": "Research local model releases",
            "model": "fake-local",
            "enabled": True,
            "notification_policy": {"on_success": True, "on_failure": True, "report_condition": CRITERION},
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def execute(client, agent):
    current = client.get(f"/api/agents/{agent['id']}").json()
    response = client.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": current["updated_at"]}
    )
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        for _ in range(12):
            if tick(session, "alert-test") is None:
                break
        root = session.get(Run, response.json()["id"])
        source = session.scalar(select(Run).where(Run.parent_run_id == root.id, Run.executor_type == "agent"))
        assert source is not None
        return source.id


def provider(monkeypatch, response, *, during_check=None):
    checked = []

    async def stream(_self, **params):
        if params["messages"][0]["content"] == SYSTEM:
            assert params["json_output"] is True and not params.get("tools")
            checked.append(json.loads(params["messages"][1]["content"]))
            if during_check:
                during_check(checked[-1])
            yield response
        else:
            yield REPORT

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return checked


@pytest.mark.parametrize("notify", [True, False])
def test_success_criteria_preserve_the_actual_report_and_gate_success_notices(monkeypatch, notify):
    checked = provider(monkeypatch, json.dumps({"notify": notify, "reason": "Checked the actual findings."}))
    with TestClient(app) as client:
        agent = create(client, tools=["remember_report"])
        rid = execute(client, agent)
        with session_factory()() as session:
            run = session.get(Run, rid)
            assert run.status == "succeeded"
            assert run.metadata_json["report_alert"]["notify"] is notify
            artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))
            assert len(artifacts) == 1 and artifact_content(artifacts[0], text=True) == REPORT
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert len(notices) == int(notify)
            events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
            assert [e.payload["text"] for e in events if e.event_type == "agent.delta"] == [REPORT]
            assert sum(e.event_type == "agent.notification.suppressed" for e in events) == int(not notify)
            memories = list(session.scalars(select(MemoryEntry).where(MemoryEntry.scope_id == agent["id"])))
            assert len(memories) == 1 and memories[0].content == REPORT
        assert checked[0]["previous_report"] is None
        assert checked[0]["operator_criterion"] == CRITERION


def test_comparison_uses_only_verified_successful_same_agent_same_definition_report(monkeypatch):
    checked = provider(monkeypatch, '{"notify":false,"reason":"No new finding."}')
    with TestClient(app) as client:
        first = create(client)
        older = execute(client, first)
        other = create(client, name="Another watcher")
        execute(client, other)
        latest = execute(client, first)
        assert checked[0]["previous_report"] is None and checked[1]["previous_report"] is None
        assert checked[2]["previous_report"]["run_id"] == older
        assert checked[2]["previous_report"]["untrusted_text"] == REPORT
        with session_factory()() as session:
            assert (
                session.get(Run, latest).metadata_json["report_alert"]["previous_report"]["run_id"] == older
            )


@pytest.mark.parametrize(
    "raw",
    [
        '{"notify":"yes","reason":"x"}',
        '{"notify":true}',
        "not JSON",
        '{"notify":true,"reason":"x","email":"other@example.invalid"}',
    ],
)
def test_invalid_classifier_output_retains_report_but_never_notifies_success(monkeypatch, raw):
    provider(monkeypatch, raw)
    with TestClient(app) as client:
        agent = create(client)
        rid = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, rid).status == "failed"
            artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))
            assert len(artifacts) == 1 and artifact_content(artifacts[0], text=True) == REPORT
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert len(notices) == 1 and notices[0].kind == "failed"


def test_stop_during_classification_prevents_success_notices_and_classifier_artifacts(monkeypatch):
    def stop(_payload):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.executor_type == "agent", Run.status == "running"))
            request_cancel(session, run)
            session.commit()

    provider(monkeypatch, '{"notify":true,"reason":"A matching finding."}', during_check=stop)
    with TestClient(app) as client:
        agent = create(client, tools=["remember_report"])
        rid = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, rid).status == "canceled"
            assert not list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert not list(session.scalars(select(MemoryEntry).where(MemoryEntry.scope_id == agent["id"])))
            artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))
            assert len(artifacts) == 1 and artifact_content(artifacts[0], text=True) == REPORT


@pytest.mark.parametrize("change", ["bytes", "trash"])
def test_changed_report_during_classification_cannot_authorize_notification(monkeypatch, change):
    def tamper(payload):
        from app.config import get_settings

        with session_factory()() as session:
            artifact = session.get(Artifact, payload["current_report"]["artifact_id"])
            if change == "bytes":
                (get_settings().data_dir / artifact.relative_path).write_text("Changed report")
            else:
                from app.db import utcnow

                artifact.trashed_at = utcnow()
                session.commit()

    provider(monkeypatch, '{"notify":true,"reason":"Match."}', during_check=tamper)
    with TestClient(app) as client:
        agent = create(client)
        rid = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, rid).status == "failed"
            assert all(n.kind == "failed" for n in session.scalars(select(Notice)))


def test_empty_default_keeps_legacy_notification_identity_and_does_not_call_classifier(monkeypatch):
    assert NotificationPolicy().model_dump() == {
        "on_success": False,
        "on_failure": False,
        "on_approval": False,
    }
    checked = provider(monkeypatch, '{"notify":true,"reason":"Unused"}')
    with TestClient(app) as client:
        agent = create(client, notification_policy={"on_success": True})
        rid = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, rid).status == "succeeded"
        assert not checked


def test_trashed_previous_report_cannot_be_silently_dropped_or_used_as_a_new_baseline(monkeypatch):
    checked = provider(monkeypatch, '{"notify":false,"reason":"No new finding."}')
    with TestClient(app) as client:
        agent = create(client)
        old = execute(client, agent)
        with session_factory()() as session:
            from app.db import utcnow

            artifact = session.scalar(select(Artifact).where(Artifact.run_id == old))
            artifact.trashed_at = utcnow()
            session.commit()
        new = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, new).status == "failed"
        assert len(checked) == 1


@pytest.mark.parametrize("tool", ["coding_local", "create_media", "market_watch"])
def test_other_output_tools_cannot_silently_ignore_or_remove_a_saved_criterion(tool):
    from app.agent_schema import AgentSettings

    with pytest.raises(ValueError, match="Success criteria"):
        AgentSettings(
            name="Changed output",
            goal="Keep its original criterion",
            tools=[tool],
            notification_policy={"on_success": True, "report_condition": CRITERION},
        )


@pytest.mark.parametrize("notify", [True, False])
def test_criterion_also_gates_reviewed_email_without_changing_its_recipient_scope(monkeypatch, notify):
    from app.models import EmailDelivery
    from test_reviewed_email import connector

    provider(monkeypatch, json.dumps({"notify": notify, "reason": "Checked findings."}))
    with TestClient(app) as client:
        target = connector(client)
        agent = create(
            client,
            notification_policy={
                "report_condition": CRITERION,
                "report_email": {
                    "connector_id": target["id"],
                    "connector_revision": target["email_policy_revision"],
                    "recipients": ["one@example.com"],
                    "mode": "review",
                },
            },
        )
        rid = execute(client, agent)
        with session_factory()() as session:
            assert session.get(Run, rid).status == "succeeded"
            deliveries = list(session.scalars(select(EmailDelivery)))
            assert len(deliveries) == int(notify)
            if notify:
                mail = session.get(Run, deliveries[0].run_id)
                assert mail.status == "waiting_for_approval"
                assert deliveries[0].payload["recipients"] == ["one@example.com"]


def test_email_rechecks_the_criterion_after_approval_before_opening_smtp(monkeypatch):
    from app.models import EmailDelivery
    from test_reviewed_email import connector

    provider(monkeypatch, '{"notify":true,"reason":"Matching finding."}')
    opened = []

    def forbidden(*_args, **_kwargs):
        opened.append(True)
        raise AssertionError("A changed criterion decision must not reach SMTP")

    monkeypatch.setattr("smtplib.SMTP", forbidden)
    monkeypatch.setattr("smtplib.SMTP_SSL", forbidden)
    with TestClient(app) as client:
        target = connector(client)
        agent = create(
            client,
            notification_policy={
                "report_condition": CRITERION,
                "report_email": {
                    "connector_id": target["id"],
                    "connector_revision": target["email_policy_revision"],
                    "recipients": ["one@example.com"],
                    "mode": "review",
                },
            },
        )
        rid = execute(client, agent)
        with session_factory()() as session:
            delivery = session.scalar(select(EmailDelivery))
            mail_id = delivery.run_id
        approved = client.post(f"/api/runs/{mail_id}/approval", json={"resolution": "granted"})
        assert approved.status_code == 200, approved.text
        with session_factory()() as session:
            source = session.get(Run, rid)
            source.metadata_json = {
                **source.metadata_json,
                "report_alert": {**source.metadata_json["report_alert"], "notify": False},
            }
            session.commit()
            assert tick(session, "criterion-before-smtp") == mail_id
            assert session.get(Run, mail_id).status != "succeeded"
            assert session.get(Run, rid).status == "succeeded"
        assert not opened
