"""Market agents use real workflow/worker contracts with deterministic synthetic quotes."""

import json
from datetime import timedelta

import pytest
from app.agent_schema import AgentSettings
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.market_schema import MarketScope
from app.market_watch import STEPS, compare, notify, parse_quote, source_url
from app.models import Agent, Artifact, MarketAlert, MarketObservation, Notice, Run
from app.schedule import launch_agent, scheduler_tick
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select


def page(price="100", trade=100, source_at=None, pair="BTC-USD"):
    return {
        "url": source_url(pair),
        "status": 200,
        "content_type": "application/json",
        "truncated": False,
        "text": json.dumps({"price": price, "trade_id": trade, "time": (source_at or utcnow()).isoformat()}),
    }


def setup_agent(session, **scope):
    agent = Agent(
        name="Bitcoin watch",
        goal="Monitor BTC",
        tools=["market_watch"],
        model="",
        enabled=True,
        provider="local-openai-compatible",
        permission_profile="agent_local",
        execution_target="container",
        market=MarketScope(**scope).model_dump(),
        trigger="interval",
        interval_seconds=60,
    )
    session.add(agent)
    session.commit()
    return agent


def complete(session, agent, monkeypatch, response):
    async def fetch(url, **kwargs):
        assert url == source_url("BTC-USD")
        return response

    monkeypatch.setattr("app.http_fetch.fetch_public", fetch)
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    for _ in range(12):
        if not tick(session, "market-test-worker"):
            break
    session.expire_all()
    runs = list(session.scalars(select(Run).where(Run.parent_run_id == rid).order_by(Run.created_at)))
    return runs


def test_factory_proposes_disabled_market_agent_without_gpu_or_model():
    from app.factory import draft_agent

    agent = draft_agent("Codziennie sprawdzaj cenę bitcoina i powiadom gdy zmiana przekroczy 3%")
    assert agent.tools == ["market_watch"] and not agent.enabled
    assert agent.market["threshold_percent"] == "3" and agent.model == ""
    assert agent.cron_expr and agent.market["instruments"] == ["BTC-USD"]


@pytest.mark.parametrize(
    "extra",
    [
        {"threshold_percent": "NaN"},
        {"threshold_percent": "0"},
        {"threshold_percent": "100.1"},
        {"threshold_percent": 5},
        {"threshold_percent": "1e9"},
        {"instruments": ["AAPL"]},
        {"instruments": ["BTC-USD", "BTC-USD"]},
        {"provider": "http://localhost"},
        {"comparison_window_seconds": True},
        {"cooldown_seconds": 0},
        {"url": "http://localhost"},
    ],
)
def test_invalid_market_scopes_fail_closed(extra):
    with pytest.raises(ValidationError):
        MarketScope(**extra)


@pytest.mark.parametrize(
    "price,trade,source_delta",
    [
        ("NaN", 1, 0),
        ("-1", 1, 0),
        ("0", 1, 0),
        ("1e99999", 1, 0),
        (1.5, 1, 0),
        ("1", True, 0),
        ("1", "2", 0),
        ("1", 1, -301),
        ("1", 1, 31),
    ],
)
def test_malformed_stale_future_quotes_cannot_create_observations(price, trade, source_delta):
    now = utcnow()
    with pytest.raises(ValueError):
        parse_quote(page(price, trade, now + timedelta(seconds=source_delta)), "BTC-USD", now=now)


def test_quote_redirect_or_truncation_not_accepted():
    for patch in [
        {"url": "https://other.example/ticker"},
        {"truncated": True},
        {"status": 429},
        {"content_type": "text/html"},
        {"text": "{bad"},
    ]:
        with pytest.raises(ValueError):
            parse_quote({**page(), **patch}, "BTC-USD", now=utcnow())


