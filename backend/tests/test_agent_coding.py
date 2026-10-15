from datetime import timedelta

from app.api import app
from app.coding_tasks import queue_proposal, queue_validation
from app.db import session_factory, utcnow
from app.engine import tick
from app.heartbeat import cancel_expired_coding
from app.models import Agent, Notice, Project, Run, Worktree
from app.runs import create_run, create_task, request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


def project(session):
    row = Project(name="Owned project", repo_path="/projects/example", agent_rules="Keep tests meaningful")
    session.add(row)
    session.commit()
    return row


def start(client, project_id, **changes):
    body = {
        "name": "Local builder",
        "goal": "Create a tested calculator",
        "model": "fake-local",
        "tools": ["coding_local"],
        "project_id": project_id,
        "enabled": True,
        **changes,
    }
    response = client.post("/api/agents", json=body)
    assert response.status_code == 201, response.text
    agent = response.json()
    response = client.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
    )
    assert response.status_code == 202, response.text
    return agent, response.json()


def finish(session, run):
    for status in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED):
        transition(session, run, status, event_type="test.transition")


def test_activation_requires_exclusive_tool_and_explicit_external_project():
    client = TestClient(app)
    for extra in (
        {"project_id": None, "tools": ["coding_cursor"], "permission_profile": "agent_external_coding"},
        {"tools": ["coding_local", "system_snapshot"]},
        {"tool_calling": "bounded"},
    ):
        response = client.post(
            "/api/agents",
            json={
                "name": "Builder",
                "goal": "Write code",
                "model": "fake",
                "enabled": True,
                "tools": ["coding_local"],
                **extra,
            },
        )
        assert response.status_code == 422
    draft = client.post(
        "/api/agents", json={"name": "Builder", "goal": "Write code", "tools": ["coding_local"]}
    )
    assert draft.status_code == 201
    assert not draft.json()["enabled"]


def test_agent_publishes_existing_coding_chain_and_cancel_reaches_grandchild():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id)
        assert tick(session, "builder") == parent["id"]
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        assert preparation.executor_type == "worktree_prepare"
        assert preparation.project_id == row.id and preparation.agent_id == agent["id"]
        request = preparation.parameters["local_coding"]
        assert request["explore"] is True and request["model"] == "fake-local"
        assert "Keep tests meaningful" in request["guidance"]
        assert "external_ai" not in preparation.effective_permissions
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
        assert not worktree.owned and worktree.relative_path.startswith("worktrees/")
        preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": worktree.branch}}
        queue_proposal(session, preparation, worktree)
        proposal = session.get(Run, preparation.metadata_json["coding_run_id"])
        finish(session, preparation)
        session.commit()
        view = client.get("/api/runs/" + parent["id"]).json()["workflow"]
        assert [s["key"] for s in view["steps"]] == ["coding.prepare", "coding.local"]
        request_cancel(session, session.get(Run, parent["id"]))
        session.commit()
        assert session.get(Run, proposal.id).status == "canceled"
        assert not session.scalars(
            select(Run).where(Run.capability.in_(["coding.commit", "coding.publish"]))
        ).all()


def test_coding_agent_cannot_bypass_other_project_work():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id)
        other_task = create_task(
            session, title="Existing user task", prompt="", capability="coding.local", project_id=row.id
        )
        other = create_run(
            session, other_task, run_type="coding", capability="coding.local", executor_type="local_proposal"
        )
        session.commit()
        tick(session, "builder")
        assert session.get(Run, parent["id"]).status == "failed"
        assert session.get(Run, other.id).status == "queued"
        assert not session.scalars(select(Worktree)).all()


def test_revoked_write_permission_creates_no_children():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id)
        run = session.get(Run, parent["id"])
        run.effective_permissions = ["filesystem_read"]
        session.commit()
        tick(session, "builder")
        assert session.get(Run, run.id).status == "failed"
        assert not session.scalars(select(Worktree)).all()


def test_gated_coding_waits_before_preparing_worktree():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id, workflow_mode="gated")
        assert parent["status"] == "waiting_for_approval"
        assert tick(session, "builder") is None
        assert not session.scalars(select(Worktree)).all()
        assert "agent_coding_deadline" not in session.get(Run, parent["id"]).task.metadata_json


