"""Existing worker chains supply final results; all runtimes/SMTP are synthetic."""

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Agent, EmailDelivery, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_avatar import avatar_agent_runtime as avatar_agent_runtime
from test_agent_avatar import settings as avatar_settings
from test_agent_media import create as media_agent
from test_agent_media import implemented_media as implemented_media
from test_agent_media import start as start_media
from test_media_jobs import bridge as bridge
from test_media_jobs import full_avatar_bridge as full_avatar_bridge
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create as data_agent
from test_python_data_agents import data_environment as data_environment
from test_reviewed_email import connector
from test_reviewed_email import smtp as smtp


@pytest.fixture
def photo_bridge(tmp_path, monkeypatch):
    from test_images import bridge

    yield from bridge.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def music_runtime(tmp_path, monkeypatch):
    from test_music import music_bridge

    yield from music_bridge.__wrapped__(tmp_path, monkeypatch)


def policy(api, *, content="report", mode="review"):
    target = connector(api)
    return {
        "report_email": {
            "connector_id": target["id"],
            "connector_revision": target["email_policy_revision"],
            "recipients": ["one@example.com"],
            "mode": mode,
            "content": content,
        }
    }


def await_message(task_id):
    for i in range(35):
        with session_factory()() as db:
            tick(db, f"result-family-{i}")
            receipt = db.scalar(select(EmailDelivery))
            if receipt:
                source = db.get(Run, receipt.payload["agent_result"]["source_run_id"])
                assert source.status == "succeeded"
                # A verified data result may still have its read-only output
                # inspection queued. Wait for that stage before handing the
                # receipt to tests that expect the next claim to be delivery.
                from app.state import ACTIVE

                if db.scalar(
                    select(Run.id).where(
                        Run.task_id == task_id,
                        Run.executor_type == "data_inspection",
                        Run.status.in_(ACTIVE),
                    )
                ):
                    continue
                return receipt.id, receipt.run_id, source.executor_type, receipt.payload
    with session_factory()() as db:
        raise AssertionError(
            [
                (run.executor_type, run.status, run.error_message, run.metadata_json)
                for run in db.scalars(select(Run).where(Run.task_id == task_id))
            ]
        )


def send_review(api, receipt_id, run_id):
    approved = api.post(f"/api/runs/{run_id}/approval", json={"resolution": "granted"})
    assert approved.status_code == 200, approved.text
    with session_factory()() as db:
        tick(db, "send-family-result")
        assert db.get(EmailDelivery, receipt_id).state == "accepted", db.get(Run, run_id).error_message


@pytest.mark.parametrize("repair", [False, True])
def test_verified_data_answer_can_be_reviewed_and_sent_after_automatic_workspace_creation(
    data_environment, smtp, repair
):
    state = data_environment
    state["program_failures"] = int(repair)
    with TestClient(app) as api:
        agent, root, _, _ = data_agent(api, state, notification_policy=policy(api))
        did, rid, executor, payload = await_message(root["task_id"])
        assert executor == "agent_data_result"
        assert "The total is 27." in payload["body"] and "Table preview" in payload["body"]
        assert "import os" not in payload["body"] and "sales.csv" not in payload["body"]
        with session_factory()() as db:
            assert db.get(Agent, agent["id"]).project_id
        send_review(api, did, rid)
        assert len(smtp[0].messages) == 1


@pytest.mark.parametrize("generated", [False, True])
def test_avatar_delivery_is_prepared_only_after_final_verified_cpu_composition(
    avatar_agent_runtime, smtp, generated
):
    with TestClient(app) as api:
        agent = media_agent(
            api,
            kind="avatar",
            request=avatar_settings(api, generated=generated),
            notification_policy=policy(api, content="summary"),
        )
        root = start_media(api, agent)
        did, rid, executor, payload = await_message(root["task_id"])
        assert executor == "media_compose"
        assert "Media generation complete." in payload["body"]
        assert "Dzień dobry" not in payload["body"] and "A person speaking" not in payload["body"]
        assert "video:" in payload["body"]
        send_review(api, did, rid)
        assert len(smtp[0].messages) == 1