def test_scope_is_exclusive_and_cannot_be_model_tool():
    for kwargs in [
        {"tools": ["market_watch", "http_fetch"]},
        {"tools": ["market_watch"], "tool_calling": "bounded"},
        {"tools": []},
        {"tools": ["market_watch"], "skills": ["research"]},
    ]:
        with pytest.raises(ValueError):
            AgentSettings(name="Watch", goal="Observe", market={}, **kwargs)
    with pytest.raises(ValueError):
        AgentSettings(name="Watch", goal="Observe", tools=["market_watch"])


def test_first_baseline_threshold_notice_report_and_restart_dedup(session, monkeypatch):
    agent = setup_agent(session, threshold_percent="5")
    now = utcnow()
    first = complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=20)))
    assert [r.parameters["tool"] for r in first] == list(STEPS)
    assert all(r.status == "succeeded" for r in first), [(r.error_message, r.status) for r in first]
    assert first[-1].metadata_json["market_result"]["rows"][0]["status"] == "baseline"
    assert session.scalar(select(func.count()).select_from(Notice)) == 0
    assert not list(session.scalars(select(Run).where(Run.executor_type.in_(["llama_load", "agent"]))))
    second = complete(session, agent, monkeypatch, page("106", 101, now - timedelta(seconds=10)))
    row = second[-1].metadata_json["market_result"]["rows"][0]
    assert row["status"] == "alert" and row["change_percent"] == "6.00000000"
    assert row["baseline_price"] == "100"
    assert session.scalar(select(func.count()).select_from(Notice)) == 1
    assert session.scalar(
        select(Artifact).where(Artifact.run_id == second[-1].id, Artifact.artifact_type == "markdown")
    )
    # Repeated delivery within the source-bound stage is idempotent.
    definition = AgentSettings.model_validate(second[2].parameters["definition"])
    assert (
        notify(session, second[2], definition)["notice_ids"]
        == second[-1].metadata_json["market_result"]["notice_ids"]
    )
    session.commit()
    aid = agent.id
    session.close()
    with session_factory()() as reopened:
        agent = reopened.get(Agent, aid)
        repeated = complete(reopened, agent, monkeypatch, page("106", 101, now - timedelta(seconds=10)))
        assert repeated[-1].metadata_json["market_result"]["rows"][0]["status"] == "repeated"
        assert reopened.scalar(select(func.count()).select_from(Notice)) == 1
        assert reopened.scalar(select(func.count()).select_from(MarketObservation)) == 2
        assert repeated[-1].metadata_json["market_result"]["email_sent"] is False


def test_bad_quote_and_correction_do_not_poison_baseline(session, monkeypatch):
    agent = setup_agent(session)
    t = utcnow() - timedelta(seconds=25)
    complete(session, agent, monkeypatch, page("100", 100, t))
    for bad in [page("NaN", 101), page("200", 101, t - timedelta(minutes=10)), page("200", 100, t)]:
        runs = complete(session, agent, monkeypatch, bad)
        assert runs[0].status == "failed" and all(r.status != "succeeded" for r in runs[1:])
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 1
    assert session.scalar(select(func.count()).select_from(MarketAlert)) == 0


@pytest.mark.parametrize(
    "scope,expected",
    [
        ({"direction": "down"}, "below_threshold"),
        ({"comparison_window_seconds": 60}, "baseline_expired"),
        ({}, "alert"),
    ],
)
def test_direction_and_maximum_gap(session, monkeypatch, scope, expected):
    agent = setup_agent(session, **scope)
    now = utcnow()
    complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=100)))
    runs = complete(session, agent, monkeypatch, page("110", 101, now))
    assert runs[-1].metadata_json["market_result"]["rows"][0]["status"] == expected


