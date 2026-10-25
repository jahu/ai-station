"""Selected conversation data enters the normal disabled Agent Factory directly."""

import json
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, ChatWorkContext, Run, Worktree
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_documents import upload_document
from test_conversation_data import drain, inspected
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def proposal():
    return {
        "name": "Daily total",
        "goal": "Calculate the total in the selected inputs.",
        "trigger": "interval",
        "interval_seconds": 300,
    }


def setup(api, state, *, scope=None, mode="work"):
    if scope is None:
        scope = {"input_artifact_ids": [inspected(api)], "model": state["model"]}
    cid = api.post("/api/chat/conversations", json={"model": "draft-local", "execution_mode": mode}).json()[
        "id"
    ]
    return cid, scope


def send(api, cid, scope, **extra):
    return api.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Create an agent that computes the total every five minutes.",
            "action": "data.analyze",
            "data": scope,
            **extra,
        },
    )


def test_selected_inputs_create_disabled_agent_without_analysis_or_workspace(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        prompt = json.loads(kwargs["messages"][1]["content"])
        assert prompt["selected_file_names"] == ["sales.csv"]
        assert prompt["allowed_families"] == ["data"]
        assert prompt["source_readers"] == []
        assert "tools" not in prompt["proposal_schema"]["properties"]
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    result = send(api, cid, scope)
    assert result.status_code == 202, result.text
    drain()
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        runs = list(db.scalars(select(Run).where(Run.task_id == result.json()["task_id"])))
        assert agent, [(r.executor_type, r.status, r.error_message) for r in runs]
        assert {r.executor_type for r in runs} == {"orchestrator", "agent_draft"}
        assert all(r.status == "succeeded" for r in runs)
        assert not agent.enabled and agent.next_run_at is None and agent.project_id is None
        assert agent.goal == proposal()["goal"] and agent.model == data_environment["model"]
        assert (
            agent.data["input_artifact_ids"] == scope["input_artifact_ids"] and agent.interval_seconds == 300
        )
        assert agent.tools == ["python_data"] and not list(db.scalars(select(Worktree)))
        draft = next(r for r in runs if r.executor_type == "agent_draft")
        assert set(draft.effective_permissions) == {"manage_agents", "filesystem_read"}
        artifact = db.get(Artifact, draft.metadata_json["definition_artifact_id"])
        assert artifact.parent_artifact_ids == scope["input_artifact_ids"]
    assert len(calls) == 1 and not data_environment["jobs"]
    saved = api.get("/api/chat/conversations/" + cid).json()
    message = next(m for m in saved["messages"] if m["role"] == "assistant")
    assert message["metadata"]["selected_data_agent"]["input_names"] == ["sales.csv"]


def test_future_execution_keeps_documents_and_live_sources_in_own_workspace(data_environment, monkeypatch):
    api = TestClient(app)
    doc = upload_document(api)
    cid, scope = setup(
        api,
        data_environment,
        scope={
            "model": data_environment["model"],
            "documents": {"artifact_ids": [doc["id"]]},
            "research": {"fetch_urls": ["https://example.com/"]},
        },
    )
    original = LocalChatProvider.stream
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

    async def draft(self, **kwargs):
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", draft)
    created = send(api, cid, scope, action="agent.create")
    assert created.status_code == 202, created.text
    drain()
    assert not fetched
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        assert agent, [(r.executor_type, r.status, r.error_message) for r in db.scalars(select(Run))]
        aid = agent.id
        assert agent.documents["artifact_ids"] == [doc["id"]] and agent.fetch_urls == ["https://example.com/"]
        assert (
            agent.tools == ["python_data", "read_documents", "http_fetch"]
            and agent.data["input_artifact_ids"] == []
        )
        assert agent.project_id is None and not list(db.scalars(select(Worktree)))
    saved = api.get("/api/agents/" + aid).json()
    enabled = api.post(
        "/api/agents/" + aid + "/enabled", json={"enabled": True, "expected_updated_at": saved["updated_at"]}
    )
    assert enabled.status_code == 200, enabled.text
    monkeypatch.setattr(LocalChatProvider, "stream", original)
    queued = api.post(
        "/api/agents/" + aid + "/run", json={"expected_updated_at": enabled.json()["updated_at"]}
    )
    assert queued.status_code == 202, queued.text
    drain()
    with session_factory()() as db:
        runs = list(db.scalars(select(Run).where(Run.task_id == queued.json()["task_id"])))
        assert all(r.status == "succeeded" for r in runs), [
            (r.executor_type, r.status, r.error_message) for r in runs
        ]
        final = next(r for r in runs if r.executor_type == "agent_data_result")
        assert final.project_id and final.metadata_json["data_result"]["rows"] == [["27"]]
    assert fetched == ["https://example.com/"] and len(data_environment["jobs"]) == 1


@pytest.mark.parametrize("change", ["bytes", "trash", "document_bytes", "scope", "parent_permission"])
def test_source_changes_fail_before_draft_inference(data_environment, monkeypatch, change):
    from app.config import get_settings

    api = TestClient(app)
    if change == "document_bytes":
        doc = upload_document(api)
        cid, scope = setup(
            api,
            data_environment,
            scope={"model": data_environment["model"], "documents": {"artifact_ids": [doc["id"]]}},
        )
    else:
        cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    result = send(api, cid, scope)
    assert result.status_code == 202, result.text
    with session_factory()() as db:
        root = db.get(Run, result.json()["id"])
        source = root.parameters["selected_data_agent"]
        if change in {"bytes", "document_bytes", "trash"}:
            item = db.get(Artifact, source["artifact_ids"][0])
            if change == "trash":
                item.trashed_at = utcnow()
            else:
                (get_settings().data_dir / item.relative_path).write_text("Changed bytes")
        elif change == "scope":
            root.parameters = {
                **root.parameters,
                "selected_data_agent": {**source, "live_public_sources": True},
            }
        else:
            root.effective_permissions = ["manage_agents"]
        db.commit()
    drain()
    assert not calls
    with session_factory()() as db:
        assert not list(db.scalars(select(Agent)))


@pytest.mark.parametrize("change", ["stop", "trash"])
def test_stop_or_changed_source_during_inference_cannot_publish_or_correct(
    data_environment, monkeypatch, change
):
    from app.runs import request_cancel

    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        with session_factory()() as db:
            run = db.scalar(select(Run).where(Run.executor_type == "agent_draft", Run.status == "running"))
            if change == "stop":
                request_cancel(db, run)
            else:
                db.get(
                    Artifact, run.parameters["selected_data_agent"]["artifact_ids"][0]
                ).trashed_at = utcnow()
            db.commit()
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    assert len(calls) == 1
    with session_factory()() as db:
        assert not list(db.scalars(select(Agent)))
        run = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert run.status == ("canceled" if change == "stop" else "failed"), run.error_message


def test_model_cannot_extend_tools_inputs_or_public_scope(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(
            {
                **proposal(),
                **(
                    {"tools": ["coding_local"], "fetch_urls": ["https://other.example/"], "data": {}}
                    if len(calls) == 1
                    else {}
                ),
            }
        )

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    assert len(calls) == 2
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        assert (
            agent
            and agent.tools == ["python_data"]
            and agent.fetch_urls == []
            and agent.data["input_artifact_ids"] == scope["input_artifact_ids"]
        )


@pytest.mark.parametrize(
    "text",
    [
        "Stwórz mi agenta, który codziennie analizuje wybrane pliki.",
        "Please create a daily agent to compare these inputs.",
    ],
)
def test_natural_explicit_creation_requests(text):
    from app.selected_data_agent import requested

    assert requested(text)


@pytest.mark.parametrize(
    "text",
    [
        "Do not create an agent from selected files",
        '"Create an agent"',
        "Explain how to create an agent",
        "> Stwórz agenta",
        "Create a chart of agent activity",
    ],
)
def test_quotes_negation_and_other_actions_do_not_create_an_agent(text):
    from app.selected_data_agent import requested

    assert not requested(text)


@pytest.mark.parametrize(
    "extra",
    [
        {"execution_mode": "chat"},
        {"image_artifact_ids": [str(uuid4())]},
        {"web_search": {"enabled": True, "query": "extra scope"}},
        {"analysis_agent_source_run_id": str(uuid4())},
    ],
)
def test_chat_and_mixed_authority_are_rejected_before_enqueue(data_environment, extra):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    response = send(api, cid, scope, **extra)
    assert response.status_code == 422, response.text
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.conversation_id == cid)))


