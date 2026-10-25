"""Inline Run now is an exact, durable conversation action, not a detached API call."""

import json
from uuid import uuid4

import pytest
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Agent, ChatProvider, Conversation, Message, Run
from sqlalchemy import select
from test_agent_result_context import followup
from test_conversation_agent_control import enable, result, send, step
from test_conversation_agent_control import saved as saved


def request(saved, **changes):
    api, cid, aid, source = saved
    agent = api.get(f"/api/agents/{aid}").json()
    conversation = api.get(f"/api/chat/conversations/{cid}").json()
    return {
        "client_request_id": str(uuid4()),
        "source_message_id": source["id"],
        "expected_updated_at": agent["updated_at"],
        "expected_settings_version": conversation["settings_version"],
        **changes,
    }


def post(saved, body=None, *, agent_id=None, conversation_id=None):
    api, cid, aid, _ = saved
    return api.post(
        f"/api/chat/conversations/{conversation_id or cid}/agents/{agent_id or aid}/run",
        json=body or request(saved),
    )


def second_agent(saved, monkeypatch):
    api, cid, _, _ = saved

    async def stream(self, **kwargs):
        yield json.dumps({"name": "Another agent", "goal": "Write another report", "tools": []})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    queued = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Create another report agent", "action": "agent.create"},
    )
    assert queued.status_code == 202, queued.text
    for _ in range(5):
        if step() is None:
            break
    messages = api.get(f"/api/chat/conversations/{cid}").json()["messages"]
    source = next(m for m in reversed(messages) if m["metadata"].get("agent_id"))
    return source["metadata"]["agent_id"], source


def test_button_only_queues_existing_controller_and_keeps_chat_mode(saved):
    with session_factory()() as db:
        row = db.get(Conversation, saved[1])
        row.execution_mode = "chat"
        db.scalar(select(ChatProvider)).enabled = False
        db.commit()
    accepted = post(saved)
    assert accepted.status_code == 202, accepted.text
    receipt = accepted.json()
    assert receipt["run"]["executor_type"] == "agent_control"
    assert receipt["run"]["effective_permissions"] == ["manage_agents"]
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))
        user = db.get(Message, receipt["user_message_id"])
        assert user.metadata_json["execution_mode"] == "assistant"
        assert user.metadata_json["agent_control_trigger"] == "button"
        assert user.metadata_json["agent_control"]["selection"] == "exact"
        assert user.metadata_json["agent_control"]["agent_name"] == db.get(Agent, saved[2]).name
        assert db.get(Conversation, saved[1]).execution_mode == "chat"
    assert step() == receipt["run"]["id"]
    done = result(saved, receipt["run"]["id"])
    assert done["metadata"]["agent_control_result"]["outcome"] == "needs_review"


def test_older_clicked_card_targets_its_agent_and_later_stop_refers_to_it(saved, monkeypatch):
    enable(saved, require_approval=True)
    aid2, _ = second_agent(saved, monkeypatch)
    body = request(saved)
    accepted = post(saved, body)
    assert accepted.status_code == 202, accepted.text
    assert step() == accepted.json()["run"]["id"]
    target = result(saved, accepted.json()["run"]["id"])["agent_control_run"]
    assert target["agent_id"] == saved[2] and target["agent_id"] != aid2
    stopped = send(saved, "Stop this agent")
    assert step() == stopped["id"]
    stopped = result(saved, stopped["id"])
    assert stopped["metadata"]["agent_control_result"]["agent_id"] == saved[2]
    assert stopped["agent_control_run"]["id"] == target["id"]
    with session_factory()() as db:
        assert db.get(Run, target["id"]).status == "canceled"
        assert not list(
            db.scalars(select(Run).where(Run.agent_id == aid2, Run.executor_type == "agent_workflow"))
        )


