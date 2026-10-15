from datetime import timedelta

import pytest
from app.api import app
from app.config import clear_settings_cache
from app.db import session_factory, utcnow
from app.models import Setting
from app.operator_auth import COOKIE, SESSION_KEY, refuse_non_loopback_bind
from app.private_access import access_origins, private_ipv4
from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "private-operator-test"
LAN = "http://192.168.20.5:8765"


def enable(monkeypatch):
    monkeypatch.setenv("AI_STATION_LAN_HOST", "192.168.20.5")
    clear_settings_cache()


def setup():
    desktop = TestClient(app)
    assert desktop.put("/api/operator-auth", json={"password": PASSWORD}).status_code == 200
    return desktop


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "8.8.8.8", "127.0.0.1", "169.254.1.1", "192.0.2.1", "::", "home.local"]
)
def test_only_explicit_private_ipv4_is_published(monkeypatch, host):
    assert not private_ipv4(host)
    monkeypatch.setenv("AI_STATION_LAN_HOST", host)
    clear_settings_cache()
    with pytest.raises(ValueError, match="private IPv4"):
        access_origins()


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://workstation.tail.ts.net",
        "https://192.168.20.5/path",
        "https://user:secret@192.168.20.5",
        "http://192.168.20.5:0",
        "https://8.8.8.8",
        "https://192.168.20.5#fragment",
    ],
)
def test_untrusted_proxy_origins_are_refused(monkeypatch, origin):
    monkeypatch.setenv("AI_STATION_ACCESS_ORIGINS", origin)
    clear_settings_cache()
    with pytest.raises(ValueError):
        access_origins()


def test_private_startup_requires_password_and_can_never_clear_it(monkeypatch):
    enable(monkeypatch)
    with session_factory()() as session, pytest.raises(RuntimeError, match="operator password"):
        refuse_non_loopback_bind(session)
    # A stale/missing credential also fails closed after startup.
    guest = TestClient(app, base_url=LAN)
    assert guest.get("/api/runs").status_code == 401
    assert guest.put("/api/operator-auth", json={"password": PASSWORD}).status_code == 401
    monkeypatch.delenv("AI_STATION_LAN_HOST")
    clear_settings_cache()
    desktop = setup()
    enable(monkeypatch)
    with session_factory()() as session:
        assert refuse_non_loopback_bind(session)["allowed"]
    assert desktop.post("/api/operator-auth/clear", json={"current_password": PASSWORD}).status_code == 409
    assert desktop.get("/api/operator-auth").json()["configured"]


def test_phone_and_desktop_sessions_are_independent_and_rotate_together(monkeypatch):
    desktop = setup()
    enable(monkeypatch)
    phone = TestClient(app, base_url=LAN)
    assert phone.get("/api/runs").status_code == 401
    signed = phone.post("/api/operator-auth/login", json={"password": PASSWORD}, headers={"Origin": LAN})
    assert signed.status_code == 200
    assert signed.json()["access_urls"] == [LAN]
    assert signed.json()["lan_bind_allowed"]
    assert signed.json()["session_scope"] == "private-network"
    assert signed.headers["cache-control"] == "no-store"
    assert phone.get("/api/runs").status_code == 200
    assert desktop.get("/api/runs").status_code == 200
    with session_factory()() as session:
        rows = list(session.scalars(select(Setting).where(Setting.key.startswith(SESSION_KEY))))
        assert len(rows) == 2
        assert all(phone.cookies.get(COOKIE) not in str(row.value) for row in rows)
    guest = TestClient(app, base_url=LAN)
    assert guest.post("/api/operator-auth/logout").status_code == 200
    assert desktop.get("/api/runs").status_code == 200
    assert phone.post("/api/operator-auth/logout").status_code == 200
    assert desktop.get("/api/runs").status_code == 200
    assert phone.get("/api/runs").status_code == 401
    assert phone.post("/api/operator-auth/login", json={"password": PASSWORD}).status_code == 200
    assert (
        desktop.put(
            "/api/operator-auth", json={"password": PASSWORD + "new", "current_password": PASSWORD}
        ).status_code
        == 200
    )
    assert phone.get("/api/runs").status_code == 401
    assert desktop.get("/api/runs").status_code == 200