def test_no_change_out_of_order_cooldown_and_changed_policy(session, monkeypatch):
    agent = setup_agent(session)
    now = utcnow()
    complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=50)))
    stable = complete(session, agent, monkeypatch, page("100", 101, now - timedelta(seconds=40)))
    assert stable[-1].metadata_json["market_result"]["rows"][0]["status"] == "below_threshold"
    complete(session, agent, monkeypatch, page("110", 102, now - timedelta(seconds=30)))
    order = complete(session, agent, monkeypatch, page("50", 99, now - timedelta(seconds=60)))
    assert order[-1].metadata_json["market_result"]["rows"][0]["status"] == "out_of_order"
    cooling = complete(session, agent, monkeypatch, page("200", 103, now - timedelta(seconds=10)))
    assert cooling[-1].metadata_json["market_result"]["rows"][0]["status"] == "cooldown"
    assert session.scalar(select(func.count()).select_from(Notice)) == 1
    agent.market = {**agent.market, "threshold_percent": "10"}
    session.commit()
    changed = complete(session, agent, monkeypatch, page("300", 104, now))
    assert changed[-1].metadata_json["market_result"]["rows"][0]["status"] == "baseline"


def test_agents_cannot_share_baselines(session, monkeypatch):
    a = setup_agent(session)
    complete(session, a, monkeypatch, page("100", 100, utcnow() - timedelta(seconds=10)))
    b = setup_agent(session)
    runs = complete(session, b, monkeypatch, page("200", 101))
    assert runs[-1].metadata_json["market_result"]["rows"][0]["status"] == "baseline"


def test_plan_tampering_and_missing_permission_fail_closed(session, monkeypatch):
    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    parent = session.get(Run, rid)
    parent.parameters = {**parent.parameters, "steps": [{"key": "market.notify", "gate": "none"}]}
    session.commit()
    tick(session, "market-worker")
    assert session.get(Run, rid).status == "failed"
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    tick(session, "market-worker")
    quote = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.quote")
    )
    quote.effective_permissions = []
    session.commit()
    tick(session, "market-worker")
    assert session.get(Run, quote.id).status == "failed"
    assert "network_read" in quote.error_message


def test_scheduler_and_api_roundtrip_no_model_required(session):
    with TestClient(app) as api:
        response = api.post(
            "/api/agents",
            json={
                "name": "BTC",
                "goal": "Observe",
                "tools": ["market_watch"],
                "market": {},
                "enabled": True,
                "trigger": "interval",
                "interval_seconds": 60,
            },
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["market"]["instruments"] == ["BTC-USD"]
        row = session.get(Agent, saved["id"])
        row.next_run_at = utcnow() - timedelta(seconds=1)
        session.commit()
        assert len(scheduler_tick(session)) == 1
        session.commit()
        parent = session.scalar(select(Run).where(Run.agent_id == row.id))
        assert parent.triggered_by == "scheduler" and parent.parameters["endpoint"] == ""
        session.commit()
        # Versioned settings retain scope, and duplicates remain disabled.
        duplicated = api.post(
            f"/api/agents/{row.id}/duplicate", json={"expected_updated_at": saved["updated_at"]}
        )
        assert duplicated.status_code == 201, duplicated.text
        assert not duplicated.json()["enabled"] and duplicated.json()["market"] == saved["market"]


def test_stop_before_network_prevents_fetch(session, monkeypatch):
    from app.runs import request_cancel

    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    tick(session, "market-worker")
    parent = session.get(Run, rid)
    request_cancel(session, parent)
    session.commit()
    for _ in range(8):
        if not tick(session, "market-worker"):
            break
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 0
    assert session.scalar(select(func.count()).select_from(Notice)) == 0


def test_migration_preserves_agents_and_has_no_implicit_market_scope(session):
    from alembic import command
    from app.db import alembic_config

    row = Agent(name="Keep me", goal="Original", tools=[])
    session.add(row)
    session.commit()
    aid = row.id
    command.downgrade(alembic_config(), "0028")
    command.upgrade(alembic_config(), "head")
    session.expire_all()
    assert session.get(Agent, aid).market is None
    assert session.get(Agent, aid).goal == "Original"


def test_stop_during_quote_cancels_request_without_committing_observation(session, monkeypatch):
    import asyncio

    from app.runs import request_cancel

    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    tick(session, "market-worker")
    quote = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.quote")
    )
    session.commit()
    canceled = []

    async def fetch(url, **kwargs):
        request_cancel(session, quote)
        session.commit()
        try:
            await asyncio.sleep(30)
        finally:
            canceled.append(True)

    monkeypatch.setattr("app.http_fetch.fetch_public", fetch)
    tick(session, "market-worker")
    assert canceled and session.get(Run, quote.id).status == "canceled"
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 0
    assert session.scalar(select(func.count()).select_from(Notice)) == 0


