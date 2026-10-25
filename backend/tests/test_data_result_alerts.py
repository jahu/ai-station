"""Notification decisions cannot rerun or invalidate completed offline analysis."""

import json

import pytest
from app.agent_alerts import SYSTEM
from app.agent_outcome import workflow_outcome
from app.agent_schema import NotificationPolicy
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import EmailDelivery, Notice, Run
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create, finish
from test_python_data_agents import data_environment as data_environment

CRITERION = "Only notify when the computed total is at least 25 and is a new finding."


def classifier(monkeypatch, response, *, before=None):
    original = LocalChatProvider.stream
    calls = []

    async def stream(self, **params):
        if params["messages"][0]["content"] == SYSTEM:
            calls.append(params)
            if before:
                before(params)
            yield response
        else:
            async for value in original(self, **params):
                yield value

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls


def policy(**extra):
    return {"on_success": True, "on_failure": True, "report_condition": CRITERION, **extra}


def finished(client, parent):
    finish(client, parent)
    with session_factory()() as session:
        return list(session.scalars(select(Run).where(Run.task_id == parent["task_id"])))


def test_criterion_only_policy_is_recognized_instead_of_silently_dropped():
    value = NotificationPolicy.model_validate({"report_condition": CRITERION})
    assert value.report_condition == CRITERION and not value.on_success
    assert value.model_dump()["report_condition"] == CRITERION


@pytest.mark.parametrize("notify", [True, False])
def test_completed_data_gets_one_source_bound_check_and_preserves_analysis(
    data_environment, monkeypatch, notify
):
    calls = classifier(monkeypatch, json.dumps({"notify": notify, "reason": "The checked total is 27."}))
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        source = next(run for run in rows if run.executor_type == "agent_data_result")
        checks = [run for run in rows if run.executor_type == "agent_result_alert"]
        assert len(checks) == 1
        check = checks[0]
        assert source.status == check.status == "succeeded", check.error_message
        assert check.parent_run_id == source.id and check.task_id == source.task_id
        assert check.effective_permissions == ["filesystem_read", "network_read"]
        assert check.parameters["agent_coding_deadline"] == source.parameters["agent_coding_deadline"]
        assert source.metadata_json["data_result"]["answer"] == "The total is 27."
        assert source.metadata_json["report_alert"]["notify"] is notify
        assert source.metadata_json["report_alert"]["check_run_id"] == check.id
        assert len(calls) == 1 and calls[0]["model"] == data_environment["model"]
        payload = json.loads(calls[0]["messages"][1]["content"])
        assert "27" in payload["current_report"]["untrusted_text"]
        assert payload["current_report"]["family"] == "data" and payload["previous_report"] is None
        assert data_environment["calls"] == 1
        generation_prompt = json.loads(data_environment["model_requests"][0]["messages"][1]["content"])
        assert generation_prompt["notification_criterion"] == CRITERION
        with session_factory()() as session:
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert len(notices) == int(notify)
            outcome = workflow_outcome(session, session.get(Run, parent["id"]))
            assert outcome["status"] == "succeeded" and outcome["alert_status"] == "succeeded"


def test_next_execution_compares_the_private_workspace_derivation_without_repeating_notices(
    data_environment, monkeypatch
):
    original = LocalChatProvider.stream
    snapshots = []

    async def stream(self, **params):
        if params["messages"][0]["content"] == SYSTEM:
            snapshots.append(json.loads(params["messages"][1]["content"]))
            yield json.dumps({"notify": len(snapshots) == 1, "reason": "Compare the verified total."})
        else:
            async for value in original(self, **params):
                yield value

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        first = finished(client, parent)
        source = next(run for run in first if run.executor_type == "agent_data_result")
        current = client.get(f"/api/agents/{agent['id']}").json()
        queued = client.post(
            f"/api/agents/{agent['id']}/run", json={"expected_updated_at": current["updated_at"]}
        )
        assert queued.status_code == 202, queued.text
        second = finished(client, queued.json())
        latest = next(run for run in second if run.executor_type == "agent_data_result")
        check = next(run for run in second if run.executor_type == "agent_result_alert")
        assert latest.status == check.status == "succeeded", check.error_message
        assert snapshots[0]["previous_report"] is None
        assert snapshots[1]["previous_report"]["run_id"] == source.id
        assert latest.metadata_json["report_alert"]["notify"] is False
        with session_factory()() as session:
            assert len(list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))) == 1
            from app.agent_result_alert import publish

            existing = publish(session, session.get(Run, latest.id))
            assert existing.id == check.id
            assert (
                len(
                    list(
                        session.scalars(
                            select(Run).where(
                                Run.task_id == latest.task_id, Run.executor_type == "agent_result_alert"
                            )
                        )
                    )
                )
                == 1
            )


