"""Explicit conversation references create source-bound disabled agent drafts."""

import json

import pytest
from app.api import app
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_data import drain, start
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_completed_analysis_can_become_a_disabled_repeat_agent_with_its_original_inputs(
    data_environment, monkeypatch
):
    api = TestClient(app)
    cid, original = start(api, data_environment, mode="work")
    drain()
    calls = []

    async def draft(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps({"name": "Daily sales", "trigger": "interval", "interval_seconds": 300})

    monkeypatch.setattr(LocalChatProvider, "stream", draft)
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Create an agent that repeats this analysis every five minutes.",
            "execution_mode": "work",
        },
    )
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as s:
        agents = list(s.scalars(select(Agent)))
        assert len(agents) == 1, [
            (r.executor_type, r.status, r.error_message)
            for r in s.scalars(select(Run).where(Run.task_id == response.json()["task_id"]))
        ]
        agent = agents[0]
        assert not agent.enabled and agent.next_run_at is None
        assert agent.tools == ["python_data"] and agent.model == data_environment["model"]
        assert agent.goal == "Calculate the total in the selected file."
        assert agent.data["input_artifact_ids"] == original["parameters"]["data"]["input_artifact_ids"]
        assert agent.project_id is None and agent.interval_seconds == 300
        prepared = s.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert prepared.status == "succeeded", prepared.error_message
        assert prepared.parameters["data_agent_source"]["source_run_id"] == original["id"]
        assert prepared.effective_permissions == ["manage_agents"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Create an agent that repeats this analysis every morning.",
        "Please create a daily agent from this analysis.",
        "Stwórz mi agenta, który powtarza tę analizę codziennie rano.",
        "Zapisz tę analizę jako agenta.",
    ],
)
def test_explicit_analysis_agent_requests(text):
    from app.data_agent_draft import requested

    assert requested(text)


@pytest.mark.parametrize(
    "text",
    [
        'Explain "Create an agent from this analysis"',
        '"Create an agent from this analysis"',
        "> Create an agent from this analysis",
        "Do not create an agent from this analysis",
        "Create an image of an agent from this analysis",
        "Create a chart from this analysis",
        "Create an agent that checks prices",
    ],
)
def test_quotes_negation_other_actions_and_unrelated_agents_do_not_inherit_sources(text):
    from app.data_agent_draft import requested

    assert not requested(text)


def setup_repeat(api, state, monkeypatch, stream):
    cid, original = start(api, state, mode="work")
    drain()
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Create an agent that repeats this analysis every five minutes.",
            "execution_mode": "work",
            "project_defaults": {"auto_install_dependencies": True, "auto_validate": True},
        },
    )
    assert response.status_code == 202, response.text
    return cid, original, response.json()


def proposal():
    return {"name": "Repeated analysis", "trigger": "interval", "interval_seconds": 300}


def test_saved_agent_executes_in_its_own_workspace_without_inheriting_work_defaults(
    data_environment, monkeypatch
):
    original_stream = LocalChatProvider.stream

    async def stream(self, **kwargs):
        yield json.dumps(proposal())

    api = TestClient(app)
    _, source, created = setup_repeat(api, data_environment, monkeypatch, stream)
    drain()
    root = api.get("/api/runs/" + created["id"]).json()
    assert root["parameters"]["project_defaults"] is None
    with session_factory()() as s:
        agent = s.scalar(select(Agent))
        aid = agent.id
        assert not any(agent.workspace_policy.values())
    saved = api.get("/api/agents/" + aid).json()
    enable = api.post(
        f"/api/agents/{aid}/enabled", json={"enabled": True, "expected_updated_at": saved["updated_at"]}
    )
    assert enable.status_code == 200, enable.text
    monkeypatch.setattr(LocalChatProvider, "stream", original_stream)
    queued = api.post(f"/api/agents/{aid}/run", json={"expected_updated_at": enable.json()["updated_at"]})
    assert queued.status_code == 202, queued.text
    drain()
    with session_factory()() as s:
        runs = list(s.scalars(select(Run).where(Run.task_id == queued.json()["task_id"])))
        assert all(r.status == "succeeded" for r in runs), [
            (r.executor_type, r.status, r.error_message) for r in runs
        ]
        original = s.get(Run, source["id"])
        final = next(r for r in runs if r.executor_type == "agent_data_result")
        assert final.agent_id == aid and final.project_id != original.project_id
        assert final.metadata_json["data_result"]["answer"] == "The total is 27."
    assert len(data_environment["jobs"]) == 2


