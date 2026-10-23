import asyncio
import time
from types import SimpleNamespace

import pytest
from app import agent_search_pages, http_fetch, web_search
from app.agent_executor import execute_context_tool
from app.agent_schema import AgentSettings
from app.agent_tools import calling_tools, parse_tool_call
from app.api import app
from app.config import clear_settings_cache, get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Artifact, MemoryEntry, Run, RunDependency
from app.paths import safe_join
from app.providers import ProviderError
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agents import create, drain, run_now, workflow_step


@pytest.fixture
def research_pages(monkeypatch):
    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    state = {"searches": [], "fetches": [], "messages": [], "deadlines": [], "fail": set()}
    state["sources"] = [
        {"id": i + 1, "title": "Source", "url": url, "snippet": "Search snippet only"}
        for i, url in enumerate(
            [
                "https://one.example.com/release",
                "http://127.0.0.1/secret",
                "https://one.example.com/release",
                "https://two.example.com/news",
                "https://three.example.com/updates",
            ]
        )
    ]

    async def search(query):
        state["searches"].append(query)
        return {
            "query": query,
            "provider": "searxng",
            "searched_at": utcnow().isoformat(),
            "partial": False,
            "sources": state["sources"],
        }

    async def fetch(url):
        state["fetches"].append(url)
        if url in state["fail"]:
            raise ProviderError("Public source is temporarily unavailable")
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "text": "Actual full page content: " + url,
            "links": ["https://not-selected.example.com/"],
            "truncated": False,
            "bounded": True,
            "untrusted": True,
        }

    async def stream(self, **kwargs):
        state["messages"].append(kwargs["messages"])
        yield "Report from actually read excerpts. [Source](https://one.example.com/release)"

    original = agent_search_pages.execute_fetch

    async def observed_fetch(*args, **kwargs):
        state["deadlines"].append(kwargs["deadline"])
        return await original(*args, **kwargs)

    state["real_fetch"] = http_fetch.fetch_public
    monkeypatch.setattr(web_search, "search", search)
    monkeypatch.setattr(http_fetch, "fetch_public", fetch)
    monkeypatch.setattr(agent_search_pages, "execute_fetch", observed_fetch)
    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return state


def queued_pages(api, **extra):
    values = {
        "enabled": True,
        "tools": ["search_pages", "web_search"],
        "search_query": "public release notes",
        **extra,
    }
    agent = create(api, **values)
    return agent, run_now(api, agent)


def published_search(api):
    agent, queued = queued_pages(api)
    with session_factory()() as session:
        tick(session, "page-test")  # Publish normal children.
        tick(session, "page-test")  # Persist actual search observation.
    return agent, queued, workflow_step(api, queued["id"], "search_pages")


def test_search_then_read_then_report_binds_urls_artifacts_and_deadline(research_pages):
    api = TestClient(app)
    agent, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    search = workflow_step(api, queued["id"], "web_search")
    pages = workflow_step(api, queued["id"], "search_pages")
    report = workflow_step(api, queued["id"], "report")
    assert search["status"] == pages["status"] == report["status"] == "succeeded"
    state = research_pages
    assert state["searches"] == ["public release notes"]
    assert state["fetches"] == [
        "https://one.example.com/release",
        "https://two.example.com/news",
        "https://three.example.com/updates",
    ]
    assert len(set(state["deadlines"])) == 1
    assert (
        search["parameters"]["deadline_at"]
        == pages["parameters"]["deadline_at"]
        == report["parameters"]["deadline_at"]
    )
    observation = pages["metadata"]["search_pages"]
    assert not observation["partial"] and observation["search_run_id"] == search["id"]
    assert pages["retry_class"] == "inspect" and pages["effective_permissions"] == ["network_read"]
    assert report["metadata"]["search_pages"] == observation
    assert "Actual full page content" in str(state["messages"])
    assert "not-selected.example.com" not in str(state["messages"])
    assert "failed/skipped sources" in state["messages"][0][0]["content"]
    saved = next(
        a
        for a in api.get("/api/artifacts?run_id=" + pages["id"]).json()
        if a["metadata"].get("tool") == "search_pages"
    )
    assert len(saved["parent_artifact_ids"]) == 4
    assert saved["parent_artifact_ids"][0] == observation["search_artifact_id"]
    payload = api.get(f"/api/artifacts/{saved['id']}/file").json()
    assert payload["pages"][0]["source_artifact_id"] in saved["parent_artifact_ids"]
    assert payload["query"] == agent["search_query"]


