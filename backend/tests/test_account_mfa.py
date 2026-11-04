"""Real local TOTP algorithm, synthetic accounts/secrets, no network or devices."""

import json
from datetime import timedelta

import pyotp
import pytest
from app.account_mfa import (
    ENROLLMENT_KEY,
    begin_enrollment,
    confirm_enrollment,
    disable_mfa,
    regenerate_recovery_codes,
)
from app.accounts import (
    AccountError,
    authenticate,
    bootstrap_admin,
    create_user,
    login,
    public_user,
)
from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import AccountEvent, UserSession, UserSetting

PASSWORD = "synthetic owner password"


@pytest.fixture
def owner(session):
    user = bootstrap_admin(session, "Owner", PASSWORD, local_setup=True)
    grant = login(session, "Owner", PASSWORD)
    session.commit()
    return user, grant


def enable(session, owner):
    user, grant = owner
    enrollment = begin_enrollment(session, grant.principal, PASSWORD)
    session.commit()
    codes = confirm_enrollment(session, grant.principal, PASSWORD, pyotp.TOTP(enrollment.secret).now())
    session.commit()
    return user, grant, enrollment, codes


def test_enrollment_secret_is_a_protected_file_not_a_database_value(session, owner):
    user, grant = owner
    enrollment = begin_enrollment(session, grant.principal, PASSWORD)
    session.commit()
    row = session.query(UserSetting).filter_by(user_id=user.id, key=ENROLLMENT_KEY).one()
    assert enrollment.secret not in json.dumps(row.value)
    path = get_settings().data_dir / row.value["secret_ref"][5:]
    assert path.read_text() == enrollment.secret
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert pyotp.parse_uri(enrollment.provisioning_uri).secret == enrollment.secret
    assert enrollment.secret not in repr(enrollment)
    assert not public_user(user)["mfa_enabled"]


def test_wrong_password_does_not_start_or_replace_enrollment(session, owner):
    _, grant = owner
    with pytest.raises(AccountError, match="Current password"):
        begin_enrollment(session, grant.principal, "incorrect")
    assert session.query(UserSetting).filter_by(key=ENROLLMENT_KEY).count() == 0


def test_pending_enrollment_is_bound_to_the_device_and_expires(session, owner):
    user, grant = owner
    enrollment = begin_enrollment(session, grant.principal, PASSWORD)
    second = login(session, user.username, PASSWORD)
    session.commit()
    with pytest.raises(AccountError, match="on this device"):
        confirm_enrollment(session, second.principal, PASSWORD, pyotp.TOTP(enrollment.secret).now())
    row = session.query(UserSetting).filter_by(user_id=user.id, key=ENROLLMENT_KEY).one()
    row.value = {**row.value, "expires_at": (utcnow() - timedelta(seconds=1)).isoformat()}
    session.commit()
    with pytest.raises(AccountError, match="new authenticator enrollment"):
        confirm_enrollment(session, grant.principal, PASSWORD, pyotp.TOTP(enrollment.secret).now())
    assert user.totp_enabled_at is None


def test_renewed_enrollment_replaces_the_old_secret_and_preserves_pending_login(session, owner):
    user, grant = owner
    first = begin_enrollment(session, grant.principal, PASSWORD)
    second = begin_enrollment(session, grant.principal, PASSWORD)
    session.commit()
    row = session.query(UserSetting).filter_by(user_id=user.id, key=ENROLLMENT_KEY).one()
    assert first.secret != second.secret
    assert (get_settings().data_dir / row.value["secret_ref"][5:]).read_text() == second.secret
    assert authenticate(session, grant.token) == grant.principal
    assert user.totp_enabled_at is None


def test_mfa_activation_keeps_confirmed_device_and_revokes_other_sessions(session, owner):
    user, grant = owner
    other = login(session, user.username, PASSWORD)
    session.commit()
    _, _, enrollment, codes = enable(session, owner)
    assert authenticate(session, grant.token) == grant.principal
    assert authenticate(session, other.token) is None
    assert public_user(user)["mfa_enabled"]
    assert session.query(UserSetting).filter_by(key=ENROLLMENT_KEY).count() == 0
    assert len(codes) == len(set(codes)) == 8
    serialized = json.dumps(user.recovery_code_hashes)
    assert all(code not in serialized and code.replace("-", "") not in serialized for code in codes)
    assert enrollment.secret not in json.dumps(public_user(user), default=str)
    with pytest.raises(AccountError, match="Additional verification"):
        login(session, user.username, PASSWORD)
    with pytest.raises(AccountError, match="already enabled"):
        confirm_enrollment(session, grant.principal, PASSWORD, pyotp.TOTP(enrollment.secret).now())


