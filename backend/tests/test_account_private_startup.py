"""Account-profile private startup must not depend on retired operator secrets."""

import pytest
from app.account_credentials import make_password_record, password_record_valid
from app.accounts import bootstrap_admin, change_password, login
from app.bootstrap_setup import administrator_configured
from app.config import clear_settings_cache
from app.db import control_session_factory
from app.models import Setting, User
from app.operator_auth import refuse_non_loopback_bind
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_account_private_api import private_app as private_app

PASSWORD = "synthetic private startup password"
LAN = "http://192.168.20.5:8765"


def enable_lan(monkeypatch):
    monkeypatch.setenv("AI_STATION_LAN_HOST", "192.168.20.5")
    clear_settings_cache()


def admin():
    with control_session_factory()() as session:
        user = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
        session.commit()
        return user.id


def test_account_admin_can_start_and_sign_in_over_reviewed_lan_without_legacy_password(
    private_app, monkeypatch
):
    admin()
    enable_lan(monkeypatch)
    with control_session_factory()() as session:
        assert session.get(Setting, "operator_auth") is None
        assert administrator_configured(session)
        assert refuse_non_loopback_bind(session, accounts_active=True)["allowed"]
    with TestClient(private_app, base_url=LAN, client=("192.168.20.8", 50000)) as phone:
        assert phone.get("/api/health").status_code == 200
        assert phone.get("/api/runs").status_code == 401
        response = phone.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD})
        assert response.status_code == 200, response.text
        assert response.json()["user"]["is_admin"]
        assert phone.get("/api/runs").status_code == 200


@pytest.mark.parametrize("state", ["pending", "disabled", "member", "missing", "malformed"])
def test_private_account_startup_refuses_unusable_admin_even_with_an_old_operator_secret(monkeypatch, state):
    if state != "pending":
        admin()
    with control_session_factory()() as session:
        user = session.scalar(select(User))
        if state == "disabled":
            user.enabled = False
        elif state == "member":
            user.is_admin = False
        elif state == "missing":
            user.password_record = {}
        elif state == "malformed":
            user.password_record = {"algorithm": "pbkdf2-sha256", "hash": "not-a-hash", "salt": "xx"}
        session.add(Setting(key="operator_auth", value=make_password_record(PASSWORD)))
        session.commit()
        enable_lan(monkeypatch)
        assert not administrator_configured(session)
        with pytest.raises(RuntimeError, match="administrator account"):
            refuse_non_loopback_bind(session, accounts_active=True)


def test_account_readiness_never_turns_on_the_dormant_profile_or_public_bind(monkeypatch):
    admin()
    enable_lan(monkeypatch)
    with control_session_factory()() as session:
        with pytest.raises(RuntimeError, match="operator password"):
            refuse_non_loopback_bind(session)
        monkeypatch.setenv("AI_STATION_BIND_HOST", "0.0.0.0")
        clear_settings_cache()
        with pytest.raises(RuntimeError):
            refuse_non_loopback_bind(session, accounts_active=True)


def test_retiring_the_legacy_password_does_not_break_account_private_startup(private_app, monkeypatch):
    user_id = admin()
    replacement = "replacement account password 2026"
    with control_session_factory()() as session:
        session.get(User, user_id).legacy_operator = True
        session.add(Setting(key="operator_auth", value=make_password_record(PASSWORD)))
        actor = login(session, "Owner", PASSWORD).principal
        change_password(session, actor, PASSWORD, replacement)
        session.commit()
        assert session.get(Setting, "operator_auth") is None
        enable_lan(monkeypatch)
        assert refuse_non_loopback_bind(session, accounts_active=True)["allowed"]
    with TestClient(private_app, base_url=LAN, client=("192.168.20.8", 50000)) as phone:
        assert (
            phone.post("/api/auth/login", json={"username": "Owner", "password": PASSWORD}).status_code == 401
        )
        response = phone.post("/api/auth/login", json={"username": "Owner", "password": replacement})
        assert response.status_code == 200 and response.json()["user"]["id"] == user_id


@pytest.mark.parametrize("record", [None, {}, [], {"algorithm": "other"}, {"iterations": 10**100}])
def test_invalid_password_records_do_not_count_as_configured_credentials(record):
    assert not password_record_valid(record)
