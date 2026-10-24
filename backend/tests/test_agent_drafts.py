import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.chat_providers import ensure_builtin
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Agent, Artifact, ChatProvider, Run, Task
from app.recovery import recover_stale
from app.runner_client import RunnerError
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_vision import vision_runtime as vision_runtime

PROPOSAL = {
    "name": "Local AI news",
    "goal": "Find useful local AI releases and write a source-linked report.",
    "tools": ["web_search"],
    "search_query": "llama.cpp release notes",
    "trigger": "interval",
    "interval_seconds": 300,
}


@pytest.fixture
def model(monkeypatch):
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9")
    clear_settings_cache()
    calls = []
    responses = [json.dumps(PROPOSAL)]

    async def stream(self, **params):
        calls.append(params)
        yield responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls, responses


def body(**extra):
    return {
        "client_request_id": str(uuid4()),
        "instruction": "Co pięć minut znajdź przydatne wydania lokalnego AI. Raport ze źródłami.",
        "model": "fake-local",
        **extra,
    }


def submit(api, **extra):
    r = api.post("/api/agent-drafts", json=body(**extra))
    assert r.status_code == 202, r.text
    return r.json()


def step():
    with session_factory()() as session:
        return tick(session, "draft-test")


def state(api, run):
    return api.get("/api/agent-drafts/" + run["id"]).json()


def test_queued_local_inference_publishes_only_disabled_definition_with_provenance(model):
    calls, _ = model
    with TestClient(app) as api:
        run = submit(api)
        assert not calls and run["status"] == "queued"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))
        reset_engine()
        assert step() == run["id"]
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert agent["interval_seconds"] == 300 and agent["tools"] == ["web_search"]
        assert agent["model"] == "fake-local" and agent["permission_profile"] == "agent_local"
        assert agent["search_query"] == PROPOSAL["search_query"]
        artifact = api.get("/api/artifacts/" + done["metadata"]["definition_artifact_id"]).json()
        stored = api.get("/api/artifacts/" + artifact["id"] + "/file").json()
        assert stored["agent_id"] == agent["id"] and stored["source_run_id"] == run["id"]
        assert not stored["definition"]["enabled"]
        assert calls[0]["location"] == "local" and calls[0]["json_output"]
        assert "messages" in done["parameters"]
        assert "market_watch" not in json.loads(calls[0]["messages"][1]["content"])["operational_local_tools"]
        assert step() is None


def test_replay_survives_provider_changes_but_conflicting_receipt_is_rejected(model):
    with TestClient(app) as api:
        request = body()
        first = api.post("/api/agent-drafts", json=request).json()
        with session_factory()() as session:
            session.scalar(select(ChatProvider)).enabled = False
            session.commit()
        assert api.post("/api/agent-drafts", json=request).json()["id"] == first["id"]
        assert (
            api.post("/api/agent-drafts", json={**request, "instruction": "Different goal"}).status_code
            == 409
        )
        with session_factory()() as session:
            assert len(list(session.scalars(select(Task)))) == 1
            assert len(list(session.scalars(select(Run)))) == 1