def test_inactive_criterion_survives_api_save_without_extra_classification(data_environment):
    with TestClient(app) as client:
        agent, parent, _, _ = create(
            client, data_environment, notification_policy={"report_condition": CRITERION}
        )
        assert agent["notification_policy"]["report_condition"] == CRITERION
        rows = finished(client, parent)
        assert all(run.executor_type != "agent_result_alert" for run in rows)
        assert data_environment["calls"] == 1
        request = json.loads(data_environment["model_requests"][0]["messages"][1]["content"])
        assert "notification_criterion" not in request


def test_invalid_check_never_repairs_python_or_erases_data(data_environment, monkeypatch):
    classifier(monkeypatch, '{"notify":"yes","reason":"Invalid decision"}')
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        source = next(run for run in rows if run.executor_type == "agent_data_result")
        check = next(run for run in rows if run.executor_type == "agent_result_alert")
        assert source.status == "succeeded" and check.status == "failed"
        assert not source.metadata_json.get("repair_run_id") and data_environment["calls"] == 1
        with session_factory()() as session:
            outcome = workflow_outcome(session, session.get(Run, parent["id"]))
            assert outcome["status"] == "succeeded" and outcome["alert_status"] == "failed"
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert len(notices) == 1 and "Notification check" in notices[0].title
            assert not list(session.scalars(select(EmailDelivery)))


def test_stop_during_check_retains_the_successful_analysis(data_environment, monkeypatch):
    def stop(_params):
        with session_factory()() as session:
            run = session.scalar(
                select(Run).where(Run.executor_type == "agent_result_alert", Run.status == "running")
            )
            request_cancel(session, run)
            session.commit()

    classifier(monkeypatch, '{"notify":true,"reason":"Total matches."}', before=stop)
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        source = next(run for run in rows if run.executor_type == "agent_data_result")
        check = next(run for run in rows if run.executor_type == "agent_result_alert")
        assert source.status == "succeeded" and check.status == "canceled"
        assert source.metadata_json["report_alert"]["state"] == "canceled"
        assert data_environment["calls"] == 1
        with session_factory()() as session:
            assert not list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))


def test_model_preparation_failure_is_a_check_failure_without_new_python(data_environment, monkeypatch):
    from app import llama

    original = llama.prepare_consumer

    def prepare(session, run):
        if run.executor_type == "agent_result_alert":
            raise ValueError("Inspect the unavailable owned runtime")
        return original(session, run)

    monkeypatch.setattr(llama, "prepare_consumer", prepare)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        source = next(run for run in rows if run.executor_type == "agent_data_result")
        check = next(run for run in rows if run.executor_type == "agent_result_alert")
        assert source.status == "succeeded" and check.status == "failed"
        assert "unavailable owned runtime" in check.error_message
        assert data_environment["calls"] == 1


def test_failed_notification_model_dependency_is_not_a_generation_failure(data_environment, monkeypatch):
    from app import llama
    from app.dependencies import depend_on
    from app.notices import emit_agent_notice
    from app.runs import create_run

    original = llama.prepare_consumer

    def prepare(session, run):
        if run.executor_type != "agent_result_alert":
            return original(session, run)
        load = create_run(
            session,
            run.task,
            run_type="runtime",
            capability="runtime.llama.load",
            executor_type="llama_load",
            execution_target="host",
        )
        load.status = "failed"  # A terminal fixture; never dispatch an actual model lifecycle operation.
        depend_on(session, run, load)
        assert emit_agent_notice(session, load, "failed") is None

    monkeypatch.setattr(llama, "prepare_consumer", prepare)
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        assert next(run for run in rows if run.executor_type == "agent_data_result").status == "succeeded"
        assert next(run for run in rows if run.executor_type == "agent_result_alert").status == "failed"
        with session_factory()() as session:
            outcome = workflow_outcome(session, session.get(Run, parent["id"]))
            assert outcome["status"] == "succeeded" and outcome["alert_status"] == "failed"
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert len(notices) == 1 and "Notification check" in notices[0].title
        assert data_environment["calls"] == 1