def test_exact_target_survives_a_new_creation_after_send(saved, monkeypatch):
    enable(saved, require_approval=True)
    # Queue the typed request, then insert a separate verified creation before dispatch.
    accepted = post(saved)
    assert accepted.status_code == 202
    with session_factory()() as db:
        from app.events import append_event
        from app.runs import create_run, create_task, transition
        from app.state import RunStatus

        agent = Agent(name="Later agent", goal="Another task", model="fake-local")
        db.add(agent)
        db.flush()
        task = create_task(
            db,
            title="Later creation",
            prompt="Create an agent",
            capability="assistant.orchestrate",
            conversation_id=saved[1],
        )
        root = create_run(
            db,
            task,
            run_type="assistant",
            capability="assistant.orchestrate",
            executor_type="orchestrator",
            permissions=["manage_agents"],
            metadata={"plan": {"action": "agent.create"}},
        )
        for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED):
            transition(db, root, state, event_type="test.transition")
        append_event(db, root.id, "agent.draft.created", {"agent_id": agent.id})
        db.add(
            Message(
                conversation_id=saved[1],
                role="assistant",
                run_id=root.id,
                content="Later draft",
                metadata_json={"agent_id": agent.id},
            )
        )
        db.commit()
    assert step() == accepted.json()["run"]["id"]
    assert result(saved, accepted.json()["run"]["id"])["agent_control_run"]["agent_id"] == saved[2]


def test_receipt_replays_before_idle_and_source_checks_without_duplicate_work(saved):
    enable(saved, require_approval=True)
    body = request(saved)
    first = post(saved, body)
    assert first.status_code == 202
    replay = post(saved, body)
    assert replay.status_code == 202 and replay.json()["run"]["id"] == first.json()["run"]["id"]
    step()
    replay = post(saved, body)
    assert replay.status_code == 202 and replay.json()["run"]["id"] == first.json()["run"]["id"]
    assert post(saved, {**body, "source_message_id": str(uuid4())}).status_code == 409
    with session_factory()() as db:
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))) == 1
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1
    ordinary = saved[0].post(
        "/api/chat/turns",
        json={
            "client_request_id": body["client_request_id"],
            "conversation_id": saved[1],
            "expected_settings_version": 1,
            "content": "Hello",
        },
    )
    assert ordinary.status_code == 409


@pytest.mark.parametrize(
    "problem", ["definition", "settings", "source", "agent", "foreign", "archived", "permission"]
)
def test_http_rejects_stale_or_unrelated_card_before_queueing(saved, problem):
    body = request(saved)
    kwargs = {}
    if problem == "definition":
        with session_factory()() as db:
            db.get(Agent, saved[2]).updated_at = utcnow()
            db.commit()
    elif problem == "settings":
        body["expected_settings_version"] += 1
    elif problem == "source":
        body["source_message_id"] = str(uuid4())
    elif problem == "agent":
        kwargs["agent_id"] = str(uuid4())
    elif problem == "foreign":
        with session_factory()() as db:
            other = Conversation(model="fake-local", execution_mode="work")
            db.add(other)
            db.commit()
            kwargs["conversation_id"] = other.id
    elif problem == "archived":
        with session_factory()() as db:
            db.get(Conversation, saved[1]).archived_at = utcnow()
            db.commit()
    else:
        with session_factory()() as db:
            db.get(Run, saved[3]["run_id"]).effective_permissions = []
            db.commit()
    response = post(saved, body, **kwargs)
    assert response.status_code == 409, response.text
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_control")))


def test_worker_still_rechecks_exact_source_after_api_acceptance(saved):
    enable(saved, require_approval=True)
    accepted = post(saved)
    assert accepted.status_code == 202
    with session_factory()() as db:
        source = db.get(Message, saved[3]["id"])
        source.metadata_json = {**source.metadata_json, "agent_id": str(uuid4())}
        db.commit()
    step()
    with session_factory()() as db:
        assert db.get(Run, accepted.json()["run"]["id"]).status == "failed"
        assert not list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))


def test_button_report_is_available_to_a_normal_followup_without_reexecution(saved, monkeypatch):
    enable(saved)
    accepted = post(saved)
    assert accepted.status_code == 202
    step()

    async def stream(self, **kwargs):
        yield "ButtonReport total:42."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    for _ in range(10):
        if step() is None:
            break
    followup(saved)
    step()
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
        assert "ButtonReport total:42." in str(reply.parameters["messages"])
        assert len(reply.parameters["agent_result_sources"]) == 1
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