def test_concurrent_same_request_publishes_one_task_and_run(model):
    with session_factory()() as session:
        ensure_builtin(session)
        session.commit()
    request = body()

    def send():
        with TestClient(app) as api:
            r = api.post("/api/agent-drafts", json=request)
            assert r.status_code == 202, r.text
            return r.json()["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _: send(), range(2)))) == 1
    with session_factory()() as session:
        assert len(list(session.scalars(select(Run)))) == 1


def test_a_single_bounded_correction_is_inspectable(model):
    calls, responses = model
    responses[:] = ['{"name":"incomplete"}', json.dumps(PROPOSAL)]
    with TestClient(app) as api:
        run = submit(api)
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        assert len(calls) == 2 and "Validation:" in calls[1]["messages"][-1]["content"]
        with session_factory()() as session:
            assert len(list(session.scalars(select(Agent)))) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"enabled": True},
        {"permission_profile": "full_access"},
        {"project_id": str(uuid4())},
        {"model": "external"},
        {"data": {"input_artifact_ids": [str(uuid4())]}},
        {"tools": ["coding_cursor"]},
        {"tools": ["read_file"]},
        {"tools": ["imaginary_tool"]},
        {"tools": ["http_fetch"], "fetch_urls": ["https://other.example/"]},
        {"tools": ["coding_local", "system_snapshot"]},
        {"tools": ["python_data", "http_fetch"]},
    ],
)
def test_invalid_permissions_tools_identifiers_and_invented_urls_publish_nothing(model, extra):
    calls, responses = model
    responses[:] = [json.dumps({**PROPOSAL, **extra})]
    with TestClient(app) as api:
        run = submit(api)
        step()
        assert state(api, run)["status"] == "failed"
        assert len(calls) == 2
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))
            assert not list(session.scalars(select(Artifact)))


