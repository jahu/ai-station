"""Synthetic stock data through the real queue/compare/notification/email contracts."""

import hashlib
import json
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from app.api import app
from app.db import utcnow
from app.engine import tick
from app.market_feeds import connector_revision
from app.market_schema import MarketScope
from app.market_watch import policy_key
from app.models import Agent, Artifact, Connector, EmailDelivery, MarketAlert, MarketObservation, Notice, Run
from app.schedule import launch_agent
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_market_email import enabled
from test_reviewed_email import Transport


def setup_stock(session, monkeypatch, **scope):
    monkeypatch.setenv("STOCK_FIXTURE_KEY", "fixture-stock-account-token")
    feed = Connector(
        key="stock-feed",
        name="Stock feed",
        kind="market_data",
        enabled=True,
        capabilities=["market.quote"],
        config_json={"provider": "finnhub"},
        secret_ref="env:STOCK_FIXTURE_KEY",
    )
    session.add(feed)
    session.flush()
    market = MarketScope(
        provider="finnhub",
        instruments=["AAPL"],
        feed={"connector_id": feed.id, "connector_revision": connector_revision(feed)},
        **scope,
    )
    agent = Agent(
        name="Stock watch",
        goal="Check AAPL",
        tools=["market_watch"],
        model="",
        enabled=True,
        provider="local-openai-compatible",
        permission_profile="agent_local",
        execution_target="container",
        market=market.model_dump(mode="json"),
        trigger="interval",
        interval_seconds=60,
    )
    session.add(agent)
    session.commit()
    return agent, feed


def install_quotes(
    monkeypatch, *, price=100, at=None, opened=True, symbol="AAPL", currency="USD", capture=None
):
    as_of = at or utcnow() - timedelta(seconds=10)

    async def fetch(url, *, extra_headers):
        if capture is not None:
            capture.append(url)
        assert extra_headers == {"X-Finnhub-Token": "fixture-stock-account-token"}
        if "/market-status?" in url:
            data = {
                "exchange": "US",
                "isOpen": opened,
                "session": "regular" if opened else None,
                "timezone": "America/New_York",
                "t": int(utcnow().timestamp()),
            }
        elif "/profile2?" in url:
            data = {"ticker": symbol, "currency": currency, "name": "Example company", "exchange": "NASDAQ"}
        else:
            data = {"c": price, "t": int(as_of.timestamp())}
        return {
            "url": url,
            "status": 200,
            "content_type": "application/json",
            "truncated": False,
            "text": json.dumps(data),
        }

    monkeypatch.setattr("app.market_feeds.fetch_public", fetch)


def launch(session, agent, *, until=None):
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    for _ in range(16):
        done = tick(session, "stock-workflow-test")
        if done is None:
            break
        if until and session.get(Run, done).parameters.get("tool") == until:
            break
    session.expire_all()
    return rid


def result(session, rid):
    report = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.report")
    )
    assert report.status == "succeeded", report.error_message
    return report.metadata_json["market_result"]


def test_stock_workflow_sets_baseline_and_alerts_without_model_or_gpu(session, monkeypatch):
    agent, _ = setup_stock(session, monkeypatch)
    now = utcnow()
    install_quotes(monkeypatch, at=now - timedelta(seconds=90))
    baseline = result(session, launch(session, agent))
    assert baseline["rows"][0]["status"] == "baseline"
    install_quotes(monkeypatch, price=110, at=now - timedelta(seconds=10))
    rid = launch(session, agent)
    data = result(session, rid)
    row = data["rows"][0]
    assert row["status"] == "alert" and row["change_percent"] == "10.00000000" and row["currency"] == "USD"
    assert row["source_metadata"]["source_time_kind"] == "provider_quote" and len(data["notice_ids"]) == 1
    assert session.scalar(select(func.count()).select_from(MarketObservation)) == 2
    assert session.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    quotes = list(
        session.scalars(
            select(Run).where(
                Run.executor_type == "agent_market", Run.parameters["tool"].as_string() == "market.quote"
            )
        )
    )
    assert all(q.effective_permissions == ["network_read", "market_data_read"] for q in quotes)
    assert all(not q.requested_resources for q in quotes)
    repeated = result(session, launch(session, agent))
    assert repeated["rows"][0]["status"] == "repeated" and repeated["notice_ids"] == []


def test_closed_market_retains_actual_asof_and_compares_across_weekend(session, monkeypatch):
    agent, _ = setup_stock(session, monkeypatch)
    now = utcnow()
    assert agent.market["comparison_window_seconds"] == 604800
    install_quotes(monkeypatch, at=now - timedelta(days=4), opened=False)
    baseline = result(session, launch(session, agent))
    assert baseline["rows"][0]["source_metadata"]["freshness"] == "last_known"
    install_quotes(monkeypatch, price=110, at=now - timedelta(days=3), opened=False)
    data = result(session, launch(session, agent))
    assert data["rows"][0]["status"] == "alert"
    assert data["rows"][0]["source_metadata"]["market_session"] == "closed"
    assert data["rows"][0]["source_at"].startswith((now - timedelta(days=3)).date().isoformat())


