"""Real account HTTP boundary; it is not installed on the production app yet."""

import hashlib
from datetime import timedelta

import pyotp
import pytest
from app import api as application
from app.account_http import account_error, refresh_account_cookie, require_account_session
from app.accounts import COOKIE, LEGACY_COOKIE, AccountError, bootstrap_admin, login
from app.accounts_api import router
from app.config import clear_settings_cache
from app.db import session_factory, utcnow
from app.models import Setting, UserSession
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

PASSWORD = "synthetic owner password"


@pytest.fixture
def account_app(monkeypatch):
    # Exercise the exact existing Host/origin/upload/exception middleware with
    # the new guard, without registering incomplete accounts on app.api.app.
    monkeypatch.setattr(application, "require_operator_session", require_account_session)
    monkeypatch.setattr(application, "refresh_operator_cookie", refresh_account_cookie)
    app = FastAPI()
    app.middleware("http")(application.local_requests)
    app.add_exception_handler(AccountError, account_error)
    app.add_exception_handler(RequestValidationError, application.invalid_request)
    app.include_router(router)
    return app


def client(app, **kwargs):
    return TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000), **kwargs)


def setup(app):
    browser = client(app)
    result = browser.post("/api/auth/setup", json={"username": "Owner", "password": PASSWORD})
    assert result.status_code == 201, result.text
    return browser, result.json()["user"]


def test_first_admin_setup_once_with_cookie_and_no_secret_in_status(account_app):
    browser = client(account_app)
    status = browser.get("/api/auth")
    assert status.json()["setup_required"] and not status.json()["authenticated"]
    assert browser.get("/api/admin/users").status_code == 401
    result = browser.post("/api/auth/setup", json={"username": "Owner", "password": PASSWORD})
    assert result.status_code == 201 and result.json()["user"]["is_admin"]
    assert COOKIE in browser.cookies and PASSWORD not in result.text
    cookie = result.headers.get("set-cookie")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=1800" in cookie
    assert "Secure" not in cookie
    status = browser.get("/api/auth")
    assert status.json()["authenticated"] and not status.json()["setup_required"]
    assert status.headers["cache-control"] == "no-store"
    assert not {"password_record", "totp_secret_ref", "recovery_code_hashes"} & status.json()["user"].keys()
    assert (
        browser.post("/api/auth/setup", json={"username": "Other", "password": PASSWORD}).status_code == 409
    )