@pytest.mark.parametrize("change", ["bytes", "source", "message", "report", "permissions"])
def test_changed_sources_fail_before_draft_inference(data_environment, monkeypatch, change):
    from app.config import get_settings
    from app.models import Artifact, Message

    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(proposal())

    api = TestClient(app)
    _, original, created = setup_repeat(api, data_environment, monkeypatch, stream)
    with session_factory()() as s:
        root = s.get(Run, created["id"])
        source = root.parameters["data_agent_source"]
        if change == "bytes":
            aid = source["data_inputs"][0]["artifact_id"]
            (get_settings().data_dir / s.get(Artifact, aid).relative_path).write_text("Changed input")
        elif change == "source":
            s.get(Run, original["id"]).parameters = {
                **s.get(Run, original["id"]).parameters,
                "content": "Changed task",
            }
        elif change == "message":
            user = s.get(Message, root.parameters["user_message_id"])
            user.metadata_json = {**user.metadata_json, "data_agent_source": {}}
        elif change == "permissions":
            root.effective_permissions = []
        else:
            row = s.get(Artifact, source["result_artifacts"][0]["id"])
            (get_settings().data_dir / row.relative_path).write_text("Changed report")
        s.commit()
    drain()
    assert not calls
    with session_factory()() as s:
        assert not list(s.scalars(select(Agent)))
        assert any(
            r.status == "failed" for r in s.scalars(select(Run).where(Run.task_id == created["task_id"]))
        )


@pytest.mark.parametrize("change", ["trash", "stop"])
def test_stop_or_source_change_during_inference_cannot_publish_or_request_a_correction(
    data_environment, monkeypatch, change
):
    from app.db import utcnow
    from app.models import Artifact
    from app.runs import request_cancel

    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        with session_factory()() as s:
            run = s.scalar(select(Run).where(Run.executor_type == "agent_draft", Run.status == "running"))
            if change == "stop":
                request_cancel(s, run)
            else:
                aid = run.parameters["data_agent_source"]["data_inputs"][0]["artifact_id"]
                s.get(Artifact, aid).trashed_at = utcnow()
            s.commit()
        yield json.dumps(proposal())

    api = TestClient(app)
    setup_repeat(api, data_environment, monkeypatch, stream)
    drain()
    assert len(calls) == 1
    with session_factory()() as s:
        assert not list(s.scalars(select(Agent)))
        run = s.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert run.status == ("canceled" if change == "stop" else "failed"), run.error_message


def test_model_cannot_change_frozen_tools_goal_or_inputs(data_environment, monkeypatch):
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(
            {
                **proposal(),
                **(
                    {"tools": ["http_fetch"], "goal": "Changed", "data": {"input_artifact_ids": []}}
                    if len(calls) == 1
                    else {}
                ),
            }
        )

    api = TestClient(app)
    _, original, _ = setup_repeat(api, data_environment, monkeypatch, stream)
    drain()
    assert len(calls) == 2
    with session_factory()() as s:
        agent = s.scalar(select(Agent))
        assert (
            agent
            and agent.tools == ["python_data"]
            and agent.goal == "Calculate the total in the selected file."
        )
        assert agent.data["input_artifact_ids"] == original["parameters"]["data"]["input_artifact_ids"]


