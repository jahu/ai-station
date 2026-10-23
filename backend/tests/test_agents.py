import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from app.api import app
from app.db import reset_engine, session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.memory import upsert_memory
from app.models import Agent, MemoryEntry, Project, Run
from app.providers import ProviderError
from app.runs import request_cancel
from app.schedule import scheduler_tick
from fastapi.testclient import TestClient
from sqlalchemy import select, text


def create(api, **extra):
    result = api.post(
        "/api/agents",
        json={"name": "Status report", "goal": "Summarize available context", "model": "fake-local", **extra},
    )
    assert result.status_code == 201, result.text
    return result.json()


def run_now(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert response.status_code == 202, response.text
    return response.json()


def drain(session, worker="agent-test", limit=30):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def workflow_step(api, parent_id, key):
    parent = api.get("/api/runs/" + parent_id).json()
    step = next(item for item in parent["workflow"]["steps"] if item["key"] == key)
    return api.get("/api/runs/" + step["run_id"]).json()


def test_factory_disabled_activation_and_unsupported_tools():
    api = TestClient(app)
    draft = api.post(
        "/api/agents/draft",
        json={"instruction": "Every morning check GPU workstation status", "model": "fake-local"},
    ).json()
    assert draft["enabled"] is False and draft["next_run_at"] is None
    assert draft["trigger"] == "cron" and draft["cron_expr"] == "0 8 * * *"
    assert draft["tools"] == ["system_snapshot"]
    assert (
        api.post(
            f"/api/agents/{draft['id']}/run", json={"expected_updated_at": draft["updated_at"]}
        ).status_code
        == 409
    )
    enabled = api.post(
        f"/api/agents/{draft['id']}/enabled",
        json={"enabled": True, "expected_updated_at": draft["updated_at"]},
    )
    assert enabled.status_code == 200 and enabled.json()["next_run_at"]
    web = api.post(
        "/api/agents/draft", json={"instruction": "Every day search the web for news", "model": "fake-local"}
    ).json()
    result = api.post(
        f"/api/agents/{web['id']}/enabled", json={"enabled": True, "expected_updated_at": web["updated_at"]}
    )
    assert result.status_code == 422 and "web_search" in result.text
    assert api.get(f"/api/agents/{web['id']}").json()["enabled"] is False


def test_local_agent_context_artifact_status_and_restart(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs)
        yield "A factual "
        yield "**local report**."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["memory_search"])
    other = create(api, name="Another agent")
    with session_factory()() as session:
        upsert_memory(session, scope="agent", scope_id=agent["id"], content="Relevant observation")
        upsert_memory(session, scope="agent", scope_id=other["id"], content="PRIVATE OTHER AGENT")
        session.commit()
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "agent-test")
    parent = api.get("/api/runs/" + queued["id"]).json()
    run = workflow_step(api, queued["id"], "report")
    assert parent["status"] == "succeeded" and run["status"] == "succeeded"
    assert "Relevant observation" in str(received[0]["messages"])
    assert "PRIVATE OTHER AGENT" not in str(received[0]["messages"])
    assert run["effective_permissions"] == []
    assert run["parameters"]["tool_context"][0]["tool"] == "memory_search"
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert artifact["type"] == "markdown" and artifact["metadata"]["partial"] is False
    reset_engine()
    saved = api.get("/api/agents/" + agent["id"]).json()
    assert saved["last_status"] == "succeeded" and saved["failure_count"] == 0
    assert queued["id"] in {item["id"] for item in saved["runs"]}


def test_failure_is_not_reported_as_success(monkeypatch):
    async def fail(self, **kwargs):
        yield "Partial observation"
        raise ProviderError("Unavailable provider")

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "agent-test")
    report = workflow_step(api, queued["id"], "report")
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "succeeded"
    assert report["status"] == "failed"
    assert api.get("/api/agents/" + agent["id"]).json()["failure_count"] == 1
    assert api.get("/api/artifacts?run_id=" + report["id"]).json()[0]["metadata"]["partial"] is True


def test_silent_generation_cancels_and_closes_stream(monkeypatch):
    closed = []

    async def silent(self, **kwargs):
        with session_factory()() as current:
            run = current.scalar(select(Run).where(Run.executor_type == "agent"))
            request_cancel(current, run)
            current.commit()
        try:
            await asyncio.sleep(30)
            yield "never"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", silent)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "agent-test")
    assert closed
    assert workflow_step(api, queued["id"], "report")["status"] == "canceled"
    assert api.get("/api/agents/" + agent["id"]).json()["last_status"] == "canceled"