def test_private_host_origin_and_fetch_site_cannot_be_spoofed(monkeypatch):
    setup()
    enable(monkeypatch)
    phone = TestClient(app, base_url=LAN)
    for origin in [
        "https://evil.example",
        LAN + ".evil.example",
        LAN + "/",
        "null",
        "http://192.168.20.5:8766",
    ]:
        assert (
            phone.post(
                "/api/operator-auth/login", json={"password": PASSWORD}, headers={"Origin": origin}
            ).status_code
            == 403
        )
    assert (
        phone.post(
            "/api/operator-auth/login",
            json={"password": PASSWORD},
            headers={"Origin": LAN, "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )
    assert phone.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert phone.get("/api/health", headers={"Host": "192.168.20.5:8766"}).status_code == 400
    assert (
        phone.get(
            "/api/runs",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Forwarded-Host": "localhost",
                "X-Forwarded-Proto": "https",
            },
        ).status_code
        == 401
    )
    assert (
        phone.post(
            "/api/operator-auth/login", json={"password": PASSWORD}, headers={"Origin": LAN}
        ).status_code
        == 200
    )


def test_configured_https_tailnet_uses_secure_cookie(monkeypatch):
    desktop = setup()
    origin = "https://workstation.example-tailnet.ts.net"
    monkeypatch.setenv("AI_STATION_ACCESS_ORIGINS", origin)
    clear_settings_cache()
    phone = TestClient(app, base_url=origin)
    signed = phone.post("/api/operator-auth/login", json={"password": PASSWORD}, headers={"Origin": origin})
    assert signed.status_code == 200
    assert "Secure" in signed.headers["set-cookie"]
    assert signed.json()["session_cookie"]["secure"] is True
    assert phone.get("/api/runs").status_code == 200
    assert desktop.get("/api/runs").status_code == 200


def test_login_budget_is_persistent_and_ignores_forwarded_ips(monkeypatch):
    setup()
    enable(monkeypatch)
    phone = TestClient(app, base_url=LAN)
    for index in range(10):
        assert (
            phone.post(
                "/api/operator-auth/login",
                json={"password": "wrong"},
                headers={"X-Forwarded-For": f"10.0.0.{index}"},
            ).status_code
            == 403
        )
    another = TestClient(app, base_url=LAN)
    denied = another.post("/api/operator-auth/login", json={"password": PASSWORD})
    assert denied.status_code == 429
    assert denied.headers["Retry-After"] == "60"
    now = utcnow()
    monkeypatch.setattr("app.operator_auth.utcnow", lambda: now + timedelta(seconds=61))
    assert another.post("/api/operator-auth/login", json={"password": PASSWORD}).status_code == 200


def test_activity_does_not_restore_old_cookie_after_password_rotation(monkeypatch):
    desktop = setup()
    before = desktop.cookies.get(COOKIE)
    now = utcnow()
    monkeypatch.setattr("app.operator_auth.utcnow", lambda: now + timedelta(minutes=2))
    rotated = desktop.put(
        "/api/operator-auth", json={"password": PASSWORD + "new", "current_password": PASSWORD}
    )
    assert rotated.status_code == 200
    assert desktop.cookies.get(COOKIE) != before
    assert desktop.get("/api/runs").status_code == 200
    monkeypatch.setattr("app.operator_auth.utcnow", lambda: now + timedelta(minutes=4))
    assert desktop.post("/api/operator-auth/logout").status_code == 200
    assert desktop.cookies.get(COOKIE) is None
    assert desktop.get("/api/runs").status_code == 401


def test_expired_phone_session_does_not_expire_active_desktop(monkeypatch):
    desktop = setup()
    enable(monkeypatch)
    phone = TestClient(app, base_url=LAN)
    assert phone.post("/api/operator-auth/login", json={"password": PASSWORD}).status_code == 200
    now = utcnow()
    monkeypatch.setattr("app.operator_auth.utcnow", lambda: now + timedelta(minutes=20))
    assert desktop.get("/api/runs").status_code == 200
    monkeypatch.setattr("app.operator_auth.utcnow", lambda: now + timedelta(minutes=31))
    assert phone.get("/api/runs").status_code == 401
    assert desktop.get("/api/runs").status_code == 200
