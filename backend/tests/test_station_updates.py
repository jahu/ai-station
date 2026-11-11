import asyncio
import copy
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from app import station_release_source as source
from app.api import app
from app.db import control_session_factory, session_factory
from app.engine import tick
from app.models import Run, User
from fastapi.testclient import TestClient
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app


def release():
    from ai_station_runner.station_release_metadata import API, WEB

    name = "AI-Station-0.5.0-linux-amd64.deb"
    return {
        "id": 123,
        "tag_name": "v0.5.0",
        "draft": False,
        "prerelease": False,
        "html_url": f"{WEB}/releases/tag/v0.5.0",
        "published_at": "2026-11-09T12:00:00Z",
        "body": "An official test release",
        "assets": [
            {
                "id": 456,
                "name": name,
                "state": "uploaded",
                "size": 50,
                "digest": "sha256:" + "a" * 64,
                "url": f"{API}/releases/assets/456",
                "browser_download_url": f"{WEB}/releases/download/v0.5.0/{name}",
            }
        ],
    }


def fake_source(monkeypatch, *, body=None, status=200, headers=None, url=None):
    calls = []

    @asynccontextmanager
    async def response(endpoint, offset, check):
        check()
        calls.append(endpoint)
        answer = httpx.Response(
            status,
            headers=headers or {},
            stream=httpx.ByteStream(body if body is not None else json.dumps(release()).encode()),
            request=httpx.Request("GET", url or endpoint),
        )
        try:
            yield answer
        finally:
            await answer.aclose()

    monkeypatch.setattr(source, "response", response)
    return calls


def test_fixed_official_source_and_frozen_identity(monkeypatch):
    calls = fake_source(monkeypatch)
    value = asyncio.run(source.release_metadata(lambda: None, release_id=123))
    assert value["version"] == "0.5.0"
    assert calls == ["https://api.github.com/repos/jahu/ai-station/releases/123"]
    with pytest.raises(ValueError, match="identity changed"):
        asyncio.run(source.release_metadata(lambda: None, release_id=124))


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"status": 429}, "busy"),
        ({"status": 404}, "unavailable"),
        ({"body": b'{"id":1,"id":2}'}, "duplicate"),
        ({"body": b"not-json"}, "invalid release"),
        ({"body": b"\xff"}, "invalid release"),
        ({"headers": {"content-length": "1048577"}}, "size limit"),
        ({"body": b"x" * (1024 * 1024 + 1)}, "size limit"),
        ({"headers": {"content-encoding": "gzip"}}, "unexpected source"),
        ({"url": "https://other.example/releases/latest"}, "unexpected source"),
        ({"url": "https://api.github.com/repos/other/app/releases/latest"}, "unexpected source"),
    ],
)
def test_untrusted_or_unbounded_metadata_is_not_admitted(monkeypatch, kwargs, match):
    fake_source(monkeypatch, **kwargs)
    with pytest.raises(ValueError, match=match):
        asyncio.run(source.release_metadata(lambda: None))


def test_http_only_enqueues_worker_keeps_history_and_coalesces_checks(monkeypatch):
    calls = fake_source(monkeypatch)
    with TestClient(app) as client:
        assert client.post("/api/maintenance/updates/checks", json={"url": "anything"}).status_code == 422
        queued = client.post("/api/maintenance/updates/checks", json={})
        assert queued.status_code == 202, queued.text
        identity = queued.json()["id"]
        assert not calls
        assert client.post("/api/maintenance/updates/checks", json={}).json()["id"] == identity
        with session_factory()() as session:
            tick(session, "updates-test")
        result = client.get("/api/maintenance/updates").json()
        assert result["latest_check"]["status"] == "succeeded", result
        assert result["release"]["version"] == "0.5.0"
        assert result["release"]["packages"]["linux-amd64"]["sha256"] == "a" * 64
        assert result["apply_available"] is False
        assert len(calls) == 1
        assert client.post("/api/maintenance/updates/checks", json={}).json()["id"] == identity


@pytest.mark.parametrize("mutation", ["cancel", "claim", "parameters"])
def test_check_never_publishes_after_cancellation_claim_loss_or_modified_contract(monkeypatch, mutation):
    from app.runs import request_cancel

    async def changed(check, **kwargs):
        with session_factory()() as other:
            row = other.get(Run, identity)
            if mutation == "cancel":
                request_cancel(other, row)
            elif mutation == "claim":
                row.worker_id = "replacement"
            else:
                row.parameters = {"url": "https://other.example"}
            other.commit()
        return copy.deepcopy(release())

    monkeypatch.setattr(source, "release_metadata", changed)
    with TestClient(app) as client:
        identity = client.post("/api/maintenance/updates/checks", json={}).json()["id"]
        with session_factory()() as session:
            tick(session, "updates-test")
        with session_factory()() as session:
            row = session.get(Run, identity)
            assert "release" not in row.metadata_json
            assert row.status == {"cancel": "canceled", "claim": "running", "parameters": "failed"}[mutation]


def test_members_cannot_check_updates_and_revocation_prevents_network(accounts, monkeypatch):
    owner, alice, bob = accounts
    calls = fake_source(monkeypatch)
    for member in (alice, bob):
        assert member.get("/api/maintenance/updates").status_code == 403
        assert member.post("/api/maintenance/updates/checks", json={}).status_code == 403
    identity = owner.post("/api/maintenance/updates/checks", json={}).json()["id"]
    assert alice.get(f"/api/runs/{identity}").status_code == 404
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        session.get(User, run.owner_id).is_admin = False
        session.commit()
    with control_session_factory()() as session:
        tick(session, "updates-private")
        row = session.get(Run, identity)
        assert row.status == "failed"
    assert not calls