def test_schedule_claims_are_atomic_and_non_overlapping():
    api = TestClient(app)
    agent = create(api, enabled=True, trigger="interval", interval_seconds=60)
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.next_run_at = utcnow() - timedelta(hours=1)
        session.commit()
    barrier = Barrier(2)

    def schedule():
        barrier.wait()
        with session_factory()() as session:
            result = scheduler_tick(session)
            session.commit()
            return result

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: schedule(), range(2)))
    assert sum(len(result) for result in results) == 1
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert scheduler_tick(session) == []
        assert row.next_run_at > utcnow()
        session.commit()
    assert (
        api.post(
            f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
        ).status_code
        == 409
    )
    paused = api.post(
        f"/api/agents/{agent['id']}/enabled",
        json={"expected_updated_at": agent["updated_at"], "enabled": False},
    )
    assert paused.status_code == 200 and paused.json()["next_run_at"] is None
    assert api.get("/api/agents/" + agent["id"]).json()["runs"][0]["status"] == "queued"


def test_one_shot_and_duplicate_never_auto_reactivate():
    api = TestClient(app)
    future = utcnow() + timedelta(minutes=5)
    agent = create(api, enabled=True, trigger="datetime", run_at=future.isoformat())
    with session_factory()() as session:
        row = session.get(Agent, agent["id"])
        row.run_at = row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert len(scheduler_tick(session)) == 1
        session.commit()
        assert scheduler_tick(session) == []
    row = api.get("/api/agents/" + agent["id"]).json()
    assert row["enabled"] is False and row["next_run_at"] is None
    copy = api.post(
        f"/api/agents/{agent['id']}/duplicate", json={"expected_updated_at": row["updated_at"]}
    ).json()
    assert copy["enabled"] is False and copy["last_run_at"] is None and copy["next_run_at"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"provider": "external"},
        {"tools": ["shell"]},
        {"skills": ["unimplemented"]},
        {"trigger": "interval"},
        {"cron_expr": "* * * * *"},
        {"trigger": "cron", "cron_expr": "* * * * * *"},
        {"trigger": "datetime", "run_at": "2026-01-01T00:00:00"},
        {"permission_profile": "coding_external"},
        {"enabled": True, "model": ""},
        {"execution_target": "host"},
    ],
)
def test_agent_definition_rejects_unimplemented_or_unsafe_fields(extra):
    response = TestClient(app).post("/api/agents", json={"name": "Test", "goal": "Report", **extra})
    assert response.status_code == 422