def test_document_and_live_public_sources_survive_drafting_and_are_read_again_when_enabled(
    data_environment, monkeypatch
):
    from test_agent_documents import upload_document

    fetched = []

    async def page(url, **kwargs):
        fetched.append(url)
        return {
            "url": url,
            "status": 200,
            "text": "Public values 12 and 15",
            "links": [],
            "truncated": False,
            "untrusted": True,
            "content_type": "text/html",
        }

    monkeypatch.setattr("app.http_fetch.fetch_public", page)
    original_stream = LocalChatProvider.stream
    api = TestClient(app)
    artifact = upload_document(api)
    cid = api.post("/api/chat/conversations", json={"model": "draft-local", "execution_mode": "work"}).json()[
        "id"
    ]
    queued = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Compare values in the selected document and public page.",
            "data": {
                "model": data_environment["model"],
                "documents": {"artifact_ids": [artifact["id"]]},
                "research": {"fetch_urls": ["https://example.com/"]},
            },
        },
    )
    assert queued.status_code == 202, queued.text
    drain()
    assert fetched == ["https://example.com/"]

    async def draft(self, **kwargs):
        prompt = json.loads(kwargs["messages"][1]["content"])
        assert prompt["live_public_sources"] is True
        assert prompt["fixed_tools"] == ["python_data", "read_documents", "http_fetch"]
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", draft)
    response = api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={"content": "Create an agent that repeats this analysis every five minutes."},
    )
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as s:
        agent = s.scalar(select(Agent))
        assert agent is not None
        aid = agent.id
        assert agent.fetch_urls == ["https://example.com/"] and agent.documents["artifact_ids"] == [
            artifact["id"]
        ]
        assert agent.tools == ["python_data", "read_documents", "http_fetch"] and not agent.enabled
        assert agent.data["input_artifact_ids"] == []
    assert fetched == ["https://example.com/"]  # Drafting never fetches or executes the retained tools.
    monkeypatch.setattr(LocalChatProvider, "stream", original_stream)
    saved = api.get(f"/api/agents/{aid}").json()
    enabled = api.post(
        f"/api/agents/{aid}/enabled", json={"enabled": True, "expected_updated_at": saved["updated_at"]}
    )
    assert enabled.status_code == 200, enabled.text
    assert (
        api.post(
            f"/api/agents/{aid}/run", json={"expected_updated_at": enabled.json()["updated_at"]}
        ).status_code
        == 202
    )
    drain()
    assert fetched == ["https://example.com/", "https://example.com/"]
    assert len(data_environment["jobs"]) == 2


def test_turn_receipt_replay_creates_one_source_bound_agent(data_environment, monkeypatch):
    from uuid import uuid4

    api = TestClient(app)
    cid, _ = start(api, data_environment, mode="work")
    drain()

    async def stream(self, **kwargs):
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    request = {
        "client_request_id": str(uuid4()),
        "conversation_id": cid,
        "expected_settings_version": api.get(f"/api/chat/conversations/{cid}")
        .json()
        .get("settings_version", 1),
        "content": "Create an agent that repeats this analysis every five minutes.",
        "execution_mode": "work",
    }
    first = api.post("/api/chat/turns", json=request)
    assert first.status_code == 202, first.text
    second = api.post("/api/chat/turns", json=request)
    assert second.json() == first.json()
    drain()
    third = api.post("/api/chat/turns", json=request)
    assert third.json()["run"]["id"] == first.json()["run"]["id"]
    with session_factory()() as s:
        assert len(list(s.scalars(select(Agent)))) == 1
        assert len(list(s.scalars(select(Run).where(Run.executor_type == "agent_draft")))) == 1


def test_another_conversation_has_no_authority_to_reuse_the_analysis(data_environment):
    api = TestClient(app)
    start(api, data_environment, mode="work")
    drain()
    cid = api.post("/api/chat/conversations", json={"model": "draft-local", "execution_mode": "work"}).json()[
        "id"
    ]
    result = api.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "Create an agent from this analysis."}
    )
    assert result.status_code == 422 and "completed analysis" in result.text
    assert api.get(f"/api/chat/conversations/{cid}").json()["messages"] == []
    with session_factory()() as s:
        assert not list(s.scalars(select(Agent)))
        assert not list(s.scalars(select(Run).where(Run.executor_type == "agent_draft")))
