"""Temporary SQLite service tests; account APIs are deliberately not enabled yet."""

import hashlib
import json
from datetime import timedelta

import pytest
from app.accounts import (
    COOKIE,
    LEGACY_COOKIE,
    AccountError,
    authenticate,
    authenticate_cookies,
    bootstrap_admin,
    change_password,
    create_user,
    list_devices,
    login,
    logout,
    public_user,
    revoke_device,
    update_user,
)
from app.db import session_factory, utcnow
from app.models import AccountEvent, Setting, User, UserSession

PASSWORD = "synthetic owner password"


@pytest.fixture
def owner(session):
    user = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
    grant = login(session, "OWNER", PASSWORD)
    session.commit()
    return user, grant


def test_bootstrap_consumes_the_existing_reserved_admin_and_cannot_be_claimed_twice(session):
    reserved = session.query(User).one().id
    with pytest.raises(AccountError, match="local access"):
        bootstrap_admin(session, "Owner", PASSWORD, local_setup=False)
    user = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
    assert user.id == reserved and user.enabled and user.is_admin and not user.bootstrap_pending
    session.commit()
    with pytest.raises(AccountError, match="already completed"):
        bootstrap_admin(session, "Attacker", "different password", local_setup=True)
    assert session.query(User).one().username == "Owner"


def test_unconfigured_admin_cannot_log_in(session):
    with pytest.raises(AccountError, match="Invalid username or password"):
        login(session, "admin", PASSWORD)
    assert session.query(UserSession).count() == 0


def test_login_reopens_from_durable_hashes_without_renewing_absolute_expiry(session, owner):
    user, grant = owner
    row = session.get(UserSession, grant.principal.session_id)
    expires = row.token_record["expires_at"]
    assert row.lookup_hash == hashlib.sha256(grant.token.encode()).hexdigest()
    assert grant.token not in json.dumps(row.token_record)
    assert PASSWORD not in json.dumps(user.password_record)
    assert grant.token not in repr(grant)
    session.commit()
    with session_factory()() as reopened:
        principal = authenticate(reopened, grant.token)
        assert principal == grant.principal
        assert reopened.get(UserSession, principal.session_id).token_record["expires_at"] == expires
    assert grant.max_age == 1800


@pytest.mark.parametrize(
    "username,password", [("missing", PASSWORD), ("Owner", "wrong"), ("../bad", PASSWORD)]
)
def test_login_does_not_disclose_account_existence(session, owner, username, password):
    count = session.query(UserSession).count()
    with pytest.raises(AccountError) as caught:
        login(session, username, password)
    assert caught.value.status == 401 and str(caught.value) == "Invalid username or password"
    assert session.query(UserSession).count() == count


def test_lookup_hash_alone_cannot_authenticate_or_refresh_a_session(session, owner):
    _, grant = owner
    row = session.get(UserSession, grant.principal.session_id)
    original = dict(row.token_record)
    row.lookup_hash = hashlib.sha256(b"forged-token").hexdigest()
    session.commit()
    assert authenticate(session, "forged-token") is None
    assert row.token_record == original


@pytest.mark.parametrize("age", [timedelta(minutes=31), timedelta(hours=13)])
def test_idle_and_absolute_expiry_do_not_refresh_expired_sessions(session, owner, age):
    _, grant = owner
    row = session.get(UserSession, grant.principal.session_id)
    original = dict(row.token_record)
    assert authenticate(session, grant.token, now=utcnow() + age) is None
    assert row.token_record == original


def test_authenticated_activity_extends_idle_only(session, owner):
    _, grant = owner
    row = session.get(UserSession, grant.principal.session_id)
    original = dict(row.token_record)
    now = utcnow() + timedelta(minutes=2)
    assert authenticate(session, grant.token, now=now) == grant.principal
    assert row.token_record["last_seen_at"] == now.isoformat()
    assert row.token_record["issued_at"] == original["issued_at"]
    assert row.token_record["expires_at"] == original["expires_at"]


def test_logout_revokes_only_the_current_device_and_survives_reopen(session, owner):
    _, first = owner
    second = login(session, "Owner", PASSWORD, label="Phone")
    logout(session, first.principal)
    session.commit()
    with session_factory()() as reopened:
        assert authenticate(reopened, first.token) is None
        assert authenticate(reopened, second.token) == second.principal
    assert session.query(AccountEvent).filter_by(action="account.logout").count() == 1


@pytest.mark.parametrize("value", ["", "invalid", "expired-cookie"])
def test_account_cookie_never_falls_back_to_old_operator_identity(session, owner, value):
    _, grant = owner
    row = session.get(UserSession, grant.principal.session_id)
    row.lookup_hash, row.legacy_operator_key = None, "operator_session"
    session.commit()
    assert authenticate_cookies(session, {LEGACY_COOKIE: grant.token}) == grant.principal
    assert authenticate_cookies(session, {COOKIE: value, LEGACY_COOKIE: grant.token}) is None