def test_agents_list_filters_by_linked_project(session):
    project = Project(name="Workstation docs", repo_path="/fixture/repo")
    session.add(project)
    session.commit()
    api = TestClient(app)
    linked = create(api, name="Linked briefing", project_id=project.id)
    create(api, name="Unlinked briefing")
    listed = api.get("/api/agents", params={"project_id": project.id}).json()
    assert [row["id"] for row in listed] == [linked["id"]]
    assert {row["name"] for row in api.get("/api/agents").json()} == {
        "Linked briefing",
        "Unlinked briefing",
    }
    assert api.get("/api/agents", params={"project_id": "not-a-uuid"}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000001"
    assert api.get("/api/agents", params={"project_id": missing}).json() == []


def test_long_factory_draft_is_valid_and_stale_edits_are_rejected():
    from app.agent_schema import AgentSettings

    api = TestClient(app)
    draft = api.post("/api/agents/draft", json={"instruction": "A" * 16000, "model": "fake"}).json()
    settings = {key: draft[key] for key in AgentSettings.model_fields}
    AgentSettings.model_validate(settings)
    saved = api.put(
        f"/api/agents/{draft['id']}",
        json={**settings, "name": "Changed", "expected_updated_at": draft["updated_at"]},
    )
    assert saved.status_code == 200
    stale = api.put(
        f"/api/agents/{draft['id']}",
        json={**settings, "name": "Stale", "expected_updated_at": draft["updated_at"]},
    )
    assert stale.status_code == 409
    assert api.get(f"/api/agents/{draft['id']}").json()["name"] == "Changed"


def test_tool_permissions_enforced_before_host_access(monkeypatch):
    from app.runner_client import RunnerClient

    called = []
    monkeypatch.setattr(RunnerClient, "hardware", lambda self: called.append(True))
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot"])
    queued = run_now(api, agent)
    assert queued["effective_permissions"] == ["filesystem_read"]
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.effective_permissions = []
        session.commit()
        drain(session, "agent-test")
    assert not called
    assert workflow_step(api, queued["id"], "system_snapshot")["status"] == "failed"


@pytest.fixture
def research(monkeypatch):
    from app import web_search
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    calls, messages = [], []

    async def search(query):
        calls.append(query)
        return {
            "query": query,
            "provider": "searxng",
            "searched_at": utcnow().isoformat(),
            "partial": False,
            "sources": [
                {
                    "id": 1,
                    "title": "Source",
                    "url": "https://example.com/research",
                    "snippet": "Public finding",
                }
            ],
        }

    async def stream(self, **params):
        messages.append(params["messages"])
        yield "# Research report\n\n[Source](https://example.com/research)"

    monkeypatch.setattr(web_search, "search", search)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls, messages


@pytest.mark.parametrize("scheduled", [False, True])
def test_agent_web_research_snapshots_public_query_and_retains_sources(research, scheduled):
    calls, messages = research
    with TestClient(app) as api:
        agent = create(
            api,
            enabled=True,
            tools=["web_search"],
            search_query="public model releases",
            goal="PRIVATE GOAL: summarize public findings",
            trigger="interval" if scheduled else "manual",
            interval_seconds=60 if scheduled else None,
        )
        if scheduled:
            with session_factory()() as session:
                session.get(Agent, agent["id"]).next_run_at = utcnow() - timedelta(seconds=1)
                session.commit()
                run_id = scheduler_tick(session)[0]
                session.commit()
        else:
            run_id = run_now(api, agent)["id"]
        with session_factory()() as session:
            # An already-queued Run must retain the reviewed query even if stored settings change.
            session.get(Agent, agent["id"]).search_query = "different future query"
            session.commit()
            drain(session, "research-test")
        parent = api.get("/api/runs/" + run_id).json()
        search = workflow_step(api, run_id, "web_search")
        run = workflow_step(api, run_id, "report")
        assert parent["status"] == "succeeded" and run["status"] == "succeeded", run
        assert parent["effective_permissions"] == ["network_read"]
        assert calls == ["public model releases"]
        assert "PRIVATE GOAL" in str(messages) and "Public finding" in str(messages)
        assert run["metadata"]["web_search"]["sources"][0]["url"] == "https://example.com/research"
        assert {item["type"] for item in api.get("/api/artifacts?run_id=" + search["id"]).json()} == {"json"}
        assert {item["type"] for item in api.get("/api/artifacts?run_id=" + run["id"]).json()} == {"markdown"}
        reset_engine()
        assert api.get("/api/runs/" + search["id"]).json()["metadata"]["web_search"]["query"] == calls[0]
        assert "tool.completed" in api.get("/api/runs/" + search["id"] + "/stream").text


def test_stock_example_runs_as_public_research_without_a_data_account(research):
    calls, messages = research
    with TestClient(app) as api:
        instruction = (
            'Every day check stock prices; search for "Apple stock price". '
            "PRIVATE: report to private@example.com"
        )
        response = api.post("/api/agents/draft", json={"instruction": instruction, "model": "fake-local"})
        assert response.status_code == 201, response.text
        draft = response.json()
        assert draft["market"] is None and draft["tools"] == ["web_search"]
        assert draft["enabled"] is False
        enabled = api.post(
            f"/api/agents/{draft['id']}/enabled",
            json={"enabled": True, "expected_updated_at": draft["updated_at"]},
        )
        assert enabled.status_code == 200, enabled.text
        run_id = run_now(api, enabled.json())["id"]
        with session_factory()() as session:
            drain(session, "public-research-test")
        parent = api.get("/api/runs/" + run_id).json()
        report = workflow_step(api, run_id, "report")
        assert parent["status"] == report["status"] == "succeeded", report
        assert parent["effective_permissions"] == ["network_read"]
        assert calls == ["Apple stock price"] and "PRIVATE" in str(messages)
        search = workflow_step(api, run_id, "web_search")
        assert search["metadata"]["web_search"]["sources"][0]["url"] == "https://example.com/research"
        assert not api.get("/api/connectors").json()


def test_stock_research_reviews_public_query_instead_of_requesting_a_key():
    with TestClient(app) as api:
        draft = api.post(
            "/api/agents/draft",
            json={"instruction": "Codziennie sprawdzaj ceny akcji Apple", "model": "fake-local"},
        ).json()
        response = api.post(
            f"/api/agents/{draft['id']}/enabled",
            json={"enabled": True, "expected_updated_at": draft["updated_at"]},
        )
        assert response.status_code == 422 and "public search query" in response.text
        assert "stock-data account" not in response.text


@pytest.mark.parametrize("mode", ["cancel", "timeout", "permission", "failure"])
def test_agent_search_cancels_bounds_runtime_and_enforces_permission(research, monkeypatch, mode):
    from app import web_search

    closed = []

    async def search(query):
        if mode == "permission":
            raise AssertionError("Unpermitted search")
        if mode == "failure":
            raise ProviderError("Search unavailable")
        try:
            if mode == "cancel":
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, run_id))
                    session.commit()
            await asyncio.Future()
        finally:
            closed.append(True)

    monkeypatch.setattr(web_search, "search", search)
    if mode == "timeout":
        import time

        original = web_search.execute_search

        async def short_deadline(session, run, query, **kwargs):
            return await original(session, run, query, deadline=time.monotonic() + 0.05)

        monkeypatch.setattr(web_search, "execute_search", short_deadline)
    with TestClient(app) as api:
        agent = create(api, enabled=True, tools=["web_search"], search_query="public query")
        run_id = run_now(api, agent)["id"]
        with session_factory()() as session:
            if mode == "permission":
                session.get(Run, run_id).effective_permissions = []
                session.commit()
            drain(session, "research-negative")
        search = workflow_step(api, run_id, "web_search")
        assert search["status"] == ("canceled" if mode == "cancel" else "failed"), search
        assert not research[1]
        if mode in {"cancel", "timeout"}:
            assert closed
        assert api.get("/api/artifacts?run_id=" + search["id"]).json() == []