@pytest.mark.parametrize("notify", [True, False])
def test_data_criterion_controls_reviewed_email_without_inheriting_send_authority(
    data_environment, monkeypatch, notify
):
    from test_reviewed_email import connector

    classifier(monkeypatch, json.dumps({"notify": notify, "reason": "Checked the actual total."}))
    with TestClient(app) as client:
        target = connector(client)
        _, parent, _, _ = create(
            client,
            data_environment,
            notification_policy=policy(
                report_email={
                    "connector_id": target["id"],
                    "connector_revision": target["email_policy_revision"],
                    "recipients": ["one@example.com"],
                    "mode": "review",
                }
            ),
        )
        if notify:
            # The final email intentionally stays waiting for operator approval.
            for _ in range(14):
                from app.engine import tick

                with session_factory()() as session:
                    if tick(session, "data-alert-email") is None:
                        break
        else:
            finished(client, parent)
        with session_factory()() as session:
            source = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
            )
            check = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_result_alert")
            )
            assert source.status == check.status == "succeeded", check.error_message
            assert (
                "email_send" not in check.effective_permissions
                and "network_external" not in check.effective_permissions
            )
            deliveries = list(session.scalars(select(EmailDelivery)))
            assert len(deliveries) == int(notify)
            if notify:
                assert session.get(Run, deliveries[0].run_id).status == "waiting_for_approval"
                assert deliveries[0].payload["recipients"] == ["one@example.com"]


def test_task_stop_after_analysis_cancels_only_pending_notification_work(data_environment, monkeypatch):
    def stop(_params):
        from app.task_control import cancel_task

        with session_factory()() as session:
            check = session.scalar(
                select(Run).where(Run.executor_type == "agent_result_alert", Run.status == "running")
            )
            cancel_task(session, check.task)
            session.commit()

    classifier(monkeypatch, '{"notify":true,"reason":"Match"}', before=stop)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        assert next(run for run in rows if run.executor_type == "agent_data_result").status == "succeeded"
        assert next(run for run in rows if run.executor_type == "agent_result_alert").status == "canceled"
        with session_factory()() as session:
            outcome = workflow_outcome(session, session.get(Run, parent["id"]))
            assert outcome["status"] == "succeeded" and outcome["alert_status"] == "canceled"
            assert not list(session.scalars(select(Notice)))


def test_expired_check_does_not_prepare_another_model(data_environment, monkeypatch):
    from datetime import timedelta

    from app import agent_result_alert, llama

    now = agent_result_alert.utcnow
    monkeypatch.setattr(agent_result_alert, "utcnow", lambda: now() + timedelta(days=1))
    original = llama.prepare_consumer
    attempted = []

    def prepare(session, run):
        if run.executor_type == "agent_result_alert":
            attempted.append(run.id)
        return original(session, run)

    monkeypatch.setattr(llama, "prepare_consumer", prepare)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        assert next(run for run in rows if run.executor_type == "agent_data_result").status == "succeeded"
        assert next(run for run in rows if run.executor_type == "agent_result_alert").status == "failed"
        assert not attempted and data_environment["calls"] == 1


def test_failed_check_does_not_consume_the_finding_for_the_next_execution(data_environment, monkeypatch):
    original = LocalChatProvider.stream
    checked = []

    async def stream(self, **params):
        if params["messages"][0]["content"] == SYSTEM:
            checked.append(json.loads(params["messages"][1]["content"]))
            yield (
                "invalid first decision"
                if len(checked) == 1
                else '{"notify":true,"reason":"First checked finding."}'
            )
        else:
            async for value in original(self, **params):
                yield value

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        first = finished(client, parent)
        assert next(run for run in first if run.executor_type == "agent_result_alert").status == "failed"
        current = client.get(f"/api/agents/{agent['id']}").json()
        response = client.post(
            f"/api/agents/{agent['id']}/run", json={"expected_updated_at": current["updated_at"]}
        )
        assert response.status_code == 202
        rows = finished(client, response.json())
        check = next(run for run in rows if run.executor_type == "agent_result_alert")
        assert check.status == "succeeded", check.error_message
        assert checked[1]["previous_report"] is None
        with session_factory()() as session:
            notices = list(session.scalars(select(Notice).where(Notice.agent_id == agent["id"])))
            assert sorted(notice.kind for notice in notices) == ["failed", "succeeded"]


@pytest.mark.parametrize("change", ["bytes", "trash"])
def test_changed_data_report_during_check_fails_without_reexecuting_python(
    data_environment, monkeypatch, change
):
    from app.config import get_settings
    from app.db import utcnow
    from app.models import Artifact

    def tamper(params):
        payload = json.loads(params["messages"][1]["content"])
        with session_factory()() as session:
            artifact = session.get(Artifact, payload["current_report"]["artifact_id"])
            if change == "bytes":
                (get_settings().data_dir / artifact.relative_path).write_text("changed")
            else:
                artifact.trashed_at = utcnow()
                session.commit()

    classifier(monkeypatch, '{"notify":true,"reason":"Match"}', before=tamper)
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        assert next(r for r in rows if r.executor_type == "agent_data_result").status == "succeeded"
        check = next(r for r in rows if r.executor_type == "agent_result_alert")
        assert check.status == "failed" and data_environment["calls"] == 1
        with session_factory()() as session:
            assert not list(session.scalars(select(EmailDelivery)))
            assert all(n.kind == "failed" for n in session.scalars(select(Notice)))


