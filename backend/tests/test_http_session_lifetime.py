"""A slow response consumer must never retain SQLite's writer reservation."""

import asyncio
import sqlite3

import pytest
from app.api import app
from app.db import get_engine
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/api/runs", "/api/artifacts", "/api/chat/conversations"])
def test_response_backpressure_releases_database_before_body_delivery(path):
    database = get_engine().url.database

    def independent_writer():
        try:
            with sqlite3.connect(database, timeout=0.1) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
        except sqlite3.OperationalError as exc:
            return str(exc)
        return None

    async def exercise():
        delivering, release, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
        messages = []

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                delivering.set()
                await release.wait()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8765")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8765),
            "root_path": "",
        }
        request = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(delivering.wait(), timeout=5)
            error = await asyncio.to_thread(independent_writer)
        finally:
            release.set()
            await asyncio.wait_for(request, timeout=5)
        assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 200, messages
        assert error is None, "The response consumer retained SQLite's writer lock: " + str(error)

    with TestClient(app):
        asyncio.run(exercise())
