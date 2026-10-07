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
from app.models import Agent, MemoryEntry, Run
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
        tick(session, "agent-test")
    run = api.get("/api/runs/" + queued["id"]).json()
    assert run["status"] == "succeeded"
    assert "Relevant observation" in str(received[0]["messages"])
    assert "PRIVATE OTHER AGENT" not in str(received[0]["messages"])
    assert run["effective_permissions"] == []
    assert run["parameters"]["tool_context"][0]["tool"] == "memory_search"
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert artifact["type"] == "markdown" and artifact["metadata"]["partial"] is False
    reset_engine()
    saved = api.get("/api/agents/" + agent["id"]).json()
    assert saved["last_status"] == "succeeded" and saved["failure_count"] == 0
    assert saved["runs"][0]["id"] == queued["id"]


def test_failure_is_not_reported_as_success(monkeypatch):
    async def fail(self, **kwargs):
        yield "Partial observation"
        raise ProviderError("Unavailable provider")

    monkeypatch.setattr(LocalChatProvider, "stream", fail)
    api = TestClient(app)
    agent = create(api, enabled=True)
    queued = run_now(api, agent)
    with session_factory()() as session:
        tick(session, "agent-test")
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"
    assert api.get("/api/agents/" + agent["id"]).json()["failure_count"] == 1
    assert api.get("/api/artifacts?run_id=" + queued["id"]).json()[0]["metadata"]["partial"] is True


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
        tick(session, "agent-test")
    assert closed
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "canceled"
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
        tick(session, "agent-test")
    assert not called
    assert api.get("/api/runs/" + queued["id"]).json()["status"] == "failed"


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
            tick(session, "research-test")
        run = api.get("/api/runs/" + run_id).json()
        assert run["status"] == "succeeded", run
        assert run["effective_permissions"] == ["network_read"]
        assert calls == ["public model releases"]
        assert "PRIVATE GOAL" in str(messages) and "Public finding" in str(messages)
        assert run["metadata"]["web_search"]["sources"][0]["url"] == "https://example.com/research"
        artifacts = api.get("/api/artifacts?run_id=" + run_id).json()
        assert {item["type"] for item in artifacts} == {"markdown", "json"}
        reset_engine()
        assert api.get("/api/runs/" + run_id).json()["metadata"]["web_search"]["query"] == calls[0]
        assert "tool.completed" in api.get("/api/runs/" + run_id + "/stream").text


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
            tick(session, "research-negative")
        result = api.get("/api/runs/" + run_id).json()
        assert result["status"] == ("canceled" if mode == "cancel" else "failed"), result
        assert not research[1]
        if mode in {"cancel", "timeout"}:
            assert closed
        assert api.get("/api/artifacts?run_id=" + run_id).json() == []


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


def test_agent_search_migration_preserves_existing_definitions():
    from alembic import command
    from app.db import alembic_config

    with TestClient(app) as api:
        agent = create(api, tools=["memory_search"])
        command.downgrade(alembic_config(), "0005")
        command.upgrade(alembic_config(), "head")
        saved = api.get("/api/agents/" + agent["id"]).json()
        assert saved["goal"] == agent["goal"] and saved["tools"] == ["memory_search"]
        assert saved["search_query"] == ""


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
        tick(session, "memory-test")
    run = api.get("/api/runs/" + queued["id"]).json()
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
        tick(session, "memory-test")
    assert ("Retained observation" in str(received[1])) is remember
    other = create(api, name="Different scope", enabled=True, tools=["memory_search"])
    run_now(api, other)
    with session_factory()() as session:
        tick(session, "memory-test")
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

        async def late(self, *args):
            result = await consume(self, *args)
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
        tick(session, "memory-test")
    run = api.get("/api/runs/" + queued["id"]).json()
    assert run["status"] == ("canceled" if "cancel" in outcome else "failed")
    assert "memory_entry_id" not in run["metadata"]
    with session_factory()() as session:
        assert list(session.scalars(select(MemoryEntry))) == []
        assert session.scalar(text("SELECT count(*) FROM memory_fts")) == 0
    artifacts = api.get("/api/artifacts?run_id=" + queued["id"]).json()
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
        tick(session, "memory-test")
        entry = session.scalar(select(MemoryEntry).where(MemoryEntry.source_run_id == queued["id"]))
        assert len(entry.content) == 12000 and "[Excerpt:" in entry.content
    assert "Do not retrieve this" not in str(received[0])
    run = api.get("/api/runs/" + queued["id"]).json()
    assert run["status"] == "succeeded" and run["metadata"]["memory_excerpted"] is True
    artifact = api.get("/api/artifacts?run_id=" + queued["id"]).json()[0]
    assert api.get(f"/api/artifacts/{artifact['id']}/file").text == report