def test_first_turn_receipt_replay_creates_one_agent(data_environment, monkeypatch):
    api = TestClient(app)
    scope = {"input_artifact_ids": [inspected(api)], "model": data_environment["model"]}

    async def stream(self, **kwargs):
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    body = {
        "client_request_id": str(uuid4()),
        "selection": {
            "provider": "local-openai-compatible",
            "model": "draft-local",
            "execution_mode": "work",
        },
        "content": "Create an agent that computes totals every five minutes.",
        "action": "data.analyze",
        "data": scope,
    }
    first = api.post("/api/chat/turns", json=body)
    assert first.status_code == 202, first.text
    second = api.post("/api/chat/turns", json=body)
    assert second.json() == first.json()
    drain()
    third = api.post("/api/chat/turns", json=body)
    assert third.json()["run"]["id"] == first.json()["run"]["id"]
    with session_factory()() as db:
        assert len(list(db.scalars(select(Agent)))) == 1


def test_empty_retained_work_context_is_general_work(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    with session_factory()() as db:
        db.add(ChatWorkContext(conversation_id=cid, task_id=None))
        db.commit()

    async def stream(self, **kwargs):
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        assert db.scalar(select(Agent)) is not None


def test_explicit_agent_action_accepts_plain_task_instructions(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)

    async def stream(self, **kwargs):
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope, action="agent.create", content="Compute totals daily at 09:00.")
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        assert db.scalar(select(Agent)) is not None