def test_agent_query_requires_explicit_review_before_activation(research):
    with TestClient(app) as api:
        draft = api.post(
            "/api/agents/draft", json={"instruction": "Every day search the web", "model": "local"}
        ).json()
        assert draft["search_query"] == "" and not draft["enabled"]
        assert (
            api.post(
                f"/api/agents/{draft['id']}/enabled",
                json={"enabled": True, "expected_updated_at": draft["updated_at"]},
            ).status_code
            == 422
        )
        assert (
            api.post(
                "/api/agents",
                json={
                    "name": "Test",
                    "goal": "Goal",
                    "model": "local",
                    "tools": ["web_search"],
                    "search_query": "x" * 501,
                },
            ).status_code
            == 422
        )
        registry = {tool["name"]: tool for tool in api.get("/api/agents/tools").json()}
        assert registry["web_search"]["operational"] and registry["web_search"]["required_permissions"] == [
            "network_read"
        ]
        assert registry["http_fetch"]["operational"] and registry["http_fetch"]["required_permissions"] == [
            "network_read"
        ]


@pytest.fixture
def pages(monkeypatch):
    from app import http_fetch

    calls, messages = [], []

    async def fetch_public(url):
        calls.append(url)
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "text": "Public page excerpt",
            "links": [url.rstrip("/") + "/about"],
            "truncated": False,
            "untrusted": True,
            "bounded": True,
        }

    async def stream(self, **params):
        messages.append(params["messages"])
        yield "# Page report\n\n[Source](https://www.example.com/)"

    monkeypatch.setattr(http_fetch, "fetch_public", fetch_public)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return calls, messages