@pytest.mark.parametrize(
    "mutation",
    [
        "permission",
        "parent",
        "definition",
        "dependency",
        "manifest",
        "source_status",
        "query",
        "hash",
        "artifact_owner",
        "trashed",
        "oversize",
    ],
)
def test_invalid_search_scope_fails_before_any_page_read(research_pages, mutation):
    api = TestClient(app)
    _, queued, pages = published_search(api)
    with session_factory()() as session:
        run = session.get(Run, pages["id"])
        source = session.scalar(
            select(Run).where(
                Run.parent_run_id == queued["id"], Run.parameters["tool"].as_string() == "web_search"
            )
        )
        parent = session.get(Run, queued["id"])
        artifact = session.get(Artifact, source.metadata_json["observation"]["artifact_id"])
        if mutation == "permission":
            run.effective_permissions = []
        elif mutation == "parent":
            run.parent_run_id = source.id  # A different parent cannot grant a search source.
        elif mutation == "definition":
            source.parameters = {
                **source.parameters,
                "definition": {**source.parameters["definition"], "goal": "Unreviewed"},
            }
        elif mutation == "dependency":
            session.delete(session.get(RunDependency, (run.id, source.id)))
        elif mutation == "manifest":
            parent.metadata_json = {**parent.metadata_json, "child_run_ids": []}
        elif mutation == "source_status":
            source.status = "failed"
        elif mutation == "query":
            source.metadata_json = {
                **source.metadata_json,
                "observation": {
                    **source.metadata_json["observation"],
                    "query": "Unreviewed private question",
                },
            }
        elif mutation == "hash":
            safe_join(get_settings().data_dir, artifact.relative_path).write_text("{}")
        elif mutation == "artifact_owner":
            artifact.run_id = parent.id
        elif mutation == "trashed":
            artifact.trashed_at = utcnow()
        elif mutation == "oversize":
            artifact.size_bytes = agent_search_pages.MAX_SOURCE_BYTES + 1
        run.status = "claimed"  # Simulate worker claim before direct tamper-boundary inspection.
        session.commit()
        from app.agent_workflow import AgentToolExecutor

        AgentToolExecutor().execute(session, run)
        session.commit()
    result = api.get("/api/runs/" + pages["id"]).json()
    assert result["status"] == "failed" and not research_pages["fetches"]
    assert not research_pages["messages"]
    assert not any(
        a["metadata"].get("tool") == "search_pages"
        for a in api.get("/api/artifacts?run_id=" + pages["id"]).json()
    )


def test_one_unavailable_source_keeps_other_actual_pages_and_error_provenance(research_pages):
    research_pages["fail"].add("https://two.example.com/news")
    api = TestClient(app)
    _, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    pages = workflow_step(api, queued["id"], "search_pages")
    assert pages["status"] == "succeeded"
    value = pages["metadata"]["search_pages"]
    assert value["partial"] and len(value["pages"]) == 2 and len(value["errors"]) == 1
    assert value["errors"][0]["url"] == "https://two.example.com/news"
    assert "temporarily unavailable" in str(research_pages["messages"])


def test_stop_closes_pending_fetch_and_never_runs_report_or_retains(research_pages, monkeypatch):
    closed = []

    async def pending(url):
        with session_factory()() as session:
            run = session.scalar(select(Run).where(Run.parameters["tool"].as_string() == "search_pages"))
            request_cancel(session, run)
            session.commit()
        try:
            await asyncio.sleep(30)
        finally:
            closed.append(url)

    monkeypatch.setattr(http_fetch, "fetch_public", pending)
    api = TestClient(app)
    _, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    assert workflow_step(api, queued["id"], "search_pages")["status"] == "canceled"
    assert len(closed) == 1 and not research_pages["messages"]
    with session_factory()() as session:
        assert session.scalar(select(MemoryEntry)) is None