@pytest.mark.parametrize(
    "content",
    [
        '"Create an agent" is only quoted. Calculate the total.',
        "Do not create an agent. Calculate the total.",
    ],
)
def test_quoted_or_negated_natural_request_keeps_one_off_analysis(data_environment, content):
    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    response = send(api, cid, scope, content=content)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        assert not list(db.scalars(select(Agent)))
        result = db.scalar(
            select(Run).where(
                Run.task_id == response.json()["task_id"], Run.executor_type == "agent_data_result"
            )
        )
        assert result and result.status == "succeeded", result.error_message if result else "No analysis"


def test_instruction_only_file_creation_keeps_zero_input_policy(data_environment, monkeypatch):
    api = TestClient(app)
    cid, scope = setup(
        api,
        data_environment,
        scope={"model": data_environment["model"], "operation": "create", "input_artifact_ids": []},
    )

    async def stream(self, **kwargs):
        yield json.dumps({**proposal(), "goal": "Create a CSV table of the supplied values."})

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    drain()
    with session_factory()() as db:
        agent = db.scalar(select(Agent))
        assert agent and agent.data["operation"] == "create" and agent.data["input_artifact_ids"] == []
        draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert draft.effective_permissions == ["manage_agents"]


def test_selected_inputs_require_local_provider_before_any_draft(data_environment, monkeypatch):
    monkeypatch.setenv("AI_STATION_TEST_EXTERNAL_KEY", "synthetic-test-key")
    api = TestClient(app)
    provider = api.post(
        "/api/chat/providers",
        json={
            "key": "external-test",
            "name": "External test",
            "location": "external",
            "endpoint": "https://api.example.test/v1",
            "default_model": "plain",
            "secret_ref": "env:AI_STATION_TEST_EXTERNAL_KEY",
        },
    )
    assert provider.status_code == 201, provider.text
    cid = api.post(
        "/api/chat/conversations",
        json={"provider": "external-test", "model": "plain", "execution_mode": "work"},
    ).json()["id"]
    scope = {"input_artifact_ids": [inspected(api)], "model": data_environment["model"]}
    response = send(api, cid, scope)
    assert response.status_code == 422 and "Local AI" in response.text
    with session_factory()() as db:
        assert not list(db.scalars(select(Run).where(Run.conversation_id == cid)))


def test_active_project_selection_cannot_grant_a_different_workspace(data_environment):
    from app.models import Task

    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    with session_factory()() as db:
        task = Task(title="Existing project task", capability="coding.local", conversation_id=cid)
        db.add(task)
        db.flush()
        db.add(ChatWorkContext(conversation_id=cid, task_id=task.id))
        db.commit()
    response = send(api, cid, scope)
    assert response.status_code == 422 and "Leave the selected project task" in response.text
    with session_factory()() as db:
        assert not list(db.scalars(select(Agent)))
        assert not list(db.scalars(select(Run).where(Run.conversation_id == cid)))


@pytest.mark.parametrize("change", ["instruction", "task_conversation", "model"])
def test_draft_instruction_and_task_cannot_depart_from_authorized_turn(data_environment, monkeypatch, change):
    from app.engine import tick

    api = TestClient(app)
    cid, scope = setup(api, data_environment)
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        yield json.dumps(proposal())

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    response = send(api, cid, scope)
    assert response.status_code == 202, response.text
    with session_factory()() as db:
        assert tick(db, "prepare-selected-root") == response.json()["id"]
        draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert draft is not None
        if change == "instruction":
            draft.parameters = {
                **draft.parameters,
                "instruction": "Create another agent with a different schedule.",
            }
        elif change == "model":
            draft.parameters = {**draft.parameters, "model": "unselected-model"}
        else:
            draft.task.conversation_id = None
        db.commit()
    drain()
    assert not calls
    with session_factory()() as db:
        assert not list(db.scalars(select(Agent)))
        draft = db.scalar(select(Run).where(Run.executor_type == "agent_draft"))
        assert draft.status == "failed"