def test_automatic_data_workspace_retains_original_consent_without_renewing_it(data_environment, smtp):
    with TestClient(app) as api:
        upload = api.post("/api/data/uploads", files={"file": ("sales.csv", b"Total\n27\n", "text/csv")})
        assert upload.status_code == 201
        with session_factory()() as db:
            tick(db, "inspect-input")
        response = api.post(
            "/api/agents",
            json={
                "name": "Data report",
                "goal": "Calculate total",
                "model": data_environment["model"],
                "tools": ["python_data"],
                "data": {"input_artifact_ids": [upload.json()["id"]]},
                "notification_policy": policy(api, mode="automatic"),
            },
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        response = api.post(
            f"/api/agents/{agent['id']}/enabled",
            json={
                "expected_updated_at": agent["updated_at"],
                "enabled": True,
                "confirm_report_email": True,
            },
        )
        assert response.status_code == 200, response.text
        agent = response.json()
        root = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
        assert root.status_code == 202, root.text
        did, rid, _, _ = await_message(root.json()["task_id"])
        with session_factory()() as db:
            tick(db, "send-automatic-data-result")
            assert db.get(EmailDelivery, did).state == "accepted", db.get(Run, rid).error_message
        saved = api.get(f"/api/agents/{agent['id']}").json()
        assert saved["report_email_authorization"]["valid"]
        assert saved["report_email_authorization"]["id"] == agent["report_email_authorization"]["id"]
        # Subsequent executions reuse the already-created project and same grant.
        again = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": saved["updated_at"]})
        assert again.status_code == 202, again.text


@pytest.mark.parametrize("provider", ["local", "cursor", "codex"])
@pytest.mark.parametrize("checks", [False, True])
def test_coding_sends_only_summary_after_review_artifact_and_configured_checks(smtp, provider, checks):
    import json
    import tempfile
    from pathlib import Path

    from app.artifacts import register_file
    from app.coding_proposal_executor import CodingProposalExecutor
    from app.coding_tasks import queue_proposal
    from app.models import Artifact, Worktree
    from app.runs import transition
    from app.state import RunStatus
    from test_agent_coding import finish, project, start

    with TestClient(app) as api:
        scope = policy(api, content="summary")
        with session_factory()() as db:
            proj = project(db)
            if checks:
                proj.test_commands = [["python3", "-m", "unittest"]]
                db.commit()
            agent, parent = start(
                api,
                proj.id,
                tools=["coding_" + provider],
                permission_profile="agent_local" if provider == "local" else "agent_external_coding",
                notification_policy=scope,
            )
            tick(db, "coding-parent")
            preparation = db.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
            tree = db.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
            preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": tree.branch}}
            finish(db, preparation)
            queue_proposal(db, preparation, tree)
            proposal = db.get(Run, preparation.metadata_json["coding_run_id"])
            for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(db, proposal, state, event_type="test.transition")
            CodingProposalExecutor().finish(
                db,
                proposal,
                {
                    "run_id": proposal.id,
                    "project_id": proj.id,
                    "worktree_run_id": tree.run_id,
                    "files": [
                        {"path": "private.py", "diff": "private-code-marker", "insertions": 1, "deletions": 0}
                    ],
                    "summary": "private-summary-marker",
                    "provider": provider,
                },
            )
            db.commit()
            receipt = db.scalar(select(EmailDelivery))
            if checks:
                assert receipt is None
                validation = db.get(Run, proposal.metadata_json["validation_run_id"])
                for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                    transition(db, validation, state, event_type="test.transition")
                report = {
                    "run_id": validation.id,
                    "project_id": proj.id,
                    "worktree_run_id": tree.run_id,
                    "commands": [{**item, "exit_code": 0} for item in validation.parameters["commands"]],
                }
                with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
                    json.dump(report, handle)
                    handle.flush()
                    register_file(
                        db,
                        source=Path(handle.name),
                        artifact_type="json",
                        mime_type="application/json",
                        original_filename="validation.json",
                        run_id=validation.id,
                    )
                validation.metadata_json = {**validation.metadata_json, "validation": report}
                transition(db, validation, RunStatus.SUCCEEDED, event_type="run.completed")
                db.commit()
                receipt = db.scalar(select(EmailDelivery))
            assert receipt is not None, [(r.executor_type, r.metadata_json) for r in db.scalars(select(Run))]
            assert "Coding result ready for review." in receipt.payload["body"]
            assert "private" not in receipt.payload["body"]
            assert db.scalar(select(Artifact).where(Artifact.run_id == proposal.id))
            did, rid = receipt.id, receipt.run_id
        send_review(api, did, rid)
        assert len(smtp[0].messages) == 1


@pytest.mark.parametrize(
    "kind,fixture,settings",
    [
        ("music", "music_runtime", {"caption": "Calm piano", "duration_seconds": 10}),
        (
            "image",
            "photo_bridge",
            {"mode": "t2i", "prompt": "Quiet forest", "width": 256, "height": 256, "steps": 1},
        ),
        (
            "video",
            "bridge",
            {
                "prompt": "Quiet forest",
                "duration_seconds": 5,
                "width": 128,
                "height": 128,
                "steps": 4,
                "gpu": "7",
            },
        ),
    ],
)
def test_other_media_email_uses_only_the_completed_primary_output(
    implemented_media, smtp, request, kind, fixture, settings
):
    request.getfixturevalue(fixture)
    with TestClient(app) as api:
        agent = media_agent(
            api, kind=kind, request=settings, notification_policy=policy(api, content="summary")
        )
        parent = start_media(api, agent)
        did, rid, executor, payload = await_message(parent["task_id"])
        assert executor == {"music": "ace_step_music", "image": "photo_pipe", "video": "media_compose"}[kind]
        assert "Media generation complete." in payload["body"]
        assert settings.get("caption", settings.get("prompt")) not in payload["body"]
        send_review(api, did, rid)
        assert len(smtp[0].messages) == 1


def test_generic_market_report_email_does_not_imply_a_threshold_alert(smtp, monkeypatch):
    from test_market_watch import complete, page, setup_agent

    with TestClient(app) as api:
        scope = policy(api)
        with session_factory()() as db:
            agent = setup_agent(db)
            agent.notification_policy = scope
            db.commit()
            rows = complete(db, agent, monkeypatch, page())
            receipt = db.scalar(select(EmailDelivery))
            assert receipt is not None, [(r.status, r.metadata_json) for r in rows]
            assert "agent_result" in receipt.payload and "market_alert" not in receipt.payload
            assert "BTC-USD" in receipt.payload["body"]
            did, rid = receipt.id, receipt.run_id
        send_review(api, did, rid)
