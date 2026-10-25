"""An activity cookie must not reserve SQLite while an endpoint still owns its session."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.api import app
from app.db import session_factory, utcnow
from app.models import Setting
from app.operator_auth import COOKIE, SESSION_KEY, refresh_operator_cookie, require_operator_session
from fastapi import Request, Response
from fastapi.testclient import TestClient


@pytest.mark.parametrize("private_https", [False, True])
def test_activity_cookie_refresh_finishes_before_the_response_session_is_released(private_https):
    client = TestClient(app)
    assert client.put("/api/operator-auth", json={"password": "stream-cookie-password"}).status_code == 200
    host = "station.example.ts.net" if private_https else "testserver"
    with session_factory()() as session:
        row = session.get(Setting, SESSION_KEY)
        row.value = {**row.value, "last_seen_at": (utcnow() - timedelta(minutes=2)).isoformat()}
        if private_https:
            session.merge(
                Setting(
                    key="private_ui_access",
                    value={
                        "revision": 1,
                        "enabled": True,
                        "password_required": True,
                        "origin": "https://station.example.ts.net",
                    },
                )
            )
        session.commit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/chat/conversations",
            "headers": [
                (b"host", host.encode()),
                (b"cookie", (COOKIE + "=" + client.cookies[COOKIE]).encode()),
            ],
        }
    )
    assert require_operator_session(request) is None
    assert request.state.operator_cookie_refresh
    response = Response()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with session_factory()() as endpoint:
            assert endpoint.get(Setting, SESSION_KEY) is not None  # Own BEGIN IMMEDIATE like a GET handler.
            pending = pool.submit(refresh_operator_cookie, request, response)
            try:
                pending.result(timeout=0.5)
            finally:
                endpoint.rollback()  # Always release the fixture even against the broken implementation.
    cookie = response.headers["set-cookie"]
    assert ("Secure" in cookie) is private_https
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=" in cookie


def test_failed_delta_flush_keeps_original_error_and_last_saved_answer(monkeypatch):
    from app import chat_executor
    from app.engine import tick
    from app.local_provider import LocalChatProvider
    from app.models import Message, Run, RunEvent
    from sqlalchemy import select
    from test_chat import new_conversation

    closed = []

    async def stream(self, **params):
        try:
            yield "Saved prefix. "
            yield "Uncommitted suffix."
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    original = chat_executor.append_event
    deltas = []

    def persist(session, run_id, event_type, payload):
        if event_type == "chat.delta":
            deltas.append(payload["text"])
            if len(deltas) == 2:
                # A genuine invalid ORM flush, not a fabricated inactive-session flag.
                session.add(RunEvent(run_id=run_id, sequence=1, event_type="fixture.duplicate", payload={}))
                session.flush()
        return original(session, run_id, event_type, payload)

    monkeypatch.setattr(chat_executor, "append_event", persist)
    with TestClient(app) as client:
        cid = new_conversation(client)
        response = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Say hello"})
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            assert tick(session, "failed-delta-flush") == rid
            run = session.get(Run, rid)
            assert run.status == "failed" and run.error_type == "IntegrityError"
            answer = session.scalar(select(Message).where(Message.run_id == rid, Message.role == "assistant"))
            assert answer.content == "Saved prefix. " and answer.metadata_json["partial"] is True
        assert closed == [True]


def test_authenticated_history_polling_refreshes_cookies_without_interrupting_stream(monkeypatch):
    import asyncio
    from threading import Event

    from app.engine import tick
    from app.local_provider import LocalChatProvider
    from test_chat import new_conversation

    entered, finish = Event(), Event()
    closed = []

    async def stream(self, **params):
        try:
            yield "First saved part. "
            entered.set()
            assert await asyncio.to_thread(finish.wait, 5)
            yield "Complete answer."
        finally:
            closed.append(True)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    client = TestClient(app)
    assert client.put("/api/operator-auth", json={"password": "stream-cookie-password"}).status_code == 200
    cid = new_conversation(client)
    queued = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Say hello"})
    assert queued.status_code == 202, queued.text
    rid = queued.json()["id"]

    def work():
        with session_factory()() as session:
            return tick(session, "authenticated-chat-stream")

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(work)
        try:
            assert entered.wait(2)
            for _ in range(3):
                with session_factory()() as session:
                    row = session.get(Setting, SESSION_KEY)
                    row.value = {**row.value, "last_seen_at": (utcnow() - timedelta(minutes=2)).isoformat()}
                    session.commit()
                response = pool.submit(client.get, f"/api/chat/conversations/{cid}").result(timeout=0.75)
                assert response.status_code == 200
                assert response.json()["messages"][-1]["content"] == "First saved part. "
                assert "HttpOnly" in response.headers["set-cookie"]
                assert not pending.done()  # Polling did not cancel or fail inference.
        finally:
            finish.set()
        assert pending.result(timeout=3) == rid
    detail = client.get(f"/api/chat/conversations/{cid}").json()
    assert detail["messages"][-1]["content"] == "First saved part. Complete answer."
    assert detail["messages"][-1]["run_status"] == "succeeded"
    assert closed == [True]
