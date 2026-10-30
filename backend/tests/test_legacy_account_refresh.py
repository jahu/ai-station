"""Cutover reads current operator credentials, not an earlier migration snapshot."""

import hashlib
from datetime import timedelta

import pytest
from app import models as m
from app.account_profile import KEY, prepare_profile
from app.accounts import AccountError, authenticate, login
from app.config import clear_settings_cache
from app.db import control_session_factory, utcnow
from app.operator_auth import SESSION_KEY, SETUP_KEY, clear_all_sessions, issue_session, save_secret
from fastapi import Response
from sqlalchemy import select
from starlette.requests import Request

PASSWORD = "synthetic original operator password"
NEW_PASSWORD = "synthetic rotated operator password"


def device(session):
    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [(b"host", b"127.0.0.1:8765")]}
    )
    return issue_session(session, Response(), request)


def snapshot_operator(session):
    user = session.scalar(select(m.User))
    save_secret(session, PASSWORD)
    session.flush()
    source = session.get(m.Setting, SETUP_KEY).value
    user.password_record = {key: source[key] for key in ("algorithm", "salt", "hash", "iterations")}
    user.enabled, user.bootstrap_pending, user.legacy_operator = True, False, True
    token = device(session)
    source = session.get(m.Setting, SESSION_KEY)
    row = m.UserSession(user_id=user.id, token_record=dict(source.value), legacy_operator_key=SESSION_KEY)
    session.add(row)
    session.commit()
    return user, token, row


def activate(session, monkeypatch):
    monkeypatch.setenv("AI_STATION_ACCESS_PROFILE", "accounts")
    clear_settings_cache()
    receipt = prepare_profile(session)
    session.commit()
    return receipt


def test_password_rotation_and_reused_session_key_import_current_identity(monkeypatch):
    with control_session_factory()() as session:
        user, old_token, old_row = snapshot_operator(session)
        user_id, old_id = user.id, old_row.id
        save_secret(session, NEW_PASSWORD)
        clear_all_sessions(session)
        new_token = device(session)
        session.commit()
        receipt = activate(session, monkeypatch)
        assert receipt["identity_refresh"]["credential_changed"]
        assert receipt["identity_refresh"]["sessions_added"] == 1
        assert authenticate(session, old_token, legacy=True) is None
        current = authenticate(session, new_token, legacy=True)
        assert current.user_id == user_id and current.session_id != old_id
        assert session.get(m.UserSession, old_id).revoked_at is not None
        with pytest.raises(AccountError):
            login(session, user.username, PASSWORD)
        assert login(session, user.username, NEW_PASSWORD).principal.user_id == user_id
        assert not any(field in str(receipt) for field in ("token_hash", "salt", "iterations"))


def test_password_configured_after_migration_closes_pending_setup(monkeypatch):
    with control_session_factory()() as session:
        user = session.scalar(select(m.User))
        assert user.bootstrap_pending
        save_secret(session, PASSWORD)
        token = device(session)
        session.commit()
        activate(session, monkeypatch)
        assert user.enabled and not user.bootstrap_pending
        assert authenticate(session, token, legacy=True).user_id == user.id
        assert login(session, user.username, PASSWORD).principal.user_id == user.id


@pytest.mark.parametrize("revoked", [False, True])
def test_unchanged_session_keeps_identity_and_never_resurrects_revocation(monkeypatch, revoked):
    with control_session_factory()() as session:
        user, token, row = snapshot_operator(session)
        identity = row.id
        seen = utcnow() + timedelta(seconds=1)
        row.token_record = {**row.token_record, "last_seen_at": seen.isoformat()}
        row.revoked_at = utcnow() if revoked else None
        session.commit()
        activate(session, monkeypatch)
        principal = authenticate(session, token, legacy=True)
        assert (principal is None) == revoked
        if principal:
            assert principal.session_id == identity and principal.user_id == user.id
        assert session.get(m.UserSession, identity).token_record["last_seen_at"] == seen.isoformat()


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_invalid_password_quarantines_staged_identity(monkeypatch, missing):
    with control_session_factory()() as session:
        user, token, _ = snapshot_operator(session)
        source = session.get(m.Setting, SETUP_KEY)
        if missing:
            session.delete(source)
        else:
            source.value = {"hash": "invalid"}
        session.commit()
        receipt = activate(session, monkeypatch)
        assert receipt["identity_refresh"]["status"] == "quarantined"
        assert not user.enabled and not user.bootstrap_pending
        assert authenticate(session, token, legacy=True) is None
        with pytest.raises(AccountError):
            login(session, user.username, PASSWORD)


def test_logged_out_devices_stay_out_and_current_devices_are_imported_once(monkeypatch):
    with control_session_factory()() as session:
        _, old_token, old = snapshot_operator(session)
        session.delete(session.get(m.Setting, SESSION_KEY))
        # Keep another device under the suffixed lookup used by operator mode.
        replacement = device(session)
        source = session.get(m.Setting, SESSION_KEY)
        source.key = SESSION_KEY + ":" + hashlib.sha256(replacement.encode()).hexdigest()
        session.commit()
        activate(session, monkeypatch)
        assert old.revoked_at is not None and authenticate(session, old_token, legacy=True) is None
        assert authenticate(session, replacement, legacy=True) is not None
        saved = session.get(m.Setting, KEY).value
        save_secret(session, NEW_PASSWORD)
        session.commit()
        assert prepare_profile(session) == saved
        assert login(session, "admin", PASSWORD)


def test_account_native_identity_is_not_overwritten_by_stale_operator_setting(monkeypatch):
    with control_session_factory()() as session:
        user, _, _ = snapshot_operator(session)
        user.legacy_operator = False
        credential = dict(user.password_record)
        save_secret(session, NEW_PASSWORD)
        session.commit()
        receipt = activate(session, monkeypatch)
        assert receipt["identity_refresh"] is None and user.password_record == credential
        assert login(session, user.username, PASSWORD)


def test_operator_refresh_preserves_disabled_account_and_role(monkeypatch):
    with control_session_factory()() as session:
        user, token, _ = snapshot_operator(session)
        user.enabled, user.is_admin = False, False
        session.commit()
        activate(session, monkeypatch)
        assert not user.enabled and not user.is_admin
        assert authenticate(session, token, legacy=True) is None
        with pytest.raises(AccountError):
            login(session, user.username, PASSWORD)
