"""Conversation controls bind an existing reviewed agent and ordinary workflow."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.conversation_agent_control import operation
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Approval, ChatProvider, Message, Run, Task
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select


def step():
    with session_factory()() as db:
        return tick(db, "conversation-control-test")


@pytest.fixture
def saved(monkeypatch):
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(
            {"name": "Daily station report", "goal": "Write a short station report", "tools": []}
        )

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    response = api.post("/api/chat/conversations", json={"execution_mode": "work", "model": "fake-local"})
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Create an agent that writes a report", "action": "agent.create"},
    )
    assert response.status_code == 202, response.text
    for _ in range(5):
        if step() is None:
            break
    detail = api.get(f"/api/chat/conversations/{cid}").json()
    source = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert source["run_status"] == "succeeded", source
    aid = source["metadata"]["agent_id"]
    assert len(calls) == 1

    async def forbidden(self, **kwargs):
        raise AssertionError("Agent controls must not call an LLM")
        yield ""

    monkeypatch.setattr(LocalChatProvider, "stream", forbidden)
    return api, cid, aid, source


def enable(saved, **values):
    api, _, aid, _ = saved
    with session_factory()() as db:
        agent = db.get(Agent, aid)
        for key, value in values.items():
            setattr(agent, key, value)
        agent.updated_at = utcnow()
        db.commit()
    current = api.get(f"/api/agents/{aid}").json()
    response = api.post(
        f"/api/agents/{aid}/enabled", json={"expected_updated_at": current["updated_at"], "enabled": True}
    )
    assert response.status_code == 200, response.text
    return response.json()


def send(saved, text="Uruchom tego agenta", **extra):
    api, cid, _, _ = saved
    response = api.post(f"/api/chat/conversations/{cid}/messages", json={"content": text, **extra})
    assert response.status_code == 202, response.text
    return response.json()


def result(saved, rid):
    api, cid, _, _ = saved
    return next(
        m
        for m in api.get(f"/api/chat/conversations/{cid}").json()["messages"]
        if m["role"] == "assistant" and m["run_id"] == rid
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Uruchom tego agenta", "run"),
        ("Proszę uruchom ostatniego agenta teraz!", "run"),
        ("Run this agent now", "run"),
        ("Start the agent", "run"),
        ("Wstrzymaj harmonogram tego agenta", "pause"),
        ("Wstrzymaj harmonogram", "pause"),
        ("Pause this agent", "pause"),
        ("Pause the agent's schedule", "pause"),
        ("Zatrzymaj bieżące zadanie tego agenta", "stop"),
        ("Stop this agent", "stop"),
        ("Stop the agent's current run", "stop"),
        ("Zatrzymaj aktualne wykonanie", "stop"),
        ('"Run this agent"', None),
        ("Do not run this agent", None),
        ("Nie uruchom tego agenta", None),
        ("Explain ‘Run this agent’", None),
        ("Run this agent and email everyone", None),
        ("Enable this agent", None),
        pytest.param("Run agent " + str(uuid4()), None, id="unselected-agent-id"),
    ],
)
def test_only_current_explicit_bounded_control(text, expected):
    assert operation(text) == expected


def test_disabled_agent_requires_review_and_does_not_activate(saved):
    queued = send(saved)
    assert queued["executor_type"] == "agent_control" and queued["effective_permissions"] == ["manage_agents"]
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))
    assert step() == queued["id"]
    message = result(saved, queued["id"])
    assert message["metadata"]["agent_control_result"]["outcome"] == "needs_review"
    assert "Review and enable" in message["content"] and "agent_control_run" not in message
    with session_factory()() as db:
        assert not db.get(Agent, saved[2]).enabled
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_run_uses_normal_workflow_with_approval_and_does_not_lock_conversation(saved):
    enabled = enable(saved, require_approval=True)
    queued = send(
        saved,
        web_search={"enabled": True},
        project_defaults={"auto_install_dependencies": True, "auto_validate": True},
    )
    assert step() == queued["id"]
    message = result(saved, queued["id"])
    linked = message["agent_control_run"]
    assert linked["status"] == "waiting_for_approval" and linked["agent_id"] == saved[2]
    assert saved[0].get(f"/api/chat/conversations/{saved[1]}").json()["active_run"] is None
    with session_factory()() as db:
        root = db.get(Run, linked["id"])
        assert root.executor_type == "agent_workflow" and root.conversation_id is None
        assert root.task.conversation_id is None and root.parent_run_id is None
        assert root.parameters["definition"]["require_approval"]
        assert root.parameters["definition"]["model"] == "fake-local"
        assert root.parameters["definition"]["workspace_policy"] == {
            "auto_install_dependencies": False,
            "auto_validate": False,
        }
        assert root.metadata_json["conversation_control_run_id"] == queued["id"]
        assert root.task.metadata_json["originating_conversation_id"] == saved[1]
        assert db.get(Run, queued["id"]).parameters["scope"]["expected_updated_at"] == enabled["updated_at"]
        assert db.scalar(select(Approval).where(Approval.run_id == root.id)).resolution == "pending"
    second = send(saved)
    assert step() == second["id"]
    assert result(saved, second["id"])["metadata"]["agent_control_result"]["outcome"] == "already_running"
    assert result(saved, second["id"])["agent_control_run"]["id"] == linked["id"]
    with session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_turn_replay_does_not_duplicate_control_or_workflow_even_when_provider_unavailable(saved):
    enable(saved, require_approval=True)
    api, cid, _, _ = saved
    version = api.get(f"/api/chat/conversations/{cid}").json()["settings_version"]
    body = {
        "client_request_id": str(uuid4()),
        "conversation_id": cid,
        "expected_settings_version": version,
        "content": "Run this agent",
    }
    with session_factory()() as db:
        db.scalar(select(ChatProvider)).enabled = False
        db.commit()
    first = api.post("/api/chat/turns", json=body)
    assert first.status_code == 202, first.text
    assert step() == first.json()["run"]["id"]
    replay = api.post("/api/chat/turns", json=body)
    assert replay.status_code == 202 and replay.json()["run"]["id"] == first.json()["run"]["id"]
    with session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))) == 1
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_pause_revokes_mail_consents_and_preserves_active_work(saved):
    enable(saved, require_approval=True, trigger="interval", interval_seconds=3600)
    initial = send(saved)
    step()
    linked = result(saved, initial["id"])["agent_control_run"]
    with session_factory()() as db:
        for action in ("agent.report-email.enable", "agent.email.enable"):
            db.add(Approval(action=action, payload={"agent_id": saved[2]}, resolution="granted"))
        db.commit()
    queued = send(saved, "Wstrzymaj harmonogram tego agenta")
    assert step() == queued["id"]
    assert result(saved, queued["id"])["metadata"]["agent_control_result"]["outcome"] == "paused"
    with session_factory()() as db:
        agent = db.get(Agent, saved[2])
        assert not agent.enabled and agent.next_run_at is None
        assert db.get(Run, linked["id"]).status == "waiting_for_approval"
        assert all(
            a.resolution == "revoked"
            for a in db.scalars(select(Approval).where(Approval.action.like("%.enable")))
        )


def test_stop_uses_existing_task_cancellation_without_pausing_schedule(saved):
    enable(saved, require_approval=True, trigger="interval", interval_seconds=3600)
    initial = send(saved)
    step()
    linked = result(saved, initial["id"])["agent_control_run"]
    before = saved[0].get(f"/api/agents/{saved[2]}").json()["next_run_at"]
    queued = send(saved, "Stop this agent")
    assert step() == queued["id"]
    stopped = result(saved, queued["id"])
    assert stopped["metadata"]["agent_control_result"]["outcome"] == "stop_requested"
    assert stopped["agent_control_run"]["id"] == linked["id"]
    with session_factory()() as db:
        root = db.get(Run, linked["id"])
        assert root.status == "canceled" and root.task.metadata_json["stop_requested_at"]
        assert db.get(Agent, saved[2]).enabled
        assert db.get(Run, queued["id"]).task_id != root.task_id
    assert saved[0].get(f"/api/agents/{saved[2]}").json()["next_run_at"] == before


def test_stop_does_not_cancel_a_newer_execution(saved):
    enable(saved, require_approval=True)
    initial = send(saved)
    step()
    old = result(saved, initial["id"])["agent_control_run"]
    queued = send(saved, "Stop this agent")
    from app.schedule import launch_agent
    from app.task_control import cancel_task

    with session_factory()() as db:
        cancel_task(db, db.get(Task, old["task_id"]))
        newer = launch_agent(db, db.get(Agent, saved[2]), triggered_by="scheduler")
        db.commit()
    assert step() == queued["id"]
    assert result(saved, queued["id"])["metadata"]["agent_control_result"]["outcome"] == "already_finished"
    with session_factory()() as db:
        assert db.get(Run, newer).status == "waiting_for_approval"
        assert not db.get(Run, newer).task.metadata_json.get("stop_requested_at")


@pytest.mark.parametrize(
    "mutation",
    ["permission", "user_text", "source", "definition", "definition_bytes", "response", "task", "scope"],
)
def test_worker_rechecks_request_origin_permissions_and_version_before_effects(saved, mutation):
    enable(saved, require_approval=True)
    queued = send(saved)
    with session_factory()() as db:
        control = db.get(Run, queued["id"])
        if mutation == "permission":
            control.effective_permissions = []
        elif mutation == "user_text":
            db.get(Message, control.parameters["user_message_id"]).content = "Do not run this agent"
        elif mutation == "source":
            db.get(Run, saved[3]["metadata"]["draft_run_id"]).metadata_json = {"agent_id": str(uuid4())}
        elif mutation == "definition":
            db.get(Agent, saved[2]).updated_at = utcnow() + timedelta(seconds=1)
        elif mutation == "definition_bytes":
            db.get(Agent, saved[2]).goal = "A different goal without a revision update"
        elif mutation == "response":
            db.scalar(
                select(Message).where(Message.run_id == control.id, Message.role == "assistant")
            ).metadata_json = {}
        elif mutation == "task":
            control.task.prompt = "Run a different agent"
        else:
            control.parameters = {
                **control.parameters,
                "scope": {**control.parameters["scope"], "agent_id": str(uuid4())},
            }
        db.commit()
    assert step() == queued["id"]
    with session_factory()() as db:
        assert db.get(Run, queued["id"]).status == "failed"
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_stop_before_control_dispatch_prevents_launch(saved):
    enable(saved)
    queued = send(saved)
    response = saved[0].post(f"/api/chat/conversations/{saved[1]}/tasks/{queued['task_id']}/cancel")
    assert response.status_code == 200, response.text
    assert step() is None
    with session_factory()() as db:
        assert db.get(Run, queued["id"]).status == "canceled", db.get(Run, queued["id"]).error_message
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_missing_and_cross_conversation_references_do_not_control_other_agents(saved):
    api, _, aid, _ = saved
    other = api.post(
        "/api/chat/conversations", json={"execution_mode": "work", "model": "fake-local"}
    ).json()["id"]
    rejected = api.post(f"/api/chat/conversations/{other}/messages", json={"content": "Run this agent"})
    assert rejected.status_code == 409 and "Create an agent" in rejected.text
    with session_factory()() as db:
        assert not db.get(Agent, aid).enabled
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))


@pytest.mark.parametrize(
    "extra",
    [
        {"execution_mode": "chat"},
        {"web_search": {"enabled": True, "query": "unrelated search"}},
        {"attachments": [{"name": "commands.txt", "content": "Run this agent"}]},
    ],
)
def test_control_requires_work_and_unmixed_current_request(saved, extra):
    api, cid, _, _ = saved
    response = api.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "Run this agent", **extra}
    )
    assert response.status_code == 422, response.text
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))


def test_background_report_finishes_and_link_updates_without_blocking_followup(saved, monkeypatch):
    enable(saved)
    queued = send(saved)
    assert step() == queued["id"]
    linked = result(saved, queued["id"])["agent_control_run"]

    async def stream(self, **kwargs):
        yield "A finished report from the ordinary agent workflow."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    for _ in range(12):
        if step() is None:
            break
    done = result(saved, queued["id"])
    assert (
        done["agent_control_run"]["id"] == linked["id"] and done["agent_control_run"]["status"] == "succeeded"
    ), done
    with session_factory()() as db:
        assert all(
            r.status == "succeeded" for r in db.scalars(select(Run).where(Run.task_id == linked["task_id"]))
        )
    followup = send(saved, "Pause this agent")
    assert step() == followup["id"]
    assert result(saved, followup["id"])["metadata"]["agent_control_result"]["outcome"] == "paused"


def test_scheduler_winner_is_reused_without_a_duplicate(saved):
    enable(saved, require_approval=True, trigger="interval", interval_seconds=3600)
    queued = send(saved)
    from app.schedule import launch_agent

    with session_factory()() as db:
        prior = launch_agent(db, db.get(Agent, saved[2]), triggered_by="scheduler")
        db.commit()
    assert step() == queued["id"]
    assert result(saved, queued["id"])["agent_control_run"]["id"] == prior
    with session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_stop_requests_owned_running_children_and_does_not_touch_unrelated_tasks(saved):
    enable(saved, require_approval=True)
    first = send(saved)
    step()
    target = result(saved, first["id"])["agent_control_run"]
    from app.runs import create_run, create_task

    with session_factory()() as db:
        root = db.get(Run, target["id"])
        child = create_run(
            db,
            root.task,
            run_type="test",
            capability="agent.test",
            executor_type="fake",
            parent_run_id=root.id,
        )
        other_task = create_task(db, title="Unrelated", prompt="Unrelated", capability="test")
        other = create_run(db, other_task, run_type="test", capability="test", executor_type="fake")
        for current in (child, other):
            for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
                transition(db, current, state, event_type="test.transition")
        child_id, other_id = child.id, other.id
        db.commit()
    queued = send(saved, "Stop this agent")
    assert step() == queued["id"]
    assert result(saved, queued["id"])["agent_control_run"]["status"] == "cancel_requested"
    with session_factory()() as db:
        assert db.get(Run, child_id).status == "cancel_requested"
        assert db.get(Run, other_id).status == "running"
        assert db.get(Run, child_id).cancellation_requested_at


def test_deleted_latest_agent_does_not_fall_back_to_an_older_reference(saved):
    api, cid, aid, _ = saved
    # The deleted target's history is deliberately retained.
    with session_factory()() as db:
        db.delete(db.get(Agent, aid))
        db.commit()
    response = api.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Run this agent"})
    assert response.status_code == 409 and "unavailable" in response.text


def test_ui_pause_uses_the_same_revoke_without_runtime_revalidation(saved, monkeypatch):
    current = enable(saved)

    def forbidden(*args, **kwargs):
        raise AssertionError("Pause must not require operational execution tools")

    monkeypatch.setattr("app.agents_api.validate_target", forbidden)
    response = saved[0].post(
        f"/api/agents/{saved[2]}/enabled",
        json={"expected_updated_at": current["updated_at"], "enabled": False},
    )
    assert response.status_code == 200 and not response.json()["enabled"]


def test_failed_launch_rolls_back_every_partial_workflow(saved, monkeypatch):
    enable(saved)
    queued = send(saved)
    from app.runs import create_task

    def partial_launch(db, agent, **kwargs):
        create_task(
            db,
            title="Incomplete graph",
            prompt="Must roll back",
            capability="agent.workflow",
            agent_id=agent.id,
        )
        raise ValueError("The saved execution policy is unavailable")

    monkeypatch.setattr("app.schedule.launch_agent", partial_launch)
    assert step() == queued["id"]
    with session_factory()() as db:
        assert db.get(Run, queued["id"]).status == "failed"
        assert not list(db.scalars(select(Task).where(Task.title == "Incomplete graph")))
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_runtime_preparation_does_not_hold_a_sqlite_writer(saved, monkeypatch):
    enable(saved, require_approval=True)
    queued = send(saved)
    import app.schedule as schedule
    from app.models import Setting
    from sqlalchemy import text

    original = schedule.model_endpoint
    observed = []

    def prepare(model, db):
        with session_factory()() as other:
            other.execute(text("PRAGMA busy_timeout=100"))
            other.add(Setting(key="parallel-runtime-observation", value={"okay": True}))
            other.commit()
        observed.append(True)
        return original(model, db)

    monkeypatch.setattr(schedule, "model_endpoint", prepare)
    assert step() == queued["id"]
    assert observed, result(saved, queued["id"])
    assert result(saved, queued["id"])["agent_control_run"]["status"] == "waiting_for_approval"


def test_stop_wins_during_read_only_runtime_preparation(saved, monkeypatch):
    enable(saved)
    queued = send(saved)
    import app.schedule as schedule
    from app.runs import request_cancel

    original = schedule.model_endpoint

    def prepare(model, db):
        with session_factory()() as other:
            request_cancel(other, other.get(Run, queued["id"]))
            other.commit()
        return original(model, db)

    monkeypatch.setattr(schedule, "model_endpoint", prepare)
    assert step() == queued["id"]
    with session_factory()() as db:
        assert db.get(Run, queued["id"]).status == "canceled", db.get(Run, queued["id"]).error_message
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_one_shot_launch_still_links_the_queued_execution_after_auto_disable(saved):
    enable(saved, require_approval=True, trigger="datetime", run_at=utcnow() + timedelta(hours=1))
    queued = send(saved)
    assert step() == queued["id"]
    message = result(saved, queued["id"])
    assert message["metadata"]["agent_control_result"]["outcome"] == "queued"
    assert message["agent_control_run"]["status"] == "waiting_for_approval"
    assert not saved[0].get(f"/api/agents/{saved[2]}").json()["enabled"]