@pytest.mark.parametrize("scheduled", [False, True])
def test_agent_http_fetch_snapshots_reviewed_urls_and_retains_pages(pages, scheduled):
    calls, messages = pages
    with TestClient(app) as api:
        agent = create(
            api,
            enabled=True,
            tools=["http_fetch"],
            fetch_urls=["https://www.example.com/"],
            goal="PRIVATE GOAL: summarize the public page",
            trigger="interval" if scheduled else "manual",
            interval_seconds=60 if scheduled else None,
        )
        if scheduled:
            with session_factory()() as session:
                session.get(Agent, agent["id"]).next_run_at = utcnow() - timedelta(seconds=1)
                session.commit()
                run_id = scheduler_tick(session)[0]
                session.commit()
        else:
            run_id = run_now(api, agent)["id"]
        with session_factory()() as session:
            session.get(Agent, agent["id"]).fetch_urls = ["https://www.example.com/later"]
            session.commit()
            drain(session, "fetch-test")
        parent = api.get("/api/runs/" + run_id).json()
        fetch = workflow_step(api, run_id, "http_fetch")
        run = workflow_step(api, run_id, "report")
        assert parent["status"] == "succeeded" and run["status"] == "succeeded", run
        assert parent["effective_permissions"] == ["network_read"]
        assert calls == ["https://www.example.com/"]
        assert "PRIVATE GOAL" in str(messages) and "Public page excerpt" in str(messages)
        assert run["metadata"]["http_fetch"]["pages"][0]["url"] == "https://www.example.com/"
        assert {item["type"] for item in api.get("/api/artifacts?run_id=" + fetch["id"]).json()} == {"json"}
        assert {item["type"] for item in api.get("/api/artifacts?run_id=" + run["id"]).json()} == {"markdown"}
        reset_engine()
        assert api.get("/api/runs/" + fetch["id"]).json()["metadata"]["http_fetch"]["urls"] == calls
        assert "tool.completed" in api.get("/api/runs/" + fetch["id"] + "/stream").text


@pytest.mark.parametrize("mode", ["cancel", "timeout", "permission", "failure", "ssrf"])
def test_agent_fetch_cancels_bounds_runtime_and_enforces_permission(pages, monkeypatch, mode):
    from app import http_fetch

    closed = []

    async def fetch_public(url):
        if mode == "permission":
            raise AssertionError("Unpermitted fetch")
        if mode == "failure":
            raise ProviderError("HTTP fetch could not complete. Check the URL and try again.")
        if mode == "ssrf":
            raise ValueError("Refusing a non-public network address")
        try:
            if mode == "cancel":
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, run_id))
                    session.commit()
            await asyncio.Future()
        finally:
            closed.append(True)

    monkeypatch.setattr(http_fetch, "fetch_public", fetch_public)
    if mode == "timeout":
        import time

        original = http_fetch.execute_fetch

        async def short_deadline(session, run, urls, **kwargs):
            return await original(session, run, urls, deadline=time.monotonic() + 0.05)

        monkeypatch.setattr(http_fetch, "execute_fetch", short_deadline)
    with TestClient(app) as api:
        agent = create(api, enabled=True, tools=["http_fetch"], fetch_urls=["https://www.example.com/"])
        run_id = run_now(api, agent)["id"]
        with session_factory()() as session:
            if mode == "permission":
                session.get(Run, run_id).effective_permissions = []
                session.commit()
            drain(session, "fetch-negative")
        fetch = workflow_step(api, run_id, "http_fetch")
        assert fetch["status"] == ("canceled" if mode == "cancel" else "failed"), fetch
        assert not pages[1]
        if mode in {"cancel", "timeout"}:
            assert closed
        assert api.get("/api/artifacts?run_id=" + fetch["id"]).json() == []


def test_agent_fetch_requires_explicit_review_before_activation():
    with TestClient(app) as api:
        draft = api.post(
            "/api/agents/draft",
            json={"instruction": "Every day fetch https://www.example.com/ docs", "model": "local"},
        ).json()
        assert draft["tools"] == ["http_fetch"]
        assert draft["fetch_urls"] == ["https://www.example.com/"]
        assert not draft["enabled"]
        empty = api.post(
            "/api/agents/draft", json={"instruction": "Fetch the public homepage daily", "model": "local"}
        ).json()
        assert empty["tools"] == ["http_fetch"] and empty["fetch_urls"] == []
        assert (
            api.post(
                f"/api/agents/{empty['id']}/enabled",
                json={"enabled": True, "expected_updated_at": empty["updated_at"]},
            ).status_code
            == 422
        )
        assert (
            api.post(
                "/api/agents",
                json={
                    "name": "Test",
                    "goal": "Goal",
                    "model": "local",
                    "tools": ["http_fetch"],
                    "fetch_urls": ["http://127.0.0.1/admin"],
                },
            ).status_code
            == 422
        )


def test_agent_search_migration_preserves_existing_definitions():
    from alembic import command
    from app.db import alembic_config

    with TestClient(app) as api:
        agent = create(api, tools=["memory_search"])
        command.downgrade(alembic_config(), "0005")
        command.upgrade(alembic_config(), "head")
        saved = api.get("/api/agents/" + agent["id"]).json()
        assert saved["goal"] == agent["goal"] and saved["tools"] == ["memory_search"]
        assert saved["search_query"] == "" and saved["fetch_urls"] == []
        assert saved["workflow_mode"] == "sequential"
        assert saved["tool_calling"] == "none"