@pytest.mark.parametrize("peer,host", [("192.168.1.5", "127.0.0.1"), ("127.0.0.1", "testserver")])
def test_remote_or_proxy_like_setup_is_not_authorized_by_spoofed_headers(account_app, peer, host):
    browser = TestClient(account_app, base_url=f"http://{host}:8765", client=(peer, 50000))
    result = browser.post(
        "/api/auth/setup",
        json={"username": "Owner", "password": PASSWORD},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert result.status_code == 403
    assert browser.get("/api/auth").json()["setup_required"]


def test_even_loopback_setup_is_closed_while_private_access_is_configured(account_app, monkeypatch):
    monkeypatch.setenv("AI_STATION_LAN_HOST", "192.168.1.121")
    clear_settings_cache()
    response = client(account_app).post("/api/auth/setup", json={"username": "Owner", "password": PASSWORD})
    assert response.status_code == 403


def test_username_validation_does_not_return_password_input(account_app):
    response = client(account_app).post(
        "/api/auth/setup", json={"username": "../private", "password": PASSWORD}
    )
    assert response.status_code == 422 and PASSWORD not in response.text and '"input"' not in response.text


def test_cross_origin_cannot_claim_bootstrap_or_log_in(account_app):
    browser = client(account_app)
    result = browser.post(
        "/api/auth/setup",
        json={"username": "Owner", "password": PASSWORD},
        headers={"Origin": "https://unrelated.example"},
    )
    assert result.status_code == 403
    assert browser.get("/api/auth").json()["setup_required"]
    setup(account_app)
    result = browser.post(
        "/api/auth/login",
        json={"username": "Owner", "password": PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert result.status_code == 403 and COOKIE not in browser.cookies


def test_attempts_are_durable_and_identity_normalization_cannot_reset_them(account_app):
    setup(account_app)
    for i in range(10):
        browser = client(account_app)
        result = browser.post(
            "/api/auth/login", json={"username": "OWNER" if i % 2 else "Owner", "password": "wrong"}
        )
        assert result.status_code == 401
    result = client(account_app).post(
        "/api/auth/login",
        json={"username": "Owner", "password": PASSWORD},
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    assert result.status_code == 429 and int(result.headers["Retry-After"]) >= 1
    with session_factory()() as session:
        value = session.get(Setting, "account_attempts:login").value
        assert value["total"] == 10 and "owner" not in str(value).lower()


def test_global_budget_also_bounds_identity_spraying(session):
    from app.account_http import attempt_budget
    from fastapi import HTTPException

    for i in range(100):
        attempt_budget(session, purpose="login", identity=f"different-{i}")
    with pytest.raises(HTTPException) as caught:
        attempt_budget(session, purpose="login", identity="yet-another")
    assert caught.value.status_code == 429


def test_member_cannot_administer_accounts_or_revoke_another_device(account_app):
    admin, _ = setup(account_app)
    created = admin.post("/api/admin/users", json={"username": "Member", "password": PASSWORD})
    assert created.status_code == 201 and not created.json()["is_admin"]
    member = client(account_app)
    assert (
        member.post("/api/auth/login", json={"username": "Member", "password": PASSWORD}).status_code == 200
    )
    assert member.get("/api/admin/users").status_code == 403
    assert (
        member.post(
            "/api/admin/users", json={"username": "Illegal", "password": PASSWORD, "is_admin": True}
        ).status_code
        == 403
    )
    admin_device = admin.get("/api/account/devices").json()[0]["id"]
    assert member.delete("/api/account/devices/" + admin_device).status_code == 404
    assert len(member.get("/api/account/devices").json()) == 1
    assert admin.get("/api/auth").json()["authenticated"]


def test_last_admin_protection_and_disable_revocation_through_http(account_app):
    admin, owner = setup(account_app)
    assert admin.delete("/api/admin/users/" + owner["id"]).status_code == 409
    user = admin.post("/api/admin/users", json={"username": "Member", "password": PASSWORD}).json()
    member = client(account_app)
    member.post("/api/auth/login", json={"username": "Member", "password": PASSWORD})
    assert admin.delete("/api/admin/users/" + user["id"]).status_code == 200
    assert member.get("/api/account/devices").status_code == 401
    assert (
        member.post("/api/auth/login", json={"username": "Member", "password": PASSWORD}).status_code == 401
    )


def test_logout_does_not_log_out_the_other_device(account_app):
    desktop, _ = setup(account_app)
    phone = client(account_app)
    phone.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
    assert desktop.post("/api/auth/logout").status_code == 200
    assert COOKIE not in desktop.cookies and LEGACY_COOKIE not in desktop.cookies
    assert desktop.get("/api/account/devices").status_code == 401
    assert phone.get("/api/account/devices").status_code == 200


def test_password_rotation_clears_cookies_and_revokes_other_devices(account_app):
    desktop, _ = setup(account_app)
    phone = client(account_app)
    phone.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
    rotated = desktop.post(
        "/api/account/password", json={"password": PASSWORD, "new_password": "synthetic rotated password"}
    )
    assert rotated.status_code == 200 and COOKIE not in desktop.cookies
    assert phone.get("/api/account/devices").status_code == 401
    assert (
        desktop.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 401
    )
    assert (
        desktop.post(
            "/api/auth/login", json={"username": "Owner", "password": "synthetic rotated password"}
        ).status_code
        == 200
    )


def test_optional_totp_enrollment_and_recovery_login_are_complete_http_operations(account_app):
    desktop, _ = setup(account_app)
    enrolled = desktop.post("/api/account/mfa/enroll", json={"password": PASSWORD})
    assert enrolled.status_code == 200 and enrolled.headers["cache-control"] == "no-store"
    secret = enrolled.json()["secret"]
    assert secret not in desktop.get("/api/auth").text
    confirmed = desktop.post(
        "/api/account/mfa/confirm", json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200
    recovery = confirmed.json()["recovery_codes"]
    assert len(recovery) == 8 and desktop.get("/api/auth").json()["user"]["mfa_enabled"]
    phone = client(account_app)
    assert phone.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 403
    result = phone.post(
        "/api/auth/login", json={"username": "Owner", "password": PASSWORD, "second_factor": recovery[0]}
    )
    assert result.status_code == 200
    assert phone.post("/api/auth/logout").status_code == 200
    assert (
        phone.post(
            "/api/auth/login", json={"username": "Owner", "password": PASSWORD, "second_factor": recovery[0]}
        ).status_code
        == 403
    )
    disabled = desktop.post("/api/account/mfa/disable", json={"password": PASSWORD, "code": recovery[1]})
    assert disabled.status_code == 200 and COOKIE not in desktop.cookies
    assert (
        desktop.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 200
    )


def test_cookie_migration_preserves_expiry_and_invalid_account_cookie_never_falls_back(account_app, session):
    owner = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
    grant = login(session, owner.username, PASSWORD)
    row = session.get(UserSession, grant.principal.session_id)
    original_expiry = row.token_record["expires_at"]
    row.lookup_hash, row.legacy_operator_key = None, "operator_session"
    session.commit()
    browser = client(account_app)
    browser.cookies.set(LEGACY_COOKIE, grant.token, domain="127.0.0.1", path="/")
    response = browser.get("/api/account/devices")
    assert response.status_code == 200 and COOKIE in browser.cookies
    assert LEGACY_COOKIE not in browser.cookies
    session.expire_all()
    row = session.get(UserSession, grant.principal.session_id)
    assert row.lookup_hash == hashlib.sha256(grant.token.encode()).hexdigest()
    assert row.token_record["expires_at"] == original_expiry
    session.commit()
    browser.cookies.clear()
    browser.cookies.set(LEGACY_COOKIE, grant.token, domain="127.0.0.1", path="/")
    browser.cookies.set(COOKIE, "invalid-cookie", domain="127.0.0.1", path="/")
    assert browser.get("/api/account/devices").status_code == 401


def test_https_private_authority_gets_secure_cookie(account_app, monkeypatch):
    setup(account_app)
    monkeypatch.setenv("AI_STATION_ACCESS_ORIGINS", "https://station.example.ts.net")
    clear_settings_cache()
    browser = TestClient(account_app, base_url="https://station.example.ts.net", client=("100.64.0.2", 50000))
    result = browser.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
    assert result.status_code == 200 and "Secure" in result.headers.get("set-cookie")


def test_expired_cookie_is_cleared_in_public_status_without_restoring_legacy_identity(account_app, session):
    owner = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
    grant = login(session, owner.username, PASSWORD)
    row = session.get(UserSession, grant.principal.session_id)
    row.token_record = {**row.token_record, "expires_at": (utcnow() - timedelta(seconds=1)).isoformat()}
    session.commit()
    browser = client(account_app)
    browser.cookies.set(COOKIE, grant.token, domain="127.0.0.1", path="/")
    response = browser.get("/api/auth")
    assert response.status_code == 200 and not response.json()["authenticated"]
    assert COOKIE not in browser.cookies


def test_sign_in_can_replace_the_oldest_device_at_the_session_limit(account_app, session):
    desktop, _ = setup(account_app)
    old_token = desktop.cookies.get(COOKIE)
    for _ in range(9):
        login(session, "Owner", PASSWORD)
    session.commit()
    result = desktop.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
    assert result.status_code == 200 and desktop.cookies.get(COOKIE) != old_token
    assert len(desktop.get("/api/account/devices").json()) == 10
    row = (
        session.query(UserSession).filter_by(lookup_hash=hashlib.sha256(old_token.encode()).hexdigest()).one()
    )
    assert row.revoked_at is not None


def test_successful_account_switch_revokes_old_device_and_private_api_disables_http_cache(account_app):
    browser, _ = setup(account_app)
    old_token = browser.cookies.get(COOKIE)
    browser.post("/api/admin/users", json={"username": "Member", "password": PASSWORD})
    result = browser.post("/api/auth/login", json={"username": "Member", "password": PASSWORD})
    assert result.status_code == 200 and result.json()["user"]["username"] == "Member"
    devices = browser.get("/api/account/devices")
    assert devices.headers["cache-control"] == "no-store" and len(devices.json()) == 1
    previous = client(account_app)
    previous.cookies.set(COOKIE, old_token, domain="127.0.0.1", path="/")
    assert previous.get("/api/account/devices").status_code == 401


def test_admin_reset_requires_reauthentication_and_revokes_target_devices(account_app):
    admin, _ = setup(account_app)
    user = admin.post("/api/admin/users", json={"username": "Member", "password": PASSWORD}).json()
    member = client(account_app)
    member.post("/api/auth/login", json={"username": "Member", "password": PASSWORD})
    path = "/api/admin/users/" + user["id"] + "/credentials"
    new_password = "synthetic reset password"
    assert member.post(path, json={"password": PASSWORD, "new_password": new_password}).status_code == 403
    assert admin.post(path, json={"password": "wrong", "new_password": new_password}).status_code == 403
    assert member.get("/api/auth").json()["authenticated"]
    response = admin.post(path, json={"password": PASSWORD, "new_password": new_password})
    assert response.status_code == 200 and new_password not in response.text
    assert member.get("/api/account/devices").status_code == 401
    assert (
        member.post("/api/auth/login", json={"username": "Member", "password": new_password}).status_code
        == 200
    )
    assert admin.get("/api/auth").json()["authenticated"]


def test_mfa_admin_reset_requires_second_factor_and_can_explicitly_reset_target_mfa(account_app):
    admin, _ = setup(account_app)
    user = admin.post("/api/admin/users", json={"username": "Member", "password": PASSWORD}).json()
    member = client(account_app)
    member.post("/api/auth/login", json={"username": "Member", "password": PASSWORD})
    codes = {}
    for name, browser in [("admin", admin), ("member", member)]:
        secret = browser.post("/api/account/mfa/enroll", json={"password": PASSWORD}).json()["secret"]
        codes[name] = browser.post(
            "/api/account/mfa/confirm", json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()}
        ).json()["recovery_codes"]
    path = "/api/admin/users/" + user["id"] + "/credentials"
    body = {"password": PASSWORD, "new_password": "synthetic reset password", "reset_mfa": True}
    assert admin.post(path, json=body).status_code == 403
    response = admin.post(path, json={**body, "second_factor": codes["admin"][0]})
    assert response.status_code == 200 and not response.json()["mfa_enabled"]
    assert member.get("/api/account/devices").status_code == 401
    assert (
        member.post(
            "/api/auth/login", json={"username": "Member", "password": "synthetic reset password"}
        ).status_code
        == 200
    )