def test_admin_creates_users_without_exposing_private_credential_fields(session, owner):
    _, grant = owner
    user = create_user(session, grant.principal, "Łukasz", "synthetic user password")
    session.commit()
    assert not user.is_admin and user.enabled
    assert login(session, "ŁUKASZ", "synthetic user password").principal.user_id == user.id
    public = public_user(user)
    assert set(public) == {
        "id",
        "username",
        "display_name",
        "is_admin",
        "enabled",
        "mfa_enabled",
        "created_at",
    }
    with pytest.raises(AccountError, match="already in use"):
        create_user(session, grant.principal, "ŁUKASZ", PASSWORD)


def test_ordinary_user_cannot_create_users_or_change_admin_roles(session, owner):
    admin, grant = owner
    user = create_user(session, grant.principal, "Member", PASSWORD)
    member = login(session, user.username, PASSWORD)
    session.commit()
    with pytest.raises(AccountError) as caught:
        create_user(session, member.principal, "Other", PASSWORD)
    assert caught.value.status == 403
    with pytest.raises(AccountError):
        update_user(session, member.principal, admin.id, enabled=False, is_admin=False)
    assert admin.is_admin and admin.enabled


@pytest.mark.parametrize("enabled,is_admin", [(False, True), (True, False), (False, False)])
def test_last_enabled_admin_cannot_be_disabled_or_demoted(session, owner, enabled, is_admin):
    admin, grant = owner
    with pytest.raises(AccountError, match="At least one enabled administrator"):
        update_user(session, grant.principal, admin.id, enabled=enabled, is_admin=is_admin)
    assert authenticate(session, grant.token) == grant.principal


def test_disable_revokes_all_devices_and_enabling_never_revives_old_cookies(session, owner):
    _, grant = owner
    user = create_user(session, grant.principal, "Member", PASSWORD)
    devices = [login(session, "Member", PASSWORD), login(session, "Member", PASSWORD)]
    update_user(session, grant.principal, user.id, enabled=False, is_admin=False)
    session.commit()
    for device in devices:
        assert authenticate(session, device.token) is None
    with pytest.raises(AccountError, match="Invalid username or password"):
        login(session, "Member", PASSWORD)
    update_user(session, grant.principal, user.id, enabled=True, is_admin=False)
    session.commit()
    assert all(authenticate(session, device.token) is None for device in devices)
    assert login(session, "Member", PASSWORD).principal.user_id == user.id


def test_demoted_admin_cannot_use_a_stale_principal(session, owner):
    admin, grant = owner
    second = create_user(session, grant.principal, "Second", PASSWORD, is_admin=True)
    second_session = login(session, second.username, PASSWORD)
    update_user(session, second_session.principal, admin.id, enabled=True, is_admin=False)
    session.commit()
    with pytest.raises(AccountError):
        create_user(session, grant.principal, "Illegal", PASSWORD)


def test_password_rotation_revokes_every_device_and_legacy_bypass(session, owner):
    user, grant = owner
    second = login(session, user.username, PASSWORD)
    user.legacy_operator = True
    session.add(Setting(key="operator_auth", value=dict(user.password_record)))
    session.add(Setting(key="operator_session", value={"legacy": True}))
    session.commit()
    with pytest.raises(AccountError, match="Current password"):
        change_password(session, grant.principal, "incorrect", "new synthetic password")
    change_password(session, grant.principal, PASSWORD, "new synthetic password")
    session.commit()
    assert not user.legacy_operator
    assert session.get(Setting, "operator_auth") is None and session.get(Setting, "operator_session") is None
    assert authenticate(session, grant.token) is None and authenticate(session, second.token) is None
    with pytest.raises(AccountError):
        login(session, user.username, PASSWORD)
    assert login(session, user.username, "new synthetic password").principal.user_id == user.id


def test_device_limit_is_per_user_and_revokes_oldest_only(session, owner):
    _, owner_grant = owner
    member = create_user(session, owner_grant.principal, "Member", PASSWORD)
    grants = [login(session, member.username, PASSWORD) for _ in range(11)]
    session.commit()
    assert authenticate(session, grants[0].token) is None
    assert all(authenticate(session, grant.token) for grant in grants[1:])
    assert authenticate(session, owner_grant.token) == owner_grant.principal


def test_mfa_enabled_account_never_gets_password_only_session(session, owner):
    user, grant = owner
    user.totp_enabled_at = utcnow()
    session.commit()
    assert authenticate(session, grant.token) is None
    with pytest.raises(AccountError, match="Additional verification"):
        login(session, user.username, PASSWORD)
    assert session.query(UserSession).count() == 1


def test_device_management_cannot_enumerate_or_revoke_another_users_session(session, owner):
    _, admin = owner
    user = create_user(session, admin.principal, "Member", PASSWORD)
    member = login(session, user.username, PASSWORD, label="Member phone")
    session.commit()
    devices = list_devices(session, member.principal)
    assert [item["id"] for item in devices] == [member.principal.session_id]
    assert devices[0]["current"] and devices[0]["label"] == "Member phone"
    assert not {"lookup_hash", "token_record", "legacy_operator_key"} & set(devices[0])
    with pytest.raises(AccountError) as caught:
        revoke_device(session, member.principal, admin.principal.session_id)
    assert caught.value.status == 404
    assert authenticate(session, admin.token) == admin.principal
    revoke_device(session, member.principal, member.principal.session_id)
    session.commit()
    assert authenticate(session, member.token) is None