def test_deadline_after_first_page_does_not_fetch_or_publish_more(research_pages, monkeypatch):
    clock = time.monotonic
    monkeypatch.setattr(
        agent_search_pages,
        "time",
        SimpleNamespace(monotonic=lambda: clock() + (10000 if research_pages["fetches"] else 0)),
    )
    api = TestClient(app)
    _, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    pages = workflow_step(api, queued["id"], "search_pages")
    assert pages["status"] == "failed" and "runtime limit" in pages["error_message"]
    assert len(research_pages["fetches"]) == 1 and not research_pages["messages"]


def test_selected_search_pages_is_not_a_model_callable_url_tool(research_pages):
    definition = AgentSettings(
        name="Research", goal="Research", tools=["web_search", "search_pages"], search_query="public notes"
    )
    assert {item["function"]["name"] for item in calling_tools(definition)} == {"web_search"}
    with pytest.raises(ValueError):
        parse_tool_call(
            definition, {"name": "search_pages", "arguments": '{"url":"https://invented.example.com"}'}
        )
    with pytest.raises(ValueError, match="requires web_search"):
        AgentSettings(name="Research", goal="Research", tools=["search_pages"])


def test_model_cannot_inject_source_urls(research_pages):
    definition = AgentSettings(
        name="Research", goal="Research", tools=["web_search", "search_pages"], search_query="public notes"
    )
    with pytest.raises(ValueError, match="cannot be supplied"):
        execute_context_tool(
            None,
            SimpleNamespace(effective_permissions=["network_read"]),
            definition,
            "search_pages",
            time.monotonic() + 60,
            arguments={"url": "https://invented.example.com"},
        )
    assert not research_pages["fetches"]


def test_search_pages_preserves_real_http_ssrf_checks(research_pages, monkeypatch):
    import socket

    research_pages["sources"] = [
        {"id": 1, "title": "Unsafe DNS", "url": "https://private.example.com/secret", "snippet": "untrusted"}
    ]
    monkeypatch.setattr(http_fetch, "fetch_public", research_pages["real_fetch"])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP connection may be created for private DNS")

    monkeypatch.setattr(http_fetch.httpx, "AsyncClient", forbidden)
    api = TestClient(app)
    _, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    value = workflow_step(api, queued["id"], "search_pages")["metadata"]["search_pages"]
    assert value["partial"] and value["pages"] == [] and len(value["errors"]) == 1
    assert not research_pages["fetches"]


def test_source_excerpts_and_model_context_are_bounded(research_pages, monkeypatch):
    async def huge(url):
        return {
            "url": url,
            "status": 200,
            "content_type": "text/plain",
            "text": "ą" * 10000,
            "links": [],
            "truncated": False,
            "untrusted": True,
        }

    monkeypatch.setattr(http_fetch, "fetch_public", huge)
    api = TestClient(app)
    _, queued = queued_pages(api)
    with session_factory()() as session:
        drain(session)
    value = workflow_step(api, queued["id"], "search_pages")["metadata"]["search_pages"]
    import json

    assert len(json.dumps(value, ensure_ascii=False)) <= agent_search_pages.MAX_RESULT_CHARS
    assert all(len(page["text"]) <= 2000 and page["truncated"] for page in value["pages"])


def test_successful_page_observation_retains_only_own_provenance(research_pages):
    api = TestClient(app)
    agent, queued = queued_pages(api, tools=["search_pages", "web_search", "remember_workflow"])
    with session_factory()() as session:
        drain(session)
    pages = workflow_step(api, queued["id"], "search_pages")
    with session_factory()() as session:
        entry = session.get(MemoryEntry, pages["metadata"]["memory_entry_id"])
        assert entry.scope == "agent" and entry.scope_id == agent["id"]
        assert entry.source_run_id == pages["id"] and entry.tags == ["agent-workflow", "search_pages"]
        assert "search_artifact_id" in entry.content
