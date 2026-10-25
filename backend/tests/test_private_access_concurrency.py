"""A slow network-status read must not hold the control-plane write transaction."""

import asyncio
from threading import Event

import httpx
from app.api import app
from app.runner_client import RunnerClient
from fastapi.testclient import TestClient


async def test_slow_private_status_releases_database_for_other_requests(monkeypatch):
    operator = TestClient(app)
    assert (
        operator.put("/api/operator-auth", json={"password": "concurrent-private-password"}).status_code
        == 200
    )
    entered, release = Event(), Event()

    def slow_native(*_args, **_kwargs):
        entered.set()
        release.wait(3)
        return {"available": True, "installed": False, "state": "not_installed", "serving": False}

    monkeypatch.setattr(RunnerClient, "request", slow_native)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", cookies=operator.cookies
    ) as client:
        pending = asyncio.create_task(client.get("/api/private-access"))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(client.get("/api/health"), timeout=0.75)
            assert response.status_code == 200
            assert not release.is_set()
        finally:
            release.set()
            assert (await pending).status_code == 200