def test_control_receipt_cannot_be_regenerated_as_a_model_reply(saved):
    accepted = post(saved)
    assert accepted.status_code == 202
    step()
    response = saved[0].post(f"/api/chat/conversations/{saved[1]}/regenerate")
    assert response.status_code == 409 and "new instruction" in response.text


def test_stale_controller_stop_reaches_only_its_published_workflow(saved):
    enable(saved, require_approval=True)
    accepted = post(saved).json()
    step()
    workflow = result(saved, accepted["run"]["id"])["agent_control_run"]
    stopped = saved[0].post(f"/api/chat/conversations/{saved[1]}/tasks/{accepted['task_id']}/cancel")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["agent_task_ids"] == [workflow["task_id"]]
    with session_factory()() as db:
        assert db.get(Run, workflow["id"]).status == "canceled"
        assert db.get(Run, workflow["id"]).task.metadata_json["stop_requested_at"]


def test_canceling_a_busy_receipt_does_not_stop_another_controllers_job(saved):
    enable(saved, require_approval=True)
    first = post(saved).json()
    step()
    workflow = result(saved, first["run"]["id"])["agent_control_run"]
    second = post(saved).json()
    step()
    assert (
        result(saved, second["run"]["id"])["metadata"]["agent_control_result"]["outcome"] == "already_running"
    )
    stopped = saved[0].post(f"/api/chat/conversations/{saved[1]}/tasks/{second['task_id']}/cancel")
    assert stopped.status_code == 200 and not stopped.json().get("agent_task_ids")
    with session_factory()() as db:
        assert db.get(Run, workflow["id"]).status == "waiting_for_approval"
        assert not db.get(Run, workflow["id"]).task.metadata_json.get("stop_requested_at")


def test_stale_stop_leaves_an_already_finished_result_readable(saved, monkeypatch):
    enable(saved)
    accepted = post(saved).json()
    step()

    async def stream(self, **kwargs):
        yield "Finished result preserved."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    for _ in range(10):
        if step() is None:
            break
    workflow = result(saved, accepted["run"]["id"])["agent_control_run"]
    assert workflow["status"] == "succeeded"
    stopped = saved[0].post(f"/api/chat/conversations/{saved[1]}/tasks/{accepted['task_id']}/cancel")
    assert stopped.status_code == 200 and not stopped.json().get("agent_task_ids")
    with session_factory()() as db:
        assert not db.get(Run, workflow["id"]).task.metadata_json.get("stop_requested_at")
    followup(saved)
    step()
    with session_factory()() as db:
        reply = db.scalar(select(Run).where(Run.executor_type == "chat"))
        assert "Finished result preserved." in str(reply.parameters["messages"])


def test_unverified_controller_link_never_signals_the_agent_workflow(saved):
    enable(saved, require_approval=True)
    accepted = post(saved).json()
    step()
    workflow = result(saved, accepted["run"]["id"])["agent_control_run"]
    with session_factory()() as db:
        root = db.get(Run, workflow["id"])
        root.metadata_json = {**root.metadata_json, "conversation_control_run_id": str(uuid4())}
        db.commit()
    stopped = saved[0].post(f"/api/chat/conversations/{saved[1]}/tasks/{accepted['task_id']}/cancel")
    assert stopped.status_code == 200 and not stopped.json().get("agent_task_ids")
    with session_factory()() as db:
        assert db.get(Run, workflow["id"]).status == "waiting_for_approval"


def test_actual_factory_creation_remains_valid_without_optional_planner_annotation(saved):
    with session_factory()() as db:
        root = db.get(Run, saved[3]["run_id"])
        root.metadata_json = {key: value for key, value in root.metadata_json.items() if key != "plan"}
        db.commit()
    accepted = post(saved)
    assert accepted.status_code == 202, accepted.text
    step()
    assert (
        result(saved, accepted.json()["run"]["id"])["metadata"]["agent_control_result"]["outcome"]
        == "needs_review"
    )
