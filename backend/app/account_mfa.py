"""Optional TOTP with replay protection and one-use recovery codes.

Only enrollment returns a secret to its authenticated owner. Database records
hold a protected data-root secret reference; complete data-root backups retain
it. File removal is intentionally not performed inside rollbackable transactions.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.account_credentials import password_matches
from app.accounts import AccountError, Principal, _actor, _audit, revoke_sessions
from app.db import utcnow
from app.models import User, UserSession, UserSetting
from app.operator_auth import parse_time
from app.providers import ProviderError
from app.secrets import resolve_secret, store_secret_file

ENROLLMENT_KEY = "auth.totp_enrollment"
ENROLLMENT_SECONDS = 600


@dataclass(frozen=True, repr=False)
class Enrollment:
    secret: str
    provisioning_uri: str
    expires_at: str


def _user(session: Session, actor: Principal, password: str) -> User:
    _actor(session, actor)
    user = session.scalar(select(User).where(User.id == actor.user_id).with_for_update())
    if not password_matches(user.password_record, password):
        raise AccountError(403, "Current password is required")
    return user


def _secret(user: User, ref: str | None) -> str:
    prefix = f"file:secrets/accounts/{user.id}/totp-"
    if not ref or not ref.startswith(prefix) or "/" in ref[len(prefix) :]:
        raise AccountError(403, "Two-factor verification is unavailable; use local recovery")
    try:
        return resolve_secret(ref)
    except (OSError, ValueError, ProviderError) as exc:
        raise AccountError(403, "Two-factor verification is unavailable; use local recovery") from exc


def _step(secret: str, code: str, *, after: int | None = None) -> int | None:
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    now = int(utcnow().timestamp()) // 30
    try:
        totp = pyotp.TOTP(secret)
        for step in (now + 1, now, now - 1):
            if (after is None or step > after) and pyotp.utils.strings_equal(totp.at(step * 30), code):
                return step
    except (ValueError, TypeError):
        return None
    return None


def begin_enrollment(session: Session, actor: Principal, password: str) -> Enrollment:
    user = _user(session, actor, password)
    if user.totp_enabled_at is not None:
        raise AccountError(409, "Disable the existing authenticator before replacing it")
    secret = pyotp.random_base32()
    ref = store_secret_file(f"accounts/{user.id}/totp-{uuid4()}", secret)
    expires = (utcnow() + timedelta(seconds=ENROLLMENT_SECONDS)).isoformat()
    row = session.scalar(
        select(UserSetting)
        .where(
            UserSetting.user_id == user.id,
            UserSetting.key == ENROLLMENT_KEY,
        )
        .with_for_update()
    )
    value = {"secret_ref": ref, "expires_at": expires, "session_id": actor.session_id}
    if row is None:
        session.add(UserSetting(user_id=user.id, key=ENROLLMENT_KEY, value=value))
    else:
        row.value = value
    _audit(session, "account.mfa_enrollment_started", user, actor)
    return Enrollment(
        secret, pyotp.TOTP(secret).provisioning_uri(user.username, issuer_name="AI Station"), expires
    )


def _recovery_hash(user: User, code: str) -> str:
    return hashlib.sha256(f"ai-station-recovery:{user.id}:{code}".encode()).hexdigest()


def _new_recovery_codes(user: User) -> list[str]:
    values = [secrets.token_hex(16) for _ in range(8)]
    user.recovery_code_hashes = [_recovery_hash(user, value) for value in values]
    return ["-".join(value[i : i + 8] for i in range(0, 32, 8)) for value in values]


def confirm_enrollment(session: Session, actor: Principal, password: str, code: str) -> list[str]:
    user = _user(session, actor, password)
    if user.totp_enabled_at is not None:
        raise AccountError(409, "Two-factor authentication is already enabled")
    row = session.scalar(
        select(UserSetting)
        .where(
            UserSetting.user_id == user.id,
            UserSetting.key == ENROLLMENT_KEY,
        )
        .with_for_update()
    )
    value = row.value if row else {}
    expiry = parse_time(value.get("expires_at"))
    if expiry is None or expiry <= utcnow() or value.get("session_id") != actor.session_id:
        raise AccountError(403, "Start a new authenticator enrollment on this device")
    step = _step(_secret(user, value.get("secret_ref")), code)
    if step is None:
        raise AccountError(403, "Invalid verification code")
    now = utcnow()
    user.totp_secret_ref, user.totp_enabled_at, user.totp_last_step = value["secret_ref"], now, step
    codes = _new_recovery_codes(user)
    revoke_sessions(session, user.id, keep=actor.session_id)
    session.get(UserSession, actor.session_id).mfa_verified_at = now
    session.delete(row)
    _audit(session, "account.mfa_enabled", user, actor)
    return codes


def verify_second_factor(session: Session, user: User, code: str) -> None:
    """Caller locks the user. Success consumes the time step or recovery code."""
    if user.totp_enabled_at is None or not isinstance(code, str) or len(code) > 64:
        raise AccountError(403, "Invalid verification code")
    normalized = code.replace("-", "").lower()
    if re.fullmatch(r"[0-9a-f]{32}", normalized):
        target = _recovery_hash(user, normalized)
        remaining = [item for item in user.recovery_code_hashes if not hmac.compare_digest(item, target)]
        if len(remaining) != len(user.recovery_code_hashes):
            user.recovery_code_hashes = remaining
            _audit(session, "account.recovery_code_used", user)
            return
    else:
        step = _step(_secret(user, user.totp_secret_ref), code, after=user.totp_last_step)
        if step is not None:
            user.totp_last_step = step
            return
    raise AccountError(403, "Invalid verification code")


def regenerate_recovery_codes(session: Session, actor: Principal, password: str, code: str) -> list[str]:
    user = _user(session, actor, password)
    verify_second_factor(session, user, code)
    codes = _new_recovery_codes(user)
    _audit(session, "account.recovery_codes_regenerated", user, actor)
    return codes


def disable_mfa(session: Session, actor: Principal, password: str, code: str) -> None:
    user = _user(session, actor, password)
    verify_second_factor(session, user, code)
    user.totp_secret_ref, user.totp_enabled_at, user.totp_last_step = None, None, None
    user.recovery_code_hashes = []
    revoke_sessions(session, user.id)
    _audit(session, "account.mfa_disabled", user, actor)