@pytest.mark.parametrize("remember", [False, True])
def test_report_memory_opt_in_provenance_and_next_scheduled_run(monkeypatch, remember):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs["messages"])
        yield "Retained observation for tomorrow"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    tools = ["memory_search", "remember_report"] if remember else ["memory_search"]
    agent = create(api, enabled=True, tools=tools, trigger="interval", interval_seconds=60)
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "memory-test")
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded"
    assert ("memory_write" in run["effective_permissions"]) is remember
    reset_engine()
    with session_factory()() as session:
        entries = list(session.scalars(select(MemoryEntry)))
        assert len(entries) == int(remember)
        if remember:
            entry = entries[0]
            assert entry.scope == "agent" and entry.scope_id == agent["id"]
            assert entry.source_run_id == run["id"]
            assert entry.memory_type == "observation" and entry.tags == ["agent-report"]
            assert not entry.pinned and entry.confidence is None
            assert run["metadata"]["memory_entry_id"] == entry.id
            from app.agent_executor import LocalAgentExecutor

            LocalAgentExecutor._remember(session, session.get(Run, run["id"]), "Duplicate")
            assert len(list(session.scalars(select(MemoryEntry)))) == 1
        row = session.get(Agent, agent["id"])
        row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert len(scheduler_tick(session)) == 1
        session.commit()
        drain(session, "memory-test")
    assert ("Retained observation" in str(received[1])) is remember
    other = create(api, name="Different scope", enabled=True, tools=["memory_search"])
    run_now(api, other)
    with session_factory()() as session:
        drain(session, "memory-test")
    assert "Retained observation" not in str(received[2])


@pytest.mark.parametrize(
    "outcome", ["failed", "canceled", "late_cancel", "missing_permission", "write_failed"]
)
def test_unsuccessful_agent_never_retains_memory(monkeypatch, outcome):
    from app.agent_executor import LocalAgentExecutor

    api = TestClient(app)
    agent = create(api, enabled=True, tools=["remember_report"])
    queued = run_now(api, agent)

    def cancel():
        with session_factory()() as session:
            request_cancel(session, session.get(Run, queued["id"]))
            session.commit()

    async def complete(self, **kwargs):
        assert outcome != "missing_permission", "Inference must not start without permission"
        yield "An observation"
        if outcome == "failed":
            raise ProviderError("Stream failed")
        if outcome == "canceled":
            cancel()
            await asyncio.sleep(1)

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    if outcome == "late_cancel":
        consume = LocalAgentExecutor._consume

        async def late(self, *args, **kwargs):
            result = await consume(self, *args, **kwargs)
            cancel()
            return result

        monkeypatch.setattr(LocalAgentExecutor, "_consume", late)
    if outcome == "missing_permission":
        with session_factory()() as session:
            session.get(Run, queued["id"]).effective_permissions = []
            session.commit()
    if outcome == "write_failed":

        def fail_write(*args, **kwargs):
            upsert_memory(*args, **kwargs)
            raise RuntimeError("Storage failed after flush")

        monkeypatch.setattr("app.agent_executor.upsert_memory", fail_write)
    with session_factory()() as session:
        drain(session, "memory-test")
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == ("canceled" if "cancel" in outcome else "failed")
    assert "memory_entry_id" not in run["metadata"]
    with session_factory()() as session:
        assert list(session.scalars(select(MemoryEntry))) == []
        assert session.scalar(text("SELECT count(*) FROM memory_fts")) == 0
    artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
    assert len(artifacts) == (0 if outcome == "missing_permission" else 1)
    if artifacts:
        assert artifacts[0]["metadata"]["partial"] is (outcome != "write_failed")


def test_report_memory_excerpt_and_read_permission_are_independent(monkeypatch):
    report = "Long observation. " * 1000
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs["messages"])
        yield report

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["remember_report"])
    with session_factory()() as session:
        upsert_memory(session, scope="agent", scope_id=agent["id"], content="Do not retrieve this")
        session.commit()
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "memory-test")
    run = workflow_step(api, queued["id"], "report")
    with session_factory()() as session:
        entry = session.scalar(select(MemoryEntry).where(MemoryEntry.source_run_id == run["id"]))
        assert len(entry.content) == 12000 and "[Excerpt:" in entry.content
    assert "Do not retrieve this" not in str(received[0])
    assert run["status"] == "succeeded" and run["metadata"]["memory_excerpted"] is True
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert api.get(f"/api/artifacts/{artifact['id']}/file").text == report


