"""Generated data email attachment scope; no external messages or credentials."""

import json
from email.parser import BytesParser
from email.policy import default
from uuid import uuid4

import pytest
from app.agent_email_schema import AgentReportEmailScope
from app.api import app
from fastapi.testclient import TestClient
from test_agent_result_email_families import await_message, policy, send_review
from test_data_output_files import chart, workbook
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create as data_agent
from test_python_data_agents import data_environment as data_environment
from test_reviewed_email import smtp as smtp


def test_attachment_policy_keeps_legacy_default_identity_and_canonicalizes_selected_kinds():
    raw = {"connector_id": str(uuid4()), "connector_revision": "a" * 64, "recipients": ["one@example.com"]}
    assert "attachment_kinds" not in AgentReportEmailScope(**raw).model_dump(mode="json")
    scope = AgentReportEmailScope(**raw, attachment_kinds=["xlsx", "csv"])
    assert scope.attachment_kinds == ["csv", "xlsx"]


def test_selected_verified_generated_files_are_real_mime_attachments(data_environment, smtp):
    expected_workbook = workbook()
    data_environment.update(
        data_exports=1,
        exports={"result.xlsx": expected_workbook, "chart.png": chart(), "report.txt": b"Result 27\n"},
    )
    with TestClient(app) as api:
        settings = policy(api, content="summary")
        settings["report_email"]["attachment_kinds"] = ["csv", "xlsx", "png", "text"]
        agent, root, _, _ = data_agent(api, data_environment, notification_policy=settings)
        did, rid, executor, payload = await_message(root["task_id"])
        assert [item["filename"] for item in payload["attachments"]] == [
            "result.csv",
            "result.xlsx",
            "chart.png",
            "report.txt",
        ]
        assert not smtp[0].messages
        send_review(api, did, rid)
        message = BytesParser(policy=default).parsebytes(smtp[0].messages[0][2])
        attachments = {item.get_filename(): item for item in message.iter_attachments()}
        assert set(attachments) == {"result.csv", "result.xlsx", "chart.png", "report.txt"}
        assert attachments["result.csv"].get_payload(decode=True) == b"Total\r\n27\r\n"
        assert attachments["result.xlsx"].get_payload(decode=True) == expected_workbook
        assert attachments["report.txt"].get_payload(decode=True) == b"Result 27\n"
        assert attachments["chart.png"].get_content_type() == "image/png"
        assert "import os" not in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.parametrize(
    "value", [["pdf"], ["csv", "csv"], True, "xlsx", ["csv", "xlsx", "png", "text", "csv"]]
)
def test_attachment_formats_are_bounded_unique_known_choices(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentReportEmailScope(
            connector_id=uuid4(),
            connector_revision="a" * 64,
            recipients=["one@example.com"],
            attachment_kinds=value,
        )


def test_files_require_the_data_tool_and_change_reviewed_definition_identity():
    from app.agent_email_schema import definition_fingerprint
    from app.agent_schema import AgentSettings
    from pydantic import ValidationError

    mail = {"connector_id": str(uuid4()), "connector_revision": "a" * 64, "recipients": ["one@example.com"]}
    base = AgentSettings(
        name="Data email",
        goal="Create a table",
        tools=["python_data"],
        data={"operation": "create"},
        notification_policy={"report_email": mail},
    )
    selected = base.model_copy(
        update={
            "notification_policy": base.notification_policy.model_copy(
                update={"report_email": AgentReportEmailScope(**mail, attachment_kinds=["xlsx"])}
            )
        }
    )
    assert definition_fingerprint(base) != definition_fingerprint(selected)
    with pytest.raises(ValidationError):
        AgentSettings(
            name="Report",
            goal="Report system state",
            tools=["telemetry"],
            notification_policy={"report_email": {**mail, "attachment_kinds": ["csv"]}},
        )


@pytest.fixture
def prepared(data_environment, smtp):
    from app.db import session_factory
    from app.models import Artifact, Run

    data_environment.update(data_exports=1, exports={"result.xlsx": workbook()})
    with TestClient(app) as api:
        settings = policy(api)
        settings["report_email"]["attachment_kinds"] = ["xlsx"]
        agent, root, original, _ = data_agent(api, data_environment, notification_policy=settings)
        did, rid, _, payload = await_message(root["task_id"])
        with session_factory()() as db:
            generation = next(
                row
                for row in db.query(Run).filter(Run.task_id == root["task_id"])
                if row.executor_type == "agent_data_generate"
            )
            request = json.loads(generation.parameters["messages"][1]["content"])
            assert "result.xlsx" in request["runtime"]["required_outputs"]
            assert "one@example.com" not in json.dumps(request) and "station@example.com" not in json.dumps(
                request
            )
            item = db.get(Artifact, payload["attachments"][0]["artifact_id"])
            assert item.id != original["id"] and item.run_id == payload["agent_result"]["source_run_id"]
        yield api, agent, did, rid, payload


@pytest.mark.parametrize(
    "change", ["trash", "bytes", "filename", "input_pointer", "manifest", "permission", "symlink", "hardlink"]
)
def test_changed_generated_files_or_scope_never_reach_smtp(prepared, smtp, change, tmp_path):
    import os

    from app.config import get_settings
    from app.db import session_factory, utcnow
    from app.models import Artifact, EmailDelivery, Run
    from test_reviewed_email import step

    api, agent, did, rid, payload = prepared
    approved = api.post(f"/api/runs/{rid}/approval", json={"resolution": "granted"})
    assert approved.status_code == 200
    with session_factory()() as db:
        artifact = db.get(Artifact, payload["attachments"][0]["artifact_id"])
        path = get_settings().data_dir / artifact.relative_path
        if change == "trash":
            artifact.trashed_at = utcnow()
        elif change == "bytes":
            path.write_bytes(b"Changed workbook")
        elif change == "filename":
            artifact.original_filename = "injected\r\nBcc: other@example.com"
        elif change == "input_pointer":
            source = db.get(Run, payload["agent_result"]["source_run_id"])
            value = source.metadata_json["data_result"]
            source.metadata_json = {
                **source.metadata_json,
                "data_result": {
                    **value,
                    "exports": [
                        {**x, "artifact_id": value["input_artifact_ids"][0]} for x in value["exports"]
                    ],
                },
            }
        elif change == "manifest":
            receipt = db.get(EmailDelivery, did)
            receipt.payload = {**receipt.payload, "attachments": []}
        elif change == "permission":
            run = db.get(Run, rid)
            run.effective_permissions = ["email_send", "network_external"]
        elif change == "symlink":
            outside = tmp_path / "outside.xlsx"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
        else:
            os.link(path, tmp_path / "linked.xlsx")
        db.commit()
    step()
    assert not smtp[0].messages and not smtp[1]
    assert api.get("/api/email/deliveries").json()[0]["state"] == "failed_before_send"


@pytest.mark.parametrize("change", ["bytes", "pause"])
def test_attachment_authority_is_rechecked_after_smtp_connection(prepared, smtp, monkeypatch, change):
    from app.config import get_settings
    from app.db import session_factory
    from app.models import Agent, Artifact
    from test_reviewed_email import step

    api, agent, did, rid, payload = prepared
    assert api.post(f"/api/runs/{rid}/approval", json={"resolution": "granted"}).status_code == 200

    def connect(config, password):
        with session_factory()() as db:
            if change == "pause":
                db.get(Agent, agent["id"]).enabled = False
            else:
                item = db.get(Artifact, payload["attachments"][0]["artifact_id"])
                (get_settings().data_dir / item.relative_path).write_bytes(b"Changed after connect")
            db.commit()
        return smtp[0]

    monkeypatch.setattr("app.email_delivery.connect_smtp", connect)
    step()
    assert not smtp[0].messages
    assert api.get("/api/email/deliveries").json()[0]["state"] == "failed_before_send"


def test_stop_during_last_result_check_prevents_data_submission(prepared, smtp, monkeypatch):
    from app import agent_email_results
    from app.models import Run
    from app.runs import request_cancel
    from test_reviewed_email import step

    api, agent, did, rid, payload = prepared
    assert api.post(f"/api/runs/{rid}/approval", json={"resolution": "granted"}).status_code == 200
    original = agent_email_results.result_snapshot

    def check(*args, **kwargs):
        value = original(*args, **kwargs)
        if smtp[1]:
            worker = args[0]
            request_cancel(worker, worker.get(Run, rid))
            worker.commit()
        return value

    monkeypatch.setattr(agent_email_results, "result_snapshot", check)
    step()
    assert not smtp[0].messages
    receipt = api.get("/api/email/deliveries").json()[0]
    assert receipt["state"] == "canceled", receipt


def test_uncertain_attachment_send_is_not_replayed(prepared, smtp):
    from app.agent_report_email import publish
    from app.db import session_factory
    from app.models import EmailDelivery, Run
    from test_reviewed_email import step

    api, agent, did, rid, payload = prepared
    smtp[0].failure = TimeoutError("Synthetic lost acceptance response")
    assert api.post(f"/api/runs/{rid}/approval", json={"resolution": "granted"}).status_code == 200
    step()
    assert len(smtp[0].messages) == 1
    assert api.get("/api/email/deliveries").json()[0]["state"] == "unknown"
    with session_factory()() as db:
        receipt = publish(db, db.get(Run, payload["agent_result"]["source_run_id"]))
        assert receipt.id == did and db.query(EmailDelivery).count() == 1
        db.commit()
    step()
    assert len(smtp[0].messages) == 1


@pytest.mark.parametrize("size", [0, 4 * 1024**2 + 1, -1])
def test_attachment_sizes_fail_before_reading_or_connecting(size):
    from types import SimpleNamespace

    from app.agent_email_attachments import describe

    artifact = SimpleNamespace(
        id="generated",
        run_id="source",
        trashed_at=None,
        original_filename="result.csv",
        artifact_type="document",
        mime_type="text/csv",
        metadata_json={"agent_data_download": True},
        size_bytes=size,
        sha256="a" * 64,
    )
    with pytest.raises(ValueError):
        describe(artifact, "csv", "source")


def test_automatic_attachment_scope_survives_only_its_reviewed_workspace_derivation(data_environment, smtp):
    from app.db import session_factory
    from app.engine import tick
    from app.models import EmailDelivery

    expected = workbook()
    data_environment.update(data_exports=1, exports={"result.xlsx": expected})
    with TestClient(app) as api:
        notification = policy(api, mode="automatic", content="summary")
        notification["report_email"]["attachment_kinds"] = ["xlsx"]
        response = api.post(
            "/api/agents",
            json={
                "name": "Automatic workbook",
                "goal": "Create a CSV table with a Total of 27",
                "tools": ["python_data"],
                "data": {"operation": "create"},
                "model": data_environment["model"],
                "notification_policy": notification,
            },
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        enabled = api.post(
            f"/api/agents/{saved['id']}/enabled",
            json={"expected_updated_at": saved["updated_at"], "enabled": True, "confirm_report_email": True},
        )
        assert enabled.status_code == 200, enabled.text
        saved = enabled.json()
        started = api.post(
            f"/api/agents/{saved['id']}/run", json={"expected_updated_at": saved["updated_at"]}
        )
        assert started.status_code == 202, started.text
        did, rid, _, payload = await_message(started.json()["task_id"])
        with session_factory()() as db:
            for _ in range(8):
                tick(db, "automatic-attachment-worker")
                if db.get(EmailDelivery, did).state == "accepted":
                    break
            assert db.get(EmailDelivery, did).state == "accepted"
        final = api.get(f"/api/agents/{saved['id']}").json()
        assert final["report_email_authorization"]["id"] == saved["report_email_authorization"]["id"]
        assert final["report_email_authorization"]["valid"]
        attachment = next(BytesParser(policy=default).parsebytes(smtp[0].messages[0][2]).iter_attachments())
        assert attachment.get_filename() == "result.xlsx" and attachment.get_payload(decode=True) == expected
