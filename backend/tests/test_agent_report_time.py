import json
from datetime import datetime, timedelta, timezone

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.local_provider import LocalChatProvider
from app.models import Agent, Run
from app.schedule import launch_agent, scheduler_tick
from fastapi.testclient import TestClient
from test_agents import create, drain, run_now, workflow_step


@pytest.mark.parametrize("triggered_by", ["user", "scheduler", "retry"])
def test_report_uses_recorded_execution_not_the_planned_cron_time(monkeypatch, triggered_by):
    received = []

    async def report(self, **kwargs):
        received.append(kwargs["messages"])
        yield "Report based on recorded execution and available observations."

    monkeypatch.setattr(LocalChatProvider, "stream", report)
    api = TestClient(app)
    agent = create(api, enabled=True, trigger="cron", cron_expr="0 8 * * *")
    before = utcnow()
    if triggered_by == "user":
        queued = run_now(api, agent)
    else:
        with session_factory()() as session:
            row = session.get(Agent, agent["id"])
            if triggered_by == "scheduler":
                row.next_run_at = utcnow() - timedelta(seconds=1)
                session.commit()
                ids = scheduler_tick(session)
                assert len(ids) == 1
                root_id = ids[0]
            else:
                root_id = launch_agent(session, row, triggered_by="retry")
            session.commit()
            queued = {"id": root_id}
    with session_factory()() as session:
        drain(session)
    after = utcnow()
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded", run
    execution = run["parameters"]["report_execution"]
    assert execution["run_id"] == run["id"]
    assert execution["workflow_run_id"] == queued["id"]
    assert execution["triggered_by"] == triggered_by
    assert execution["timezone"] == "UTC"
    prepared = datetime.fromisoformat(execution["context_prepared_at"])
    assert prepared.utcoffset() == timedelta(0) and before <= prepared <= after
    assert execution["saved_schedule"] == {
        "trigger": "cron",
        "cron_expr": "0 8 * * *",
        "interval_seconds": None,
        "run_at": None,
        "planned_only": True,
    }
    system = received[0][0]["content"]
    assert json.dumps(execution, ensure_ascii=False) in system
    assert "triggered_by=user means a manual run" in system
    assert "Never substitute a cron time" in system
    with session_factory()() as session:
        row = session.get(Run, run["id"])
        assert execution["run_created_at"] == row.created_at.isoformat()
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert artifact["metadata"]["report_execution"] == execution
    assert artifact["metadata"]["partial"] is False


def test_current_execution_does_not_redate_old_source_observations(monkeypatch):
    from app import web_search
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://search:8080")
    clear_settings_cache()
    observed = "2020-01-02T09:00:00+00:00"
    received = []

    async def search(query):
        return {
            "query": query,
            "searched_at": observed,
            "provider": "searxng",
            "partial": False,
            "sources": [
                {
                    "id": 1,
                    "title": "Historical release",
                    "url": "https://example.com/release",
                    "snippet": "Old release",
                }
            ],
        }

    async def report(self, **kwargs):
        received.append(kwargs["messages"])
        yield "Historical source observation; its freshness is not established by this Run."

    monkeypatch.setattr(web_search, "search", search)
    monkeypatch.setattr(LocalChatProvider, "stream", report)
    api = TestClient(app)
    agent = create(api, enabled=True, tools=["web_search"], search_query="public history")
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded"
    execution = run["parameters"]["report_execution"]
    assert datetime.fromisoformat(execution["context_prepared_at"]) > datetime(
        2020, 1, 2, tzinfo=timezone.utc
    )
    assert run["metadata"]["web_search"]["searched_at"] == observed
    assert observed in received[0][1]["content"]
    assert "publication times separate" in received[0][0]["content"]


def test_partial_failed_report_keeps_actual_execution_provenance_without_memory(monkeypatch):
    from app.models import MemoryEntry
    from app.providers import ProviderError
    from sqlalchemy import select

    async def report(self, **kwargs):
        yield "Incomplete report"
        raise ProviderError("Provider stream failed")

    monkeypatch.setattr(LocalChatProvider, "stream", report)
    api = TestClient(app)
    queued = run_now(api, create(api, enabled=True, tools=["remember_report"]))
    with session_factory()() as session:
        drain(session)
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "failed"
    artifact = api.get("/api/artifacts?run_id=" + run["id"]).json()[0]
    assert artifact["metadata"]["partial"] is True
    assert artifact["metadata"]["report_execution"] == run["parameters"]["report_execution"]
    with session_factory()() as session:
        assert session.scalar(select(MemoryEntry)) is None