@pytest.mark.parametrize(
    "override",
    [{"price": 0}, {"currency": "EUR"}, {"symbol": "OTHER"}, {"at": utcnow() - timedelta(minutes=6)}],
)
def test_unsupported_stock_quote_never_persists_an_observation_or_alert(session, monkeypatch, override):
    agent, _ = setup_stock(session, monkeypatch)
    install_quotes(monkeypatch, **override)
    rid = launch(session, agent)
    quote = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.quote")
    )
    assert quote.status == "failed"
    for model in (MarketObservation, MarketAlert, Notice):
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_revised_same_timestamp_is_inspectable_and_cannot_overwrite_baseline(session, monkeypatch):
    agent, _ = setup_stock(session, monkeypatch)
    at = utcnow() - timedelta(seconds=10)
    install_quotes(monkeypatch, at=at)
    launch(session, agent)
    install_quotes(monkeypatch, price=101, at=at)
    rid = launch(session, agent)
    quote = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.quote")
    )
    assert quote.status == "failed" and "already recorded" in quote.error_message
    assert list(session.scalars(select(MarketObservation.price))) == ["100"]
    assert session.scalar(select(func.count()).select_from(Notice)) == 0
    source = session.get(Artifact, quote.metadata_json["stock_source_artifact_id"])
    from app.config import get_settings
    from app.paths import safe_join

    receipt = json.loads(safe_join(get_settings().data_dir, source.relative_path).read_text())
    assert receipt["quotes"][0]["price"] == "101" and source.run_id == quote.id


def test_stale_closed_quote_is_not_delivered_even_when_asof_age_is_allowed(session, monkeypatch):
    from app.market_watch import MarketExecutor
    from app.runs import claim_next

    agent, _ = setup_stock(session, monkeypatch)
    now = utcnow()
    install_quotes(monkeypatch, at=now - timedelta(days=4), opened=False)
    launch(session, agent)
    install_quotes(monkeypatch, price=110, at=now - timedelta(days=3), opened=False)
    rid = launch(session, agent, until="market.compare")
    row = session.scalar(select(MarketObservation).order_by(MarketObservation.observed_at.desc()))
    row.observed_at = utcnow() - timedelta(minutes=6)
    session.commit()
    notify = claim_next(session, "stock-aged-notify")
    assert notify.parent_run_id == rid and notify.parameters["tool"] == "market.notify"
    MarketExecutor().execute(session, notify)
    session.commit()
    assert notify.metadata_json["market_result"]["rows"][0]["status"] == "stale_before_delivery"
    assert session.scalar(select(func.count()).select_from(Notice)) == 0


def test_saved_account_rotation_blocks_dispatch_and_pending_publication(session, monkeypatch):
    agent, feed = setup_stock(session, monkeypatch)
    install_quotes(monkeypatch)
    rid = launch(session, agent, until="market.quote")
    monkeypatch.setenv("STOCK_FIXTURE_KEY", "rotated-fixture-stock-account-token")
    for _ in range(5):
        if tick(session, "stock-rotation-test") is None:
            break
    with pytest.raises(ValueError, match="changed"):
        launch_agent(session, agent, triggered_by="user")
    compare = session.scalar(
        select(Run).where(Run.parent_run_id == rid, Run.parameters["tool"].as_string() == "market.compare")
    )
    assert compare.status == "failed" and "changed" in compare.error_message
    assert session.scalar(select(func.count()).select_from(Notice)) == 0


def test_crypto_policy_hash_remains_byte_for_byte_compatible():
    legacy = {
        "provider": "coinbase_exchange",
        "instruments": ["BTC-USD"],
        "threshold_percent": "5",
        "direction": "both",
        "comparison_window_seconds": 172800,
        "cooldown_seconds": 3600,
    }
    assert (
        policy_key(MarketScope()) == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    )


def test_factory_does_not_invent_symbols_or_choose_a_paid_account():
    from app.factory import draft_agent

    for text, symbols in [
        ("Codziennie sprawdzaj ceny akcji AAPL i MSFT i powiadom przy zmianie o 3%", ["AAPL", "MSFT"]),
        ("Codziennie sprawdzaj ceny akcji Apple", []),
    ]:
        draft = draft_agent(text)
        assert draft.tools == ["market_watch"] and draft.market["provider"] == "finnhub"
        assert draft.market["instruments"] == symbols and draft.market["feed"] is None
        assert not draft.enabled and draft.model == ""


