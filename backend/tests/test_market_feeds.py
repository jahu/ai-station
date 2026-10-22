"""Account reads use fake HTTP and keys; never a real finance API or SMTP account."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.engine import tick
from app.market_feeds import connector_revision
from app.models import Artifact, Connector, Run, RunEvent
from fastapi.testclient import TestClient
from sqlalchemy import func, select

KEY = "fixture-stock-key-54321"


@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setenv("STOCK_TEST_KEY", KEY)
    api = TestClient(app)
    response = api.post(
        "/api/connectors",
        json={
            "key": "stocks",
            "name": "Stocks",
            "kind": "market_data",
            "market_provider": "finnhub",
            "secret_ref": "env:STOCK_TEST_KEY",
        },
    )
    assert response.status_code == 201, response.text
    return api, response.json()


def status_page(url):
    return {
        "url": url,
        "status": 200,
        "content_type": "application/json",
        "truncated": False,
        "text": json.dumps(
            {
                "exchange": "US",
                "isOpen": False,
                "session": None,
                "timezone": "America/New_York",
                "t": int(utcnow().timestamp()),
            }
        ),
    }


def fake_status(monkeypatch, *, patch=None):
    seen = []

    async def fetch(url, *, extra_headers):
        seen.append((url, extra_headers))
        return {**status_page(url), **(patch or {})}

    monkeypatch.setattr("app.market_feeds.fetch_public", fetch)
    return seen


def work():
    with session_factory()() as session:
        tick(session, "stock-account-test")


def receipt(api, run_id):
    result = api.get("/api/runs/" + run_id)
    assert result.status_code == 200
    return result.json()


def test_save_is_metadata_only_and_check_is_queued_with_canonical_artifact(feed, monkeypatch):
    api, row = feed
    seen = fake_status(monkeypatch)
    assert row["market_provider"] == "finnhub" and len(row["market_policy_revision"]) == 64
    assert row["health"] == "unknown" and row["secret_present"]
    run = api.post(f"/api/connectors/{row['id']}/check").json()
    assert run["status"] == "queued" and seen == []
    assert run["effective_permissions"] == ["network_read", "market_data_read"]
    assert KEY not in json.dumps(run) and "secret_ref" not in run["parameters"]
    blocked = api.delete(f"/api/connectors/{row['id']}")
    assert blocked.status_code == 409
    work()
    result = receipt(api, run["id"])
    assert result["status"] == "succeeded", result
    assert seen == [("https://finnhub.io/api/v1/stock/market-status?exchange=US", {"X-Finnhub-Token": KEY})]
    assert "entitlements were not tested" in result["summary"]
    public = api.get(f"/api/connectors/{row['id']}").json()
    assert public["health"] == "healthy" and public["market_policy_revision"] == row["market_policy_revision"]
    with session_factory()() as session:
        artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run["id"])))
        assert len(artifacts) == 1
        from app.config import get_settings
        from app.paths import safe_join

        stored = safe_join(get_settings().data_dir, artifacts[0].relative_path).read_text()
        assert KEY not in stored and '"text"' not in stored and '"market_session": "closed"' in stored


def test_symbol_lookup_deduplicates_and_does_not_change_account_health(feed, monkeypatch):
    api, row = feed
    seen = []

    async def fetch(url, **kwargs):
        seen.append(url)
        return {
            **status_page(url),
            "text": json.dumps(
                {
                    "count": 4,
                    "result": [
                        {"symbol": "AAPL", "description": "Apple Inc", "type": "Common Stock"},
                        {"symbol": "AAPL", "description": "Apple duplicate"},
                        {"symbol": "BINANCE:BTCUSD", "description": "Crypto"},
                        {"symbol": "BRK.B", "description": "Berkshire"},
                    ],
                }
            ),
        }

    monkeypatch.setattr("app.market_feeds.fetch_public", fetch)
    run = api.post(
        f"/api/market-feeds/{row['id']}/search",
        json={"connector_revision": row["market_policy_revision"], "query": "Apple & company"},
    )
    assert run.status_code == 202 and not seen
    work()
    result = receipt(api, run.json()["id"])
    assert result["status"] == "succeeded", result
    assert [r["symbol"] for r in result["metadata"]["market_feed"]["symbols"]] == ["AAPL", "BRK.B"]
    assert seen == ["https://finnhub.io/api/v1/search?q=Apple+%26+company&exchange=US"]
    public = api.get(f"/api/connectors/{row['id']}").json()
    assert public["health"] == "unknown" and public["last_run_id"] is None


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"status": 401}, "rejected"),
        ({"status": 403}, "subscription"),
        ({"status": 429}, "rate limit"),
        ({"truncated": True}, "unsupported"),
        ({"url": "https://other.example/"}, "unsupported"),
        ({"error": "server error with " + KEY}, "credential-bearing"),
        ({"text": json.dumps({"error": KEY})}, "credential-bearing"),
    ],
)
def test_provider_failures_do_not_persist_raw_data_or_retry(feed, monkeypatch, patch, reason):
    api, row = feed
    seen = fake_status(monkeypatch, patch=patch)
    run = api.post(f"/api/connectors/{row['id']}/check").json()
    work()
    result = receipt(api, run["id"])
    assert result["status"] == "failed" and reason in result["error_message"], result
    assert len(seen) == 1 and KEY not in json.dumps(result)
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0
        assert KEY not in json.dumps([event.payload for event in session.scalars(select(RunEvent))])


def test_invalid_header_or_transport_exception_never_echoes_key(feed, monkeypatch):
    api, row = feed

    async def fetch(*args, **kwargs):
        raise ValueError("invalid header " + KEY)

    monkeypatch.setattr("app.market_feeds.fetch_public", fetch)
    run = api.post(f"/api/connectors/{row['id']}/check").json()
    work()
    result = receipt(api, run["id"])
    assert result["status"] == "failed" and KEY not in json.dumps(result)


def test_connector_key_rotation_rejects_stale_lookup_without_network(feed, monkeypatch):
    api, row = feed
    seen = fake_status(monkeypatch)
    monkeypatch.setenv("STOCK_TEST_KEY", "rotated-fixture-stock-key")
    changed = api.get(f"/api/connectors/{row['id']}").json()
    assert changed["market_policy_revision"] != row["market_policy_revision"]
    response = api.post(
        f"/api/market-feeds/{row['id']}/search",
        json={"connector_revision": row["market_policy_revision"], "query": "Apple"},
    )
    assert response.status_code == 409 and seen == []


def test_rotation_after_enqueue_is_checked_again_by_worker(feed, monkeypatch):
    api, row = feed
    seen = fake_status(monkeypatch)
    run = api.post(f"/api/connectors/{row['id']}/check").json()
    monkeypatch.setenv("STOCK_TEST_KEY", "rotated-fixture-stock-key")
    work()
    assert receipt(api, run["id"])["status"] == "failed" and not seen


def test_disabled_or_missing_account_cannot_read(feed, monkeypatch):
    api, row = feed
    seen = fake_status(monkeypatch)
    monkeypatch.delenv("STOCK_TEST_KEY")
    assert api.get(f"/api/connectors/{row['id']}").json()["secret_present"] is False
    assert api.post(f"/api/connectors/{row['id']}/check").status_code == 409
    monkeypatch.setenv("STOCK_TEST_KEY", KEY)
    response = api.patch(
        f"/api/connectors/{row['id']}", json={"enabled": False, "expected_updated_at": row["updated_at"]}
    )
    assert response.status_code == 200
    assert api.post(f"/api/connectors/{row['id']}/check").status_code == 409 and not seen


@pytest.mark.parametrize(
    "extra",
    [
        {"url": "https://example.com"},
        {"repository": "owner/repo"},
        {"market_provider": None},
        {"secret": "key\r\nAuthorization: leaked"},
    ],
)
def test_account_cannot_supply_custom_host_repository_or_header_injection(extra):
    api = TestClient(app)
    response = api.post(
        "/api/connectors",
        json={
            "key": "stocks",
            "name": "Stocks",
            "kind": "market_data",
            "market_provider": "finnhub",
            **extra,
        },
    )
    assert response.status_code == 422
    assert "leaked" not in response.text


def test_stop_during_read_cancels_pending_request_and_writes_no_artifact(feed, monkeypatch):
    from app.runs import request_cancel

    api, row = feed
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    canceled = []
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        session.commit()

        async def fetch(*args, **kwargs):
            request_cancel(session, run)
            session.commit()
            try:
                await asyncio.sleep(30)
            finally:
                canceled.append(True)

        monkeypatch.setattr("app.market_feeds.fetch_public", fetch)
        tick(session, "stock-stop-test")
        assert run.status == "canceled" and canceled
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0


def test_missing_permission_and_expired_dispatch_do_not_read(feed, monkeypatch):
    api, row = feed
    seen = fake_status(monkeypatch)
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.effective_permissions = ["network_read"]
        session.commit()
    work()
    assert receipt(api, queued["id"])["status"] == "failed" and not seen
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        run.parameters = {**run.parameters, "deadline_at": (utcnow() - timedelta(seconds=1)).isoformat()}
        session.commit()
    work()
    assert "expired" in receipt(api, queued["id"])["error_message"] and not seen


def test_stale_worker_read_is_interrupted_without_auto_replay(feed):
    from app.recovery import recover_stale
    from app.runs import transition
    from app.state import RunStatus

    api, row = feed
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        for state in (RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING):
            transition(session, run, state, event_type="fixture.transition")
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

        class Runner:
            def inspect_process(self, run_id):
                return {"alive": False, "known": False}

        assert run.id in recover_stale(session, Runner())
        assert run.status == "interrupted" and run.retry_class == "inspect"
        assert connector_revision(session.get(Connector, row["id"])) == row["market_policy_revision"]


def test_cross_origin_redirect_drops_token_and_response_is_not_accepted(feed, monkeypatch):
    from app import http_fetch

    api, row = feed
    seen = []
    original = httpx.AsyncClient

    def handle(request):
        seen.append(dict(request.headers))
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "https://other.example/status"})
        return httpx.Response(200, json={"unexpected": True})

    monkeypatch.setattr(
        http_fetch.socket, "getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle))
    )
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    work()
    assert seen[0]["x-finnhub-token"] == KEY and "x-finnhub-token" not in seen[1]
    assert receipt(api, queued["id"])["status"] == "failed"


def test_dns_private_target_is_blocked_before_sending_credentials(feed, monkeypatch):
    from app import http_fetch

    api, row = feed
    monkeypatch.setattr(
        http_fetch.socket, "getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("127.0.0.1", 0))]
    )
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    work()
    assert receipt(api, queued["id"])["status"] == "failed"


def test_interruption_while_read_is_pending_cancels_the_future_and_cannot_publish(feed, monkeypatch):
    from app.runs import transition
    from app.state import RunStatus

    api, row = feed
    queued = api.post(f"/api/connectors/{row['id']}/check").json()
    closed = []
    with session_factory()() as session:
        run = session.get(Run, queued["id"])
        session.commit()

        async def fetch(*args, **kwargs):
            transition(session, run, RunStatus.INTERRUPTED, event_type="run.interrupted")
            session.commit()
            try:
                await asyncio.sleep(30)
            finally:
                closed.append(True)

        monkeypatch.setattr("app.market_feeds.fetch_public", fetch)
        tick(session, "stock-interrupted-read")
        assert run.status == "interrupted" and closed
        assert session.scalar(select(func.count()).select_from(Artifact)) == 0