def test_expired_worker_does_not_reexecute_quote_or_repeat_notification(session):
    from app.recovery import recover_stale
    from app.runs import transition
    from app.state import RunStatus

    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    tick(session, "market-worker")
    quote = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.quote")
    )
    transition(session, quote, RunStatus.CLAIMED, event_type="run.claimed")
    transition(session, quote, RunStatus.PREPARING, event_type="executor.preparing")
    transition(session, quote, RunStatus.RUNNING, event_type="executor.started")
    quote.lease_expires_at = utcnow() - timedelta(seconds=5)
    session.commit()

    class Runner:
        def inspect_process(self, run_id):
            return {"alive": False, "known": False}

    assert quote.id in recover_stale(session, Runner())
    session.commit()
    assert session.get(Run, quote.id).status == "interrupted"
    assert session.get(Run, quote.id).retry_class == "inspect"
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 0


def test_comparison_and_notification_drop_a_quote_that_aged_in_queue(session, monkeypatch):
    agent = setup_agent(session)
    now = utcnow()
    complete(session, agent, monkeypatch, page("100", 100, now - timedelta(seconds=20)))
    runs = complete(session, agent, monkeypatch, page("110", 101, now - timedelta(seconds=10)))
    definition = AgentSettings.model_validate(runs[1].parameters["definition"])
    monkeypatch.setattr("app.market_watch.utcnow", lambda: now + timedelta(seconds=400))
    assert compare(session, runs[1], definition)["rows"][0]["status"] == "stale"
    # Confirmed notices remain exactly once, even if an old stage is inspected again.
    assert len(notify(session, runs[2], definition)["notice_ids"]) == 1
    assert session.scalar(select(func.count()).select_from(Notice)) == 1


def test_failed_workflow_emits_one_failure_notice_not_one_per_stage(session, monkeypatch):
    agent = setup_agent(session)
    agent.notification_policy = {"on_failure": True}
    session.commit()
    runs = complete(session, agent, monkeypatch, {**page(), "status": 503})
    assert runs[-1].status == "failed"
    assert session.scalar(select(func.count()).select_from(Notice)) == 1
    assert session.get(Agent, agent.id).failure_count == 1


def test_workflow_cannot_restore_withdrawn_parent_network_permission(session):
    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    parent = session.get(Run, rid)
    parent.effective_permissions = []
    session.commit()
    tick(session, "market-worker")
    assert session.get(Run, rid).status == "failed"
    assert "network_read" in parent.error_message
    assert not list(session.scalars(select(Run).where(Run.parent_run_id == rid)))


def test_default_gap_allows_daily_schedule_and_network_jitter(session, monkeypatch):
    agent = setup_agent(session)
    now = utcnow()
    yesterday = now - timedelta(days=1, seconds=15)
    monkeypatch.setattr("app.market_watch.utcnow", lambda: yesterday)
    complete(session, agent, monkeypatch, page("100", 100, yesterday))
    monkeypatch.setattr("app.market_watch.utcnow", lambda: now)
    runs = complete(session, agent, monkeypatch, page("110", 101, now))
    assert runs[-1].metadata_json["market_result"]["rows"][0]["status"] == "alert"
    assert agent.market["comparison_window_seconds"] == 172800