def test_stock_email_uses_reviewed_template_currency_and_closed_session_receipt(session, monkeypatch):
    wire = Transport()
    monkeypatch.setattr("app.email_delivery.connect_smtp", lambda *_: wire)
    agent, _ = setup_stock(session, monkeypatch)
    stock_market = agent.market
    agent.enabled = False
    aid = agent.id
    session.commit()
    api = TestClient(app)
    smtp = api.post(
        "/api/connectors",
        json={
            "key": "stock-mail",
            "name": "Mail",
            "kind": "email",
            "smtp": {
                "host": "smtp.example.com",
                "sender": "station@example.com",
                "allowed_recipients": ["one@example.com"],
            },
        },
    ).json()
    agent = session.get(Agent, aid)
    agent.market = {
        **stock_market,
        "email": {
            "connector_id": smtp["id"],
            "connector_revision": smtp["email_policy_revision"],
            "recipients": ["one@example.com"],
        },
    }
    session.commit()
    reviewed = api.get("/api/agents/" + aid).json()
    assert enabled(api, reviewed, confirm=False).status_code == 409
    response = enabled(api, reviewed)
    assert response.status_code == 200, response.text
    session.expire_all()
    agent = session.get(Agent, aid)
    now = utcnow()
    install_quotes(monkeypatch, at=now - timedelta(days=4), opened=False)
    launch(session, agent)
    assert not wire.messages
    install_quotes(monkeypatch, price=110, at=now - timedelta(days=3), opened=False)
    data = result(session, launch(session, agent))
    assert len(wire.messages) == 1 and data["email_receipts"][0]["state"] == "accepted"
    message = BytesParser(policy=policy.default).parsebytes(wire.messages[0][2]).get_body().get_content()
    assert "Currency: USD" in message and "provider quote time:" in message
    assert "closed; last known" in message and "trade time:" not in message
    receipt = session.scalar(select(EmailDelivery))
    assert receipt.payload["market_alert"]["template"] == "stock-threshold-v1"


def test_account_can_be_reviewed_in_an_incomplete_draft_but_enable_requires_symbols(session, monkeypatch):
    _, feed = setup_stock(session, monkeypatch)
    target = {"connector_id": feed.id, "connector_revision": connector_revision(feed)}
    session.commit()
    api = TestClient(app)
    response = api.post(
        "/api/agents",
        json={
            "name": "Draft",
            "goal": "Choose stocks later",
            "tools": ["market_watch"],
            "market": {"provider": "finnhub", "instruments": [], "feed": target},
        },
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert not draft["market_readiness"]["ready"] and not draft["enabled"]
    assert enabled(api, draft).status_code == 422


def test_pause_remains_available_after_account_rotation(session, monkeypatch):
    agent, _ = setup_stock(session, monkeypatch)
    aid = agent.id
    session.commit()
    api = TestClient(app)
    assert api.get("/api/agents/" + aid).json()["market_readiness"]["ready"]
    monkeypatch.setenv("STOCK_FIXTURE_KEY", "rotated-fixture-stock-account-token")
    saved = api.get("/api/agents/" + aid).json()
    assert not saved["market_readiness"]["ready"]
    response = api.post(
        "/api/agents/" + aid + "/enabled", json={"expected_updated_at": saved["updated_at"], "enabled": False}
    )
    assert response.status_code == 200 and not response.json()["enabled"]
    assert enabled(api, response.json()).status_code == 409


def test_account_settings_cannot_change_while_a_scoped_quote_is_queued(session, monkeypatch):
    agent, feed = setup_stock(session, monkeypatch)
    fid = feed.id
    rid = launch_agent(session, agent, triggered_by="user")
    session.commit()
    tick(session, "stock-publish-only")
    session.commit()
    api = TestClient(app)
    saved = api.get("/api/connectors/" + fid).json()
    response = api.patch(
        "/api/connectors/" + fid, json={"name": "Changed", "expected_updated_at": saved["updated_at"]}
    )
    assert response.status_code == 409
    assert api.delete("/api/connectors/" + fid).status_code == 409
    assert api.get("/api/runs/" + rid).json()["status"] == "succeeded"


def test_stock_migration_preserves_legacy_crypto_observation_and_baseline_hash(session):
    from alembic import command
    from app.db import alembic_config
    from test_market_watch import setup_agent

    agent = setup_agent(session)
    rid = launch_agent(session, agent, triggered_by="user")
    row = MarketObservation(
        agent_id=agent.id,
        run_id=rid,
        policy_key=policy_key(MarketScope()),
        instrument="BTC-USD",
        trade_id="123",
        price="100.01",
        source_at=utcnow(),
        source_url="https://api.exchange.coinbase.com/products/BTC-USD/ticker",
    )
    session.add(row)
    session.flush()
    identity, source_time, baseline = row.id, row.source_at, row.policy_key
    session.commit()
    command.downgrade(alembic_config(), "0030")
    command.upgrade(alembic_config(), "head")
    session.expire_all()
    saved = session.get(MarketObservation, identity)
    assert saved.price == "100.01" and saved.trade_id == "123" and saved.source_at == source_time
    assert saved.policy_key == baseline and saved.source_metadata == {}
