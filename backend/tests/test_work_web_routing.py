"""Default Web availability must not consume a Work action or grant its tools."""

import json

import pytest
from app import web_search
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def model(monkeypatch):
    calls = []

    async def stream(_self, **params):
        calls.append(params)
        if params["messages"][0]["content"].startswith("Route the user's request"):
            yield json.dumps({"action": "agent.create", "reason": "Prepare a disabled agent for review."})
        else:
            yield json.dumps(
                {
                    "name": "Workstation report",
                    "goal": "Report current workstation GPU and RAM use.",
                    "tools": ["system_snapshot"],
                    "trigger": "manual",
                }
            )

    async def no_search(_query):
        pytest.fail("Creating a draft must not search the user's request")

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    monkeypatch.setattr(web_search, "search", no_search)
    return calls


def work():
    with session_factory()() as session:
        return tick(session, "work-web-test")


@pytest.mark.parametrize(
    "content",
    [
        "Create an agent that reports workstation GPU and RAM use",
        "Could you prepare an agent for me to report workstation GPU and RAM use?",
        "Chciałbym mieć agenta, który opisuje aktualne użycie GPU i RAM mojej stacji.",
    ],
)
def test_default_web_does_not_block_a_reviewable_agent_draft(model, content):
    with TestClient(app) as client:
        conversation = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        route = f"/api/chat/conversations/{conversation['id']}"
        sent = client.post(
            route + "/messages",
            json={
                "content": content,
                "execution_mode": "work",
                "project_defaults": {"auto_install_dependencies": True, "auto_validate": True},
                "web_search": {"enabled": True},
            },
        )
        assert sent.status_code == 202, sent.text
        root = sent.json()
        assert work() == root["id"]
        with session_factory()() as session:
            planner = session.get(Run, root["id"])
            child = session.get(Run, planner.metadata_json.get("child_run_id"))
            assert child is not None and child.executor_type == "agent_draft"
            assert child.task_id == planner.task_id and child.parent_run_id == planner.id
        assert work() == child.id
        with session_factory()() as session:
            agents = list(session.scalars(select(Agent)))
            assert len(agents) == 1 and not agents[0].enabled and agents[0].next_run_at is None
            assert agents[0].tools == ["system_snapshot"]
        assert client.get("/api/chat/preferences").json()["web_search_enabled"] is True


@pytest.mark.parametrize("mode", ["chat", "work", "orchestrator"])
def test_selected_chat_retains_search_instead_of_creating_an_agent(model, mode):
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": mode}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={"content": "Create an agent for me", "action": "chat", "web_search": {"enabled": True}},
        )
        assert sent.status_code == 202
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            child = session.get(Run, root.metadata_json["child_run_id"])
            assert child.executor_type == "chat" and child.parameters["web_search"]["enabled"]
            assert not list(session.scalars(select(Agent)))
        assert not model  # Queueing ordinary chat does not invoke the planner.


@pytest.mark.parametrize("mode", ["work", "orchestrator"])
def test_workstation_inspection_does_not_need_a_model_or_search(model, mode):
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": mode}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={"content": "Show current GPU and RAM use", "web_search": {"enabled": True}},
        )
        assert sent.status_code == 202, sent.text
        assert "endpoint" not in sent.json()["parameters"]
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            child = session.get(Run, root.metadata_json["child_run_id"])
            assert child.executor_type == "station_snapshot" and not root.parameters["web_search"]["enabled"]
        assert not model


@pytest.mark.parametrize(
    "scope", [{"enabled": True, "query": "my explicit public query"}, {"enabled": True, "render_pages": True}]
)
def test_explicit_research_is_never_dropped_for_a_work_action(model, scope):
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={"content": "Create an agent for a workstation report", "web_search": scope},
        )
        assert sent.status_code == 202, sent.text
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            assert root.status == "succeeded" and "child_run_id" not in root.metadata_json
            assert root.metadata_json["plan"]["action"] == "clarify"
            assert root.parameters["web_search"]["enabled"]
        assert not model


@pytest.mark.parametrize("mode", ["chat", "work", "orchestrator"])
def test_ambiguous_work_image_preflights_the_planner_even_with_default_web(mode):
    from uuid import uuid4

    from app.assistant import assistant_needs_provider
    from app.chat import MessageBody
    from app.work_web_policy import prepare_turn

    body = MessageBody(
        content="How many shapes are visible?", image_artifact_ids=[uuid4()], web_search={"enabled": True}
    )
    prepared = prepare_turn(body, mode)
    assert assistant_needs_provider(prepared) is (mode != "chat")