def test_login_consumes_totp_time_step_and_replay_cannot_issue_another_cookie(session, owner):
    user, _, enrollment, _ = enable(session, owner)
    # Enrollment itself consumes its code. Use a later real counter while
    # freezing the service clock, without waiting or weakening verification.
    import app.account_mfa as mfa

    now = utcnow() + timedelta(seconds=60)
    original_now = mfa.utcnow
    mfa.utcnow = lambda: now
    try:
        code = pyotp.TOTP(enrollment.secret).at(now)
        grant = login(session, user.username, PASSWORD, second_factor=code)
        session.commit()
        assert session.get(UserSession, grant.principal.session_id).mfa_verified_at is not None
        assert authenticate(session, grant.token) == grant.principal
        count = session.query(UserSession).count()
        with pytest.raises(AccountError, match="Invalid verification code"):
            login(session, user.username, PASSWORD, second_factor=code)
        assert session.query(UserSession).count() == count
    finally:
        mfa.utcnow = original_now


def test_recovery_code_is_one_use_even_after_database_reopen(session, owner):
    user, _, _, codes = enable(session, owner)
    grant = login(session, user.username, PASSWORD, second_factor=codes[0])
    session.commit()
    assert len(user.recovery_code_hashes) == 7
    assert authenticate(session, grant.token) == grant.principal
    session.commit()
    with session_factory()() as reopened:
        with pytest.raises(AccountError, match="Invalid verification code"):
            login(reopened, user.username, PASSWORD, second_factor=codes[0])
    assert session.query(AccountEvent).filter_by(action="account.recovery_code_used").count() == 1


def test_bad_password_never_consumes_a_recovery_code(session, owner):
    user, _, _, codes = enable(session, owner)
    with pytest.raises(AccountError, match="Invalid username or password"):
        login(session, user.username, "incorrect", second_factor=codes[0])
    assert len(user.recovery_code_hashes) == 8
    assert login(session, user.username, PASSWORD, second_factor=codes[0]).principal.user_id == user.id


def test_recovery_codes_are_not_valid_for_another_account(session, owner):
    user, owner_grant = owner
    other = create_user(session, owner_grant.principal, "Member", PASSWORD)
    member = login(session, other.username, PASSWORD)
    session.commit()
    _, _, _, owner_codes = enable(session, owner)
    _, _, _, other_codes = enable(session, (other, member))
    with pytest.raises(AccountError, match="Invalid verification code"):
        login(session, other.username, PASSWORD, second_factor=owner_codes[0])
    assert len(other.recovery_code_hashes) == 8
    assert (
        login(session, other.username, PASSWORD, second_factor=other_codes[0]).principal.user_id == other.id
    )
    assert user.id != other.id


def test_recovery_regeneration_requires_both_factors_and_invalidates_old_codes(session, owner):
    user, grant, _, codes = enable(session, owner)
    with pytest.raises(AccountError, match="Current password"):
        regenerate_recovery_codes(session, grant.principal, "incorrect", codes[0])
    fresh = regenerate_recovery_codes(session, grant.principal, PASSWORD, codes[0])
    session.commit()
    assert len(fresh) == 8 and not set(fresh) & set(codes)
    with pytest.raises(AccountError, match="Invalid verification code"):
        login(session, user.username, PASSWORD, second_factor=codes[1])
    assert login(session, user.username, PASSWORD, second_factor=fresh[0]).principal.user_id == user.id


def test_disable_requires_both_factors_and_revokes_all_old_sessions(session, owner):
    user, grant, _, codes = enable(session, owner)
    with pytest.raises(AccountError, match="Invalid verification code"):
        disable_mfa(session, grant.principal, PASSWORD, "invalid")
    assert user.totp_enabled_at is not None
    disable_mfa(session, grant.principal, PASSWORD, codes[0])
    session.commit()
    assert user.totp_enabled_at is None and user.totp_secret_ref is None and user.recovery_code_hashes == []
    assert authenticate(session, grant.token) is None
    assert login(session, user.username, PASSWORD).principal.user_id == user.id


def test_missing_mfa_secret_fails_closed_but_stored_recovery_code_still_works(session, owner):
    user, _, _, codes = enable(session, owner)
    path = get_settings().data_dir / user.totp_secret_ref[5:]
    path.unlink()
    with pytest.raises(AccountError, match="unavailable"):
        login(session, user.username, PASSWORD, second_factor="123456")
    assert login(session, user.username, PASSWORD, second_factor=codes[0]).principal.user_id == user.id