def test_retention_of_older_baselines_does_not_invalidate_the_latest_checked_result(
    data_environment, monkeypatch
):
    from app.db import utcnow
    from app.models import Artifact

    calls = classifier(monkeypatch, '{"notify":false,"reason":"Unchanged total"}')
    with TestClient(app) as client:
        agent, parent, _, _ = create(client, data_environment, notification_policy=policy())
        first = finished(client, parent)
        first_source = next(r for r in first if r.executor_type == "agent_data_result")
        sources = [first_source]
        for index in range(2):
            if index == 1:
                with session_factory()() as session:
                    artifact_id = first_source.metadata_json["data_result"]["report_artifact_id"]
                    session.get(Artifact, artifact_id).trashed_at = utcnow()
                    session.commit()
            current = client.get(f"/api/agents/{agent['id']}").json()
            response = client.post(
                f"/api/agents/{agent['id']}/run", json={"expected_updated_at": current["updated_at"]}
            )
            assert response.status_code == 202
            rows = finished(client, response.json())
            check = next(r for r in rows if r.executor_type == "agent_result_alert")
            assert check.status == "succeeded", check.error_message
            source = next(r for r in rows if r.executor_type == "agent_data_result")
            assert source.metadata_json["report_alert"]["previous_report"]["run_id"] == sources[-1].id
            sources.append(source)
        assert len(calls) == 3 and data_environment["calls"] == 3


def test_data_email_rechecks_successful_check_before_opening_transport(data_environment, monkeypatch):
    from app.engine import tick
    from test_reviewed_email import connector

    classifier(monkeypatch, '{"notify":true,"reason":"Matches"}')
    opened = []

    def forbidden(*args, **kwargs):
        opened.append(True)
        raise AssertionError("An invalidated check must not open SMTP")

    monkeypatch.setattr("smtplib.SMTP", forbidden)
    monkeypatch.setattr("smtplib.SMTP_SSL", forbidden)
    with TestClient(app) as client:
        target = connector(client)
        _, parent, _, _ = create(
            client,
            data_environment,
            notification_policy=policy(
                report_email={
                    "connector_id": target["id"],
                    "connector_revision": target["email_policy_revision"],
                    "recipients": ["one@example.com"],
                    "mode": "review",
                }
            ),
        )
        for _ in range(14):
            with session_factory()() as session:
                if tick(session, "data-email-check") is None:
                    break
        with session_factory()() as session:
            delivery = session.scalar(select(EmailDelivery))
            assert delivery is not None
            mail_id = delivery.run_id
            check_id = session.scalar(
                select(Run.id).where(
                    Run.task_id == parent["task_id"], Run.executor_type == "agent_result_alert"
                )
            )
        response = client.post(f"/api/runs/{mail_id}/approval", json={"resolution": "granted"})
        assert response.status_code == 200, response.text
        with session_factory()() as session:
            check = session.get(Run, check_id)
            check.parameters = {**check.parameters, "source_report": {"run_id": "other-result"}}
            session.commit()
            assert tick(session, "data-email-invalidated-check") == mail_id
            assert session.get(Run, mail_id).status == "failed"
        assert not opened


def test_stale_notification_check_is_inspected_without_replay_or_late_publication(
    data_environment, monkeypatch
):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.db import utcnow
    from app.recovery import recover_stale

    def lose_worker(_params):
        with session_factory()() as session:
            check = session.scalar(
                select(Run).where(Run.executor_type == "agent_result_alert", Run.status == "running")
            )
            check.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            recovered = recover_stale(session, SimpleNamespace(inspect_process=lambda _: {"alive": False}))
            assert recovered == [check.id]
            session.commit()

    calls = classifier(monkeypatch, '{"notify":true,"reason":"Late response"}', before=lose_worker)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment, notification_policy=policy())
        rows = finished(client, parent)
        assert next(r for r in rows if r.executor_type == "agent_data_result").status == "succeeded"
        check = next(r for r in rows if r.executor_type == "agent_result_alert")
        assert check.status == "interrupted", check.error_message
        assert len(calls) == 1 and data_environment["calls"] == 1
        with session_factory()() as session:
            assert not list(session.scalars(select(EmailDelivery)))
            assert all(n.kind == "interrupted" for n in session.scalars(select(Notice)))
            outcome = workflow_outcome(session, session.get(Run, parent["id"]))
            assert outcome["status"] == "succeeded" and outcome["alert_status"] == "interrupted"
