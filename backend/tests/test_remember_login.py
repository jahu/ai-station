from datetime import timedelta

import pytest
from app import accounts, operator_auth
from app.db import session_factory, utcnow
from app.models import UserSession
from sqlalchemy import select
from test_accounts_api import PASSWORD, client, setup
from test_accounts_api import account_app as account_app


def test_remembered_device_survives_two_days_and_new_logins_without_extending_absolute_expiry(
    account_app, monkeypatch
):
    browser, _ = setup(account_app)
    reply = browser.post(
        "/api/auth/login", json={"username": "Owner", "password": PASSWORD, "remember_me": True}
    )
    assert reply.status_code == 200
    assert reply.json()["session_idle_seconds"] == reply.json()["session_max_age_seconds"] == 2592000
    cookie = next(c for c in reply.headers.get_list("set-cookie") if c.startswith(accounts.COOKIE + "="))
    assert "Max-Age=2592000" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    with session_factory()() as db:
        row = db.scalar(select(UserSession).where(UserSession.revoked_at.is_(None)))
        identity = row.id
        record = dict(row.token_record)
        assert record["remember_me"] is True and record["idle_timeout_seconds"] == 2592000
    future = utcnow() + timedelta(days=2)
    monkeypatch.setattr(accounts, "utcnow", lambda: future)
    monkeypatch.setattr(operator_auth, "utcnow", lambda: future)
    another = client(account_app)
    assert (
        another.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 200
    )
    devices = browser.get("/api/account/devices")
    assert devices.status_code == 200, devices.text
    assert any(d["id"] == identity for d in devices.json())
    with session_factory()() as db:
        row = db.get(UserSession, identity)
        assert row.revoked_at is None
        assert row.token_record["expires_at"] == record["expires_at"]
    future = utcnow() + timedelta(days=31)
    assert browser.get("/api/account/devices").status_code == 401


def test_default_idle_timeout_is_unchanged_and_remembered_logout_revokes_access(account_app, monkeypatch):
    browser, _ = setup(account_app)
    login = browser.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
    assert "Max-Age=1800" in next(
        c for c in login.headers.get_list("set-cookie") if c.startswith(accounts.COOKIE + "=")
    )
    future = utcnow() + timedelta(hours=1)
    monkeypatch.setattr(accounts, "utcnow", lambda: future)
    monkeypatch.setattr(operator_auth, "utcnow", lambda: future)
    assert browser.get("/api/account/devices").status_code == 401
    assert (
        browser.post(
            "/api/auth/login", json={"username": "Owner", "password": PASSWORD, "remember_me": True}
        ).status_code
        == 200
    )
    assert browser.post("/api/auth/logout").status_code == 200
    assert browser.get("/api/account/devices").status_code == 401


@pytest.mark.parametrize("value", ["true", 1, {}, None])
def test_remember_preference_requires_an_explicit_boolean(account_app, value):
    browser, _ = setup(account_app)
    result = browser.post(
        "/api/auth/login", json={"username": "Owner", "password": PASSWORD, "remember_me": value}
    )
    assert result.status_code == 422