def test_coding_deadline_cancels_owned_child_before_dispatch():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id)
        tick(session, "builder")
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        preparation.parameters = {
            **preparation.parameters,
            "agent_coding_deadline": (utcnow() - timedelta(seconds=1)).isoformat(),
        }
        session.commit()
        transition(session, preparation, RunStatus.CLAIMED, event_type="test.claim")
        cancel_expired_coding(session, preparation.id)
        assert preparation.status == "cancel_requested"
        assert not preparation.metadata_json.get("dispatch_attempted")
        session.commit()
        cancel_expired_coding(session, preparation.id)
        assert preparation.status == "cancel_requested"


def test_validation_notice_and_agent_history_share_coding_task():
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        row.test_commands = [["python3", "-m", "unittest"]]
        session.commit()
        agent, parent = start(client, row.id, notification_policy={"on_success": True})
        tick(session, "builder")
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
        preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": worktree.branch}}
        finish(session, preparation)
        queue_proposal(session, preparation, worktree)
        proposal = session.get(Run, preparation.metadata_json["coding_run_id"])
        finish(session, proposal)
        assert not session.scalars(select(Notice)).all()
        queue_validation(session, proposal)
        validation = session.get(Run, proposal.metadata_json["validation_run_id"])
        finish(session, validation)
        session.commit()
        notice = session.scalar(select(Notice))
        assert notice.run_id == validation.id and "ready for review" in notice.title
        assert validation.agent_id == agent["id"]
        assert validation.task_id == parent["task_id"]
        assert session.get(Agent, agent["id"]).last_status == "succeeded"


def test_failed_grandchild_retry_is_inspectable_from_notice():
    from app.schedule import retry_view, workflow_source

    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id, retry_policy={"mode": "manual"})
        tick(session, "builder")
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        worktree = session.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
        preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": worktree.branch}}
        finish(session, preparation)
        queue_proposal(session, preparation, worktree)
        proposal = session.get(Run, preparation.metadata_json["coding_run_id"])
        from app.runs import mark_failed

        transition(session, proposal, RunStatus.CLAIMED, event_type="test.claim")
        mark_failed(session, proposal, "LocalCodingFailed", "Confirmed failed completion")
        session.commit()
        source = workflow_source(session, proposal)
        assert source.id == parent["id"]
        assert retry_view(session, source)["allowed"]
        session.commit()
        assert client.get("/api/runs/" + proposal.id).json()["workflow"]["parent_run_id"] == parent["id"]


def test_deadline_heartbeat_requests_owned_run_cancellation(monkeypatch):
    import time
    from types import SimpleNamespace

    from app import heartbeat

    monkeypatch.setattr(
        heartbeat, "get_settings", lambda: SimpleNamespace(heartbeat_seconds=0.02, lease_seconds=30)
    )
    client = TestClient(app)
    with session_factory()() as session:
        row = project(session)
        agent, parent = start(client, row.id)
        tick(session, "builder")
        preparation = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        preparation.parameters = {
            **preparation.parameters,
            "agent_coding_deadline": (utcnow() + timedelta(minutes=1)).isoformat(),
        }
        session.commit()

        class OwnedFake:
            def execute(self, session, run):
                transition(session, run, RunStatus.PREPARING, event_type="test.preparing")
                transition(session, run, RunStatus.RUNNING, event_type="test.running")
                # Exercise expiry while executing, rather than racing the
                # queue's pre-dispatch deadline guard on busy build machines.
                run.parameters = {
                    **run.parameters,
                    "agent_coding_deadline": (utcnow() + timedelta(seconds=0.1)).isoformat(),
                }
                session.commit()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    session.refresh(run)
                    if run.status == "cancel_requested":
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                        return
                    session.commit()
                    time.sleep(0.01)
                raise AssertionError("Deadline heartbeat did not request cancellation")

        assert tick(session, "builder", executors={"worktree_prepare": OwnedFake()}) == preparation.id
        assert session.get(Run, preparation.id).status == "canceled"


def test_factory_keeps_coding_draft_disabled_without_inventing_project():
    response = TestClient(app).post(
        "/api/agents/draft", json={"instruction": "Every day write code for my project"}
    )
    assert response.status_code == 201
    assert response.json()["tools"] == ["coding_local"]
    assert response.json()["enabled"] is False and response.json()["project_id"] is None