def test_explicit_user_url_and_local_code_auto_model_preserve_existing_policy(model):
    _, responses = model
    responses[:] = [
        json.dumps(
            {
                "name": "Website builder",
                "goal": "Build the reviewed website in a private workspace",
                "tools": ["coding_local", "http_fetch"],
                "fetch_urls": ["https://example.com/"],
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(api, instruction="Build a website from https://example.com/")
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["model"] == "auto" and agent["project_id"] is None
        assert agent["workspace_policy"]["auto_validate"]
        assert agent["tools"] == ["coding_local", "http_fetch"]


def test_datetime_draft_is_persisted_as_an_actual_datetime(model):
    _, responses = model
    responses[:] = [
        json.dumps(
            {
                **PROPOSAL,
                "trigger": "datetime",
                "interval_seconds": None,
                "run_at": "2099-01-01T08:00:00+02:00",
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(api)
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["run_at"].startswith("2099-01-01T06:00:00") and not agent["enabled"]


@pytest.mark.parametrize("stage", ["queued", "during_model", "after_model"])
def test_stop_never_publishes_a_definition(model, monkeypatch, stage):
    from app.agent_drafts import AgentDraftExecutor

    with TestClient(app) as api:
        run = submit(api)

        def cancel():
            r = api.post("/api/agent-drafts/" + run["id"] + "/cancel")
            assert r.status_code == 200, r.text

        if stage == "queued":
            cancel()
        elif stage == "during_model":

            async def stream(self, **params):
                cancel()
                yield json.dumps(PROPOSAL)

            monkeypatch.setattr(LocalChatProvider, "stream", stream)
        else:
            original = AgentDraftExecutor.prepare

            async def after(self, session, row):
                result = await original(self, session, row)
                session.commit()
                cancel()
                return result

            monkeypatch.setattr(AgentDraftExecutor, "prepare", after)
        step()
        assert state(api, run)["status"] == "canceled"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))
            assert not list(session.scalars(select(Artifact)))


def test_permission_failure_does_not_call_the_model_or_create_agents(model):
    calls, _ = model
    with TestClient(app) as api:
        run = submit(api)
        with session_factory()() as session:
            session.get(Run, run["id"]).effective_permissions = []
            session.commit()
        step()
        assert state(api, run)["status"] == "failed" and not calls


def test_pending_stream_is_closed_when_stopped(model, monkeypatch):
    closed = []
    with TestClient(app) as api:
        run = submit(api)

        async def stream(self, **params):
            try:
                api.post("/api/agent-drafts/" + run["id"] + "/cancel")
                await asyncio.sleep(5)
                yield "late"
            finally:
                closed.append(True)

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        step()
        assert state(api, run)["status"] == "canceled" and closed


@pytest.mark.parametrize("status", [RunStatus.CLAIMED, RunStatus.RUNNING])
def test_stale_inference_is_not_replayed_but_an_unstarted_claim_is_safe(model, status):
    class Absent:
        def inspect_process(self, run_id):
            raise RunnerError(404, "not owned")

    with TestClient(app) as api:
        run = submit(api)
        with session_factory()() as session:
            row = session.get(Run, run["id"])
            transition(session, row, RunStatus.CLAIMED, event_type="run.claimed")
            if status == RunStatus.RUNNING:
                transition(session, row, RunStatus.PREPARING, event_type="executor.preparing")
                transition(session, row, RunStatus.RUNNING, event_type="executor.started")
            row.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            assert recover_stale(session, Absent()) == [row.id]
            session.commit()
            assert row.status == ("queued" if status == RunStatus.CLAIMED else "interrupted")
        assert not model[0]


def test_selected_owned_model_load_is_an_ordinary_prerequisite(model, vision_runtime):
    model_id, loads = vision_runtime
    with TestClient(app) as api:
        run = submit(api, model="llamacpp:" + model_id)
        assert not loads and not model[0]
        with session_factory()() as session:
            queued = list(session.scalars(select(Run)))
            assert any(r.executor_type == "llama_load" and r.status == "queued" for r in queued)
        for _ in range(5):
            if step() is None:
                break
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        assert len(loads) == len(model[0]) == 1


def test_recognized_public_crypto_scope_is_preserved_without_a_model_inventing_policy(model):
    _, responses = model
    responses[:] = [
        json.dumps(
            {
                "name": "Bitcoin observer",
                "goal": "Observe Bitcoin in USD and alert on a five percent change",
                "tools": ["market_watch"],
                "trigger": "interval",
                "interval_seconds": 3600,
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(api, instruction="Every hour check Bitcoin price in USD, alert at 5%")
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["model"] == "" and agent["market"]["provider"] == "coinbase_exchange"
        assert agent["market"]["instruments"] == ["BTC-USD"]
        assert agent["market"]["threshold_percent"] == "5" and not agent["enabled"]
        assert agent["market"].get("email") is None


def test_generic_stock_research_does_not_require_a_financial_data_account(model):
    calls, responses = model
    responses[:] = [
        json.dumps(
            {
                **PROPOSAL,
                "name": "Public stock research",
                "goal": "Research public stock price news",
                "search_query": "public stock prices news",
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(api, instruction="Every morning research stock prices using free public sources")
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["market"] is None and agent["tools"] == ["web_search"]
        assert "market_watch" not in json.loads(calls[0]["messages"][1]["content"])["operational_local_tools"]


def test_revocation_during_generation_prevents_publication(model, monkeypatch):
    with TestClient(app) as api:
        run = submit(api)

        async def stream(self, **params):
            with session_factory()() as session:
                session.get(Run, run["id"]).effective_permissions = []
                session.commit()
            yield json.dumps(PROPOSAL)

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        step()
        assert state(api, run)["status"] == "failed"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))


def work_turn(api):
    cid = api.post("/api/chat/conversations", json={"model": "fake-local", "execution_mode": "work"}).json()[
        "id"
    ]
    request = {
        "client_request_id": str(uuid4()),
        "conversation_id": cid,
        "expected_settings_version": 1,
        "content": 'Create an agent that every five minutes searches for "llama.cpp releases"',
        "web_search": {"enabled": False},
    }
    response = api.post("/api/chat/turns", json=request)
    assert response.status_code == 202, response.text
    return cid, request, response.json()["run"]


def test_work_uses_same_queued_factory_and_receipt_then_displays_disabled_draft_inline(model):
    with TestClient(app) as api:
        cid, request, parent = work_turn(api)
        assert step() == parent["id"]
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))
        assert api.post("/api/chat/turns", json=request).json()["run"]["id"] == parent["id"]
        detail = api.get("/api/chat/conversations/" + cid).json()
        child = detail["active_run"]
        assert child["executor_type"] == "agent_draft" and child["task_id"] == parent["task_id"]
        assert child["effective_permissions"] == ["manage_agents"]
        step()
        detail = api.get("/api/chat/conversations/" + cid).json()
        assert detail["active_run"] is None
        metadata = detail["messages"][-1]["metadata"]
        assert metadata["draft_run_id"] == child["id"]
        agent = api.get("/api/agents/" + metadata["agent_id"]).json()
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert len(model[0]) == 1


@pytest.mark.parametrize("problem", ["parent_permission", "conversation"])
def test_work_publication_remains_bound_to_its_authorized_origin(model, problem):
    with TestClient(app) as api:
        cid, _, parent = work_turn(api)
        step()
        child = api.get("/api/chat/conversations/" + cid).json()["active_run"]
        with session_factory()() as session:
            if problem == "parent_permission":
                session.get(Run, parent["id"]).effective_permissions = []
            else:
                session.get(Run, child["id"]).conversation_id = None
            session.commit()
        step()
        assert state(api, child)["status"] == "failed"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))


def test_work_stop_during_factory_does_not_publish_or_activate(model, monkeypatch):
    with TestClient(app) as api:
        cid, _, parent = work_turn(api)
        step()
        child = api.get("/api/chat/conversations/" + cid).json()["active_run"]

        async def stream(self, **params):
            response = api.post("/api/chat/conversations/" + cid + "/tasks/" + parent["task_id"] + "/cancel")
            assert response.status_code == 200, response.text
            yield json.dumps(PROPOSAL)

        monkeypatch.setattr(LocalChatProvider, "stream", stream)
        step()
        assert state(api, child)["status"] == "canceled"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))


def test_external_chat_provider_creates_only_a_labelled_model_free_local_draft(model, monkeypatch):
    monkeypatch.setenv("AI_STATION_DRAFT_TEST_KEY", "fixture-only")
    with session_factory()() as session:
        session.add(
            ChatProvider(
                key="external-fixture",
                name="External fixture",
                kind="openai-compatible",
                location="external",
                endpoint="https://api.example.com/v1",
                secret_ref="env:AI_STATION_DRAFT_TEST_KEY",
                enabled=True,
            )
        )
        session.commit()
    with TestClient(app) as api:
        created = api.post(
            "/api/chat/conversations",
            json={"provider": "external-fixture", "model": "external-model", "execution_mode": "work"},
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={"content": "Create an agent that summarizes local GPU usage"},
        )
        assert response.status_code == 202, response.text
        step()
        detail = api.get("/api/chat/conversations/" + cid).json()
        assert "without inference" in detail["messages"][-1]["content"]
        aid = detail["messages"][-1]["metadata"]["agent_id"]
        agent = api.get("/api/agents/" + aid).json()
        assert agent["model"] == "" and not agent["enabled"]
        assert not model[0] and detail["active_run"] is None


def test_real_model_missing_page_scope_is_corrected_before_a_draft_is_saved(model):
    calls, responses = model
    incomplete = {
        **PROPOSAL,
        "name": "Llama.cpp Daily Digest",
        "tools": ["web_search", "http_fetch"],
        "fetch_urls": [],
        "trigger": "cron",
        "cron_expr": "0 8 * * *",
        "interval_seconds": None,
    }
    responses[:] = [json.dumps(incomplete), json.dumps({**incomplete, "tools": ["web_search"]})]
    with TestClient(app) as api:
        run = submit(
            api,
            instruction="Codziennie o 08:00 UTC przygotuj podsumowanie nowości w llama.cpp z publicznych źródeł",
        )
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        assert len(calls) == 2
        catalog = json.loads(calls[0]["messages"][1]["content"])["operational_local_tools"]
        assert "http_fetch" not in catalog and "browser" not in catalog
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["tools"] == ["web_search"] and agent["search_query"]
        assert not agent["fetch_urls"] and not agent["enabled"] and agent["next_run_at"] is None


@pytest.mark.parametrize("tool", ["web_search", "http_fetch", "browser"])
def test_selected_tools_with_missing_required_scope_never_publish_an_unusable_draft(model, tool):
    _, responses = model
    responses[:] = [json.dumps({**PROPOSAL, "tools": [tool], "search_query": "", "fetch_urls": []})]
    with TestClient(app) as api:
        run = submit(api, instruction="Review public information at https://example.com/")
        step()
        assert state(api, run)["status"] == "failed"
        with session_factory()() as session:
            assert not list(session.scalars(select(Agent)))


def test_assisted_draft_can_review_source_page_reading_without_inventing_urls(model, monkeypatch):
    calls, responses = model
    responses[:] = [json.dumps({**PROPOSAL, "tools": ["web_search", "search_pages"]})]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Drafting must never read public pages")

    monkeypatch.setattr("app.http_fetch.fetch_public", forbidden)
    with TestClient(app) as api:
        run = submit(api, instruction="Find release notes and read the search sources before reporting.")
        step()
        result = state(api, run)
        assert result["status"] == "succeeded", result["error_message"]
        agent = api.get("/api/agents/" + result["metadata"]["agent_id"]).json()
        assert agent["tools"] == ["web_search", "search_pages"] and agent["fetch_urls"] == []
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert agent["search_query"] == PROPOSAL["search_query"]
        assert "search_pages" in calls[0]["messages"][1]["content"]


@pytest.mark.parametrize(
    "tools", [["coding_local", "web_search"], ["coding_local", "web_search", "search_pages"]]
)
def test_assisted_draft_can_review_research_before_local_code(model, tools):
    calls, responses = model
    responses[:] = [
        json.dumps(
            {
                **PROPOSAL,
                "name": "Research builder",
                "goal": "Build a small reference website from reviewed public research",
                "tools": tools,
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(
            api,
            instruction="Create a local agent to research public weather references and build a small website",
        )
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["tools"] == tools and agent["model"] == "auto"
        assert not agent["enabled"] and not agent["project_id"]
        assert agent["search_query"] == PROPOSAL["search_query"]
        assert len(calls) == 1


@pytest.mark.parametrize(
    "tools", [["python_data", "http_fetch"], ["python_data", "web_search", "search_pages"]]
)
def test_assisted_data_research_draft_remains_disabled_without_invented_files(model, tools):
    calls, responses = model
    responses[:] = [
        json.dumps(
            {
                **PROPOSAL,
                "goal": "Compute a CSV from reviewed public numbers",
                "tools": tools,
                "fetch_urls": ["https://data.example.com/numbers"] if "http_fetch" in tools else [],
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(
            api, instruction="Analyse public JSON from https://data.example.com/numbers and create a CSV"
        )
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["tools"] == tools and agent["model"] == "auto"
        assert agent["data"] == {"input_artifact_ids": [], "max_repairs": 1}
        assert not agent["enabled"] and agent["next_run_at"] is None and not agent["project_id"]
        assert len(calls) == 1


@pytest.mark.parametrize("family", ["coding_local", "python_data"])
def test_assisted_draft_can_review_rendered_sources_for_local_work(model, monkeypatch, family):
    monkeypatch.setattr("app.browser.available", lambda: {"available": True})
    calls, responses = model
    responses[:] = [
        json.dumps(
            {
                **PROPOSAL,
                "tools": [family, "browser"],
                "fetch_urls": ["https://example.com/"],
                "search_query": "",
            }
        )
    ]
    with TestClient(app) as api:
        run = submit(
            api,
            instruction="Create a local agent to read JavaScript-rendered https://example.com/ and create a CSV"
            if family == "python_data"
            else "Create a local agent to build a website from JavaScript-rendered https://example.com/",
        )
        step()
        done = state(api, run)
        assert done["status"] == "succeeded", done["error_message"]
        agent = api.get("/api/agents/" + done["metadata"]["agent_id"]).json()
        assert agent["tools"] == [family, "browser"] and agent["model"] == "auto"
        assert agent["fetch_urls"] == ["https://example.com/"] and not agent["enabled"]
        assert agent["next_run_at"] is None and len(calls) == 1