@pytest.mark.parametrize("action", ["runtime.stop", "runtime.load", "coding.commit", "coding.publish"])
def test_model_plan_cannot_invent_sensitive_authority(model, monkeypatch, action):
    async def stream(_self, **_params):
        yield json.dumps({"action": action, "reason": "Attempt without an approved form"})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={"content": "Could you help me with a task?", "web_search": {"enabled": True}},
        )
        assert sent.status_code == 202, sent.text
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            assert "child_run_id" not in root.metadata_json
            assert len(list(session.scalars(select(Run)))) == 1
            assert "manage_models" not in root.effective_permissions


def test_default_web_does_not_block_an_explicit_new_project_scope(model, monkeypatch):
    monkeypatch.setattr(
        "app.coding_model_routing.select_coding_model", lambda _session: {"model": "qualified-fixture"}
    )
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={
                "content": "Build a local weather website",
                "new_project": {"name": "Weather"},
                "web_search": {"enabled": True},
            },
        )
        assert sent.status_code == 202, sent.text
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            child = session.get(Run, root.metadata_json["child_run_id"])
            assert child.executor_type == "project_setup" and not root.parameters["web_search"]["enabled"]
        assert not model


def test_planning_uses_plain_history_and_skips_legacy_expanded_attachments():
    from datetime import timedelta

    from app.assistant import planner_context
    from app.db import utcnow
    from app.models import Conversation, Message

    with session_factory()() as session:
        row = Conversation(model="fake-local")
        session.add(row)
        session.flush()
        now = utcnow()
        session.add_all(
            [
                Message(
                    conversation_id=row.id,
                    role="user",
                    content="PRIVATE_EXPANDED_FILE_BODY",
                    metadata_json={
                        "user_text": "My actual instruction",
                        "attachments": [{"name": "secret.txt"}],
                    },
                    created_at=now - timedelta(seconds=2),
                ),
                Message(
                    conversation_id=row.id,
                    role="user",
                    content="LEGACY_PRIVATE_BODY",
                    metadata_json={"attachments": [{"name": "old.txt"}]},
                    created_at=now - timedelta(seconds=1),
                ),
            ]
        )
        current = Message(
            conversation_id=row.id,
            role="user",
            content="x" * 32000,
            metadata_json={"user_text": "Could you help me?"},
            created_at=now,
        )
        session.add(current)
        session.flush()
        context = planner_context(session, row, current)
        assert context == [{"role": "user", "content": "My actual instruction"}]


def test_stop_during_default_web_planning_closes_the_stream_without_a_draft(model, monkeypatch):
    from app.runs import request_cancel

    closed = []

    async def stream(_self, **_params):
        try:
            with session_factory()() as session:
                root = session.scalar(select(Run).where(Run.executor_type == "orchestrator"))
                request_cancel(session, root)
                session.commit()
            yield '{"action":"agent.create","reason":"Prepare a draft"}'
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={
                "content": "Could you prepare an agent for workstation monitoring?",
                "web_search": {"enabled": True},
            },
        )
        assert sent.status_code == 202
        work()
        with session_factory()() as session:
            runs = list(session.scalars(select(Run)))
            assert len(runs) == 1 and runs[0].status == "canceled"
            assert not list(session.scalars(select(Agent)))
        assert closed


def test_chat_mode_does_not_gain_agent_authority_from_default_web(model):
    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "chat"}
        ).json()
        sent = client.post(
            f"/api/chat/conversations/{row['id']}/messages",
            json={"content": "Create an agent for a workstation report", "web_search": {"enabled": True}},
        )
        assert sent.status_code == 202
        work()
        with session_factory()() as session:
            root = session.get(Run, sent.json()["id"])
            assert root.metadata_json["plan"]["action"] == "clarify"
            assert "child_run_id" not in root.metadata_json and not list(session.scalars(select(Agent)))
        assert not model


def test_default_web_work_receipt_replays_one_disabled_draft_without_search(model):
    from uuid import uuid4

    from app.models import RunEvent

    with TestClient(app) as client:
        row = client.post(
            "/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}
        ).json()
        body = {
            "client_request_id": str(uuid4()),
            "conversation_id": row["id"],
            "expected_settings_version": row["settings_version"],
            "content": "Could you prepare an agent for a workstation report?",
            "execution_mode": "work",
            "web_search": {"enabled": True},
        }
        first = client.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        rid = first.json()["run"]["id"]
        assert client.post("/api/chat/turns", json=body).json()["run"]["id"] == rid
        assert work() == rid
        work()
        assert client.post("/api/chat/turns", json=body).json()["run"]["id"] == rid
        conflict = client.post(
            "/api/chat/turns",
            json={**body, "web_search": {"enabled": True, "query": "different explicit scope"}},
        )
        assert conflict.status_code == 409
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run)))) == 2
            agents = list(session.scalars(select(Agent)))
            assert len(agents) == 1 and not agents[0].enabled
            events = list(
                session.scalars(
                    select(RunEvent).where(
                        RunEvent.run_id == rid, RunEvent.event_type == "web_search.not_used"
                    )
                )
            )
            assert len(events) == 1