def test_workflow_memory_stores_observations_not_search_or_reports(monkeypatch):
    from app.runner_client import RunnerClient

    monkeypatch.setattr(RunnerClient, "hardware", lambda self: {"ok": True, "gpus": []})

    async def complete(self, **kwargs):
        yield "Report without retention"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot", "memory_search", "remember_workflow"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "memory-test")
    snapshot = workflow_step(api, queued["id"], "system_snapshot")
    search = workflow_step(api, queued["id"], "memory_search")
    report = workflow_step(api, queued["id"], "report")
    assert snapshot["status"] == "succeeded"
    assert snapshot["metadata"]["memory_entry_id"]
    assert "memory_entry_id" not in search["metadata"]
    assert "memory_entry_id" not in report["metadata"]
    parent = api.get("/api/runs/" + queued["id"]).json()
    saved = next(item for item in parent["workflow"]["steps"] if item["key"] == "system_snapshot")
    assert saved["memory_id"] == snapshot["metadata"]["memory_entry_id"]
    with session_factory()() as session:
        entries = list(session.scalars(select(MemoryEntry)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.scope == "agent" and entry.scope_id == agent["id"]
        assert entry.source_run_id == snapshot["id"]
        assert entry.tags == ["agent-workflow", "system_snapshot"]
        assert '"ok": true' in entry.content
        from app.agent_executor import persist_agent_memory

        persist_agent_memory(
            session,
            session.get(Run, snapshot["id"]),
            "Duplicate",
            tags=["agent-workflow", "system_snapshot"],
            tool="remember_workflow",
            excerpt_notice="",
        )
        assert len(list(session.scalars(select(MemoryEntry)))) == 1


@pytest.mark.parametrize("outcome", ["failed", "missing_permission", "write_failed"])
def test_unsuccessful_workflow_step_never_retains_memory(monkeypatch, outcome):
    from app.runner_client import RunnerClient

    called = []

    def hardware(self):
        called.append(True)
        if outcome == "failed":
            raise RuntimeError("host down")
        return {"ok": True}

    monkeypatch.setattr(RunnerClient, "hardware", hardware)

    async def complete(self, **kwargs):
        yield "unused"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot", "remember_workflow"])
    queued = run_now(api, agent)
    if outcome == "missing_permission":
        with session_factory()() as session:
            session.get(Run, queued["id"]).effective_permissions = []
            session.commit()
    if outcome == "write_failed":

        def fail_write(*args, **kwargs):
            upsert_memory(*args, **kwargs)
            raise RuntimeError("Storage failed after flush")

        monkeypatch.setattr("app.agent_executor.upsert_memory", fail_write)
    with session_factory()() as session:
        drain(session, "memory-test")
    snapshot = workflow_step(api, queued["id"], "system_snapshot")
    assert snapshot["status"] == "failed"
    assert "memory_entry_id" not in snapshot["metadata"]
    assert (not called) is (outcome == "missing_permission")
    with session_factory()() as session:
        assert list(session.scalars(select(MemoryEntry))) == []
        assert session.scalar(text("SELECT count(*) FROM memory_fts")) == 0


def test_workflow_memory_excerpts_oversized_observations(monkeypatch):
    from app.runner_client import RunnerClient

    payload = {"blob": "N" * 15000}
    monkeypatch.setattr(RunnerClient, "hardware", lambda self: payload)

    async def complete(self, **kwargs):
        yield "ok"

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["system_snapshot", "remember_workflow"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session, "memory-test")
    snapshot = workflow_step(api, queued["id"], "system_snapshot")
    with session_factory()() as session:
        entry = session.scalar(select(MemoryEntry).where(MemoryEntry.source_run_id == snapshot["id"]))
        assert len(entry.content) == 12000 and "[Excerpt:" in entry.content
    assert snapshot["status"] == "succeeded" and snapshot["metadata"]["memory_excerpted"] is True
    artifact = api.get("/api/artifacts?run_id=" + snapshot["id"]).json()[0]
    assert '"blob"' in api.get(f"/api/artifacts/{artifact['id']}/file").text


RAW_REPORT_REQUEST = """I'll gather more concrete details from public GitHub sources.
<tool_call>
<function=web_search>
<parameter=query>
llama.cpp release notes b4892 June 2026 changelog
</parameter>
</function>
</tool_call>"""


@pytest.mark.parametrize("bounded", [False, True])
def test_raw_report_requests_get_one_tool_free_correction(research, monkeypatch, bounded):
    from app.agent_executor import LocalAgentExecutor

    calls, _ = research
    received, deadlines = [], []
    consume = LocalAgentExecutor._consume

    async def observed(self, session, run, definition, deadline, **kwargs):
        deadlines.append(deadline)
        return await consume(self, session, run, definition, deadline, **kwargs)

    async def stream(self, **kwargs):
        received.append(kwargs)
        if len(received) == 1:
            yield RAW_REPORT_REQUEST
        else:
            assert kwargs["tools"] is None and kwargs["on_tool_calls"] is None
            assert "No further tool requests" in kwargs["messages"][0]["content"]
            assert "Public finding" in str(kwargs["messages"])
            yield "# Report\n\nPublic finding. [Source](https://example.com/research)"

    monkeypatch.setattr(LocalAgentExecutor, "_consume", observed)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(
        api,
        enabled=True,
        tools=["web_search", "remember_report"],
        search_query="llama.cpp latest updates news",
        tool_calling="bounded" if bounded else "none",
    )
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded", run
    assert calls == ["llama.cpp latest updates news"]  # No model-invented search was dispatched.
    assert len(received) == 2 and deadlines[0] == deadlines[1]
    execution = run["parameters"]["report_execution"]
    assert all(execution["context_prepared_at"] in frame["messages"][0]["content"] for frame in received)
    events = api.get(f"/api/runs/{run['id']}/stream").text
    assert events.count('"event_type": "agent.report.correction_requested"') == 1
    artifacts = api.get("/api/artifacts?run_id=" + run["id"]).json()
    assert len(artifacts) == 1 and artifacts[0]["metadata"]["partial"] is False
    assert artifacts[0]["metadata"]["report_execution"] == execution
    report = api.get(f"/api/artifacts/{artifacts[0]['id']}/file").text
    assert report.startswith("# Report") and "<tool_call>" not in report
    with session_factory()() as session:
        entry = session.scalar(select(MemoryEntry))
        assert entry.content == report and entry.source_run_id == run["id"]


@pytest.mark.parametrize("response", [RAW_REPORT_REQUEST, "", "<function=web_search>again</function>"])
def test_invalid_report_correction_never_succeeds_or_retains_memory(monkeypatch, response):
    received = []

    async def stream(self, **kwargs):
        received.append(kwargs)
        yield RAW_REPORT_REQUEST if len(received) == 1 else response

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["remember_report"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "failed" and len(received) == 2
    assert api.get("/api/artifacts?run_id=" + run["id"]).json() == []
    with session_factory()() as session:
        assert session.scalar(select(MemoryEntry)) is None


def test_stop_during_report_correction_closes_stream_without_retention(monkeypatch):
    received, closed = [], []

    async def stream(self, **kwargs):
        received.append(kwargs)
        if len(received) == 1:
            yield RAW_REPORT_REQUEST
            return
        try:
            with session_factory()() as session:
                request_cancel(session, session.scalar(select(Run).where(Run.executor_type == "agent")))
                session.commit()
            await asyncio.sleep(30)
            yield "never"
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["remember_report"])
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "canceled" and len(received) == 2 and closed == [True]
    assert api.get("/api/artifacts?run_id=" + run["id"]).json() == []
    with session_factory()() as session:
        assert session.scalar(select(MemoryEntry)) is None


@pytest.mark.parametrize("fence,close", [("```xml", "```"), ("~~~~xml", "~~~~~")])
def test_fenced_tool_protocol_examples_remain_valid_reports(monkeypatch, fence, close):
    received = []
    report = f"Protocol example:\n{fence}\n<tool_call>example</tool_call>\n{close}\nEnd of example."

    async def stream(self, **kwargs):
        received.append(kwargs)
        yield report

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    queued = run_now(api, create(api, enabled=True))
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded" and len(received) == 1
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert api.get(f"/api/artifacts/{artifact['id']}/file").text == report
