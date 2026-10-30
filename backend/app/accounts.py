"""Account services. Not exposed over HTTP before private-resource scoping ships.

Callers own transactions. A principal describes an authenticated device, never
an agent permission grant. Credentials and bearer tokens have no public model.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.account_credentials import make_password_record, password_matches, username_identity
from app.db import utcnow
from app.models import AccountEvent, Setting, User, UserSession
from app.operator_auth import (
    LAST_SEEN_MIN_WRITE_SECONDS,
    SESSION_ABSOLUTE_SECONDS,
    SESSION_IDLE_SECONDS,
    cookie_max_age,
    idle_seconds,
    parse_time,
    session_verdict,
)

COOKIE = "ais_session"
LEGACY_COOKIE = "ais_operator"
MAX_DEVICES = 10
REMEMBERED_SESSION_SECONDS = 30 * 24 * 3600


class AccountError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str
    is_admin: bool


@dataclass(frozen=True, repr=False)
class SessionGrant:
    token: str
    principal: Principal
    max_age: int


def public_user(user: User) -> dict:
    """Explicit allowlist: no deferred credential, MFA secret or recovery hash."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "enabled": user.enabled,
        "mfa_enabled": user.totp_enabled_at is not None,
        "recovery_required": not user.bootstrap_pending and not bool(user.password_record),
        "created_at": user.created_at,
    }


def _audit(session: Session, action: str, subject: User, actor: Principal | None = None) -> None:
    session.add(
        AccountEvent(
            actor_user_id=actor.user_id if actor else subject.id,
            subject_user_id=subject.id,
            action=action,
            details={},
        )
    )


def bootstrap_admin(session: Session, username: str, password: str, *, local_setup: bool) -> User:
    if not local_setup:
        raise AccountError(403, "First administrator setup requires local access")
    users = list(session.scalars(select(User).with_for_update()))
    if len(users) != 1 or not users[0].bootstrap_pending:
        raise AccountError(409, "Administrator setup is already completed or requires local recovery")
    display, identity = username_identity(username)
    record = make_password_record(password)
    user = users[0]
    user.username, user.normalized_username = display, identity
    user.display_name = display
    user.password_record = record
    user.password_changed_at = utcnow()
    user.enabled, user.bootstrap_pending = True, False
    _audit(session, "account.bootstrap_completed", user)
    session.flush()
    return user


def _verdict(row: UserSession, token: str, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    try:
        return session_verdict(row.token_record, token, now=now)
    except (AttributeError, TypeError, ValueError):
        return "invalid"


def _lookup(session: Session, token: str, *, legacy: bool) -> UserSession | None:
    if not isinstance(token, str) or not 1 <= len(token) <= 256:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    clause = UserSession.lookup_hash == digest
    if legacy:
        clause = or_(clause, UserSession.legacy_operator_key == "operator_session")
    for row in session.scalars(select(UserSession).where(clause).with_for_update()):
        if _verdict(row, token, utcnow()) in {"valid", "idle", "expired"}:
            return row
    return None


def authenticate(
    session: Session,
    token: str | None,
    *,
    legacy: bool = False,
    now: datetime | None = None,
) -> Principal | None:
    """Validate expiry, current account status and enrollment before refreshing idle time."""
    if not token:
        return None
    now = now or utcnow()
    row = _lookup(session, token, legacy=legacy)
    if row is None or _verdict(row, token, now) != "valid":
        return None
    user = session.get(User, row.user_id, populate_existing=True)
    if user is None or not user.enabled or user.bootstrap_pending:
        return None
    if user.totp_enabled_at is not None and (
        row.mfa_verified_at is None or row.mfa_verified_at < user.totp_enabled_at
    ):
        return None
    if user.password_changed_at is not None:
        issued = parse_time(row.token_record.get("issued_at"))
        if issued is None or issued < user.password_changed_at:
            return None
    last_seen = parse_time(row.token_record.get("last_seen_at"))
    if last_seen is None or (now - last_seen).total_seconds() >= LAST_SEEN_MIN_WRITE_SECONDS:
        row.token_record = {**row.token_record, "last_seen_at": now.isoformat()}
    return Principal(user.id, row.id, user.is_admin)


def authenticate_cookies(session: Session, cookies: dict[str, str]) -> Principal | None:
    # Presence wins, including an empty/expired account cookie: never fall back
    # to the previous device operator's privileged cookie after switching users.
    if COOKIE in cookies:
        return authenticate(session, cookies[COOKIE])
    return authenticate(session, cookies.get(LEGACY_COOKIE), legacy=True)


def _issue_session(
    session: Session, user: User, *, label: str = "", mfa_verified: bool = False, remember_me: bool = False
) -> SessionGrant:
    if not user.enabled or user.bootstrap_pending or (user.totp_enabled_at is not None and not mfa_verified):
        raise AccountError(403, "Additional verification is required")
    now = utcnow()
    active = []
    for row in session.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
        .with_for_update()
    ):
        expires = parse_time(row.token_record.get("expires_at"))
        seen = parse_time(row.token_record.get("last_seen_at")) or parse_time(
            row.token_record.get("issued_at")
        )
        if (
            expires is None
            or expires <= now
            or seen is None
            or seen + timedelta(seconds=idle_seconds(row.token_record)) <= now
        ):
            row.revoked_at = now
        else:
            active.append(row)
    if len(active) >= MAX_DEVICES:
        for row in sorted(active, key=lambda item: item.created_at)[: len(active) - MAX_DEVICES + 1]:
            row.revoked_at = now
    token, salt = secrets.token_hex(32), secrets.token_bytes(16)
    record = {
        "token_hash": hmac.new(salt, token.encode(), hashlib.sha256).hexdigest(),
        "salt": salt.hex(),
        "issued_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "expires_at": (
            now + timedelta(seconds=REMEMBERED_SESSION_SECONDS if remember_me else SESSION_ABSOLUTE_SECONDS)
        ).isoformat(),
        "idle_timeout_seconds": REMEMBERED_SESSION_SECONDS if remember_me else SESSION_IDLE_SECONDS,
        **({"remember_me": True} if remember_me else {}),
    }
    row = UserSession(
        user_id=user.id,
        lookup_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_record=record,
        label=label[:160],
        mfa_verified_at=now if mfa_verified else None,
    )
    session.add(row)
    session.flush()
    return SessionGrant(token, Principal(user.id, row.id, user.is_admin), cookie_max_age(record, now=now))


def login(
    session: Session,
    username: str,
    password: str,
    *,
    label: str = "",
    second_factor: str | None = None,
    remember_me: bool = False,
) -> SessionGrant:
    try:
        _, identity = username_identity(username)
    except ValueError:
        identity = ""
    user = session.scalar(select(User).where(User.normalized_username == identity).with_for_update())
    # Unknown and disabled identities perform the same bounded expensive work.
    record = (
        user.password_record
        if user
        else {
            "algorithm": "pbkdf2-sha256",
            "salt": "00" * 16,
            "hash": "00" * 32,
            "iterations": 600_000,
        }
    )
    valid = password_matches(record, password)
    if not valid or user is None or not user.enabled or user.bootstrap_pending:
        raise AccountError(401, "Invalid username or password")
    verified = False
    if user.totp_enabled_at is not None:
        from app.account_mfa import verify_second_factor

        if second_factor is None:
            raise AccountError(403, "Additional verification is required")
        verify_second_factor(session, user, second_factor)
        verified = True
    grant = _issue_session(session, user, label=label, mfa_verified=verified, remember_me=remember_me)
    _audit(session, "account.login", user, grant.principal)
    return grant


def _actor(session: Session, principal: Principal, *, admin: bool = False, lock: bool = False) -> User:
    user = session.get(User, principal.user_id, populate_existing=True, with_for_update=lock)
    device = session.get(UserSession, principal.session_id, populate_existing=True, with_for_update=lock)
    now = utcnow()
    if (
        user is None
        or device is None
        or device.user_id != user.id
        or device.revoked_at is not None
        or not user.enabled
        or user.bootstrap_pending
    ):
        raise AccountError(401, "Account login required")
    expires = parse_time(device.token_record.get("expires_at"))
    seen = parse_time(device.token_record.get("last_seen_at"))
    if (
        expires is None
        or expires <= now
        or seen is None
        or seen + timedelta(seconds=idle_seconds(device.token_record)) <= now
    ):
        raise AccountError(401, "Account login required")
    issued = parse_time(device.token_record.get("issued_at"))
    if user.password_changed_at is not None and (issued is None or issued < user.password_changed_at):
        raise AccountError(401, "Account login required")
    if user.totp_enabled_at is not None and (
        device.mfa_verified_at is None or device.mfa_verified_at < user.totp_enabled_at
    ):
        raise AccountError(401, "Additional verification is required")
    if admin and not user.is_admin:
        raise AccountError(403, "Administrator access required")
    return user


def create_user(
    session: Session, actor: Principal, username: str, password: str, *, is_admin: bool = False
) -> User:
    _actor(session, actor, admin=True)
    display, identity = username_identity(username)
    if session.scalar(select(User.id).where(User.normalized_username == identity)):
        raise AccountError(409, "Username is already in use")
    user = User(
        username=display,
        normalized_username=identity,
        display_name=display,
        password_record=make_password_record(password),
        password_changed_at=utcnow(),
        is_admin=is_admin,
    )
    session.add(user)
    session.flush()
    _audit(session, "account.created", user, actor)
    return user


def revoke_sessions(session: Session, user_id: str, *, keep: str | None = None) -> None:
    now = utcnow()
    for row in session.scalars(select(UserSession).where(UserSession.user_id == user_id).with_for_update()):
        if row.id != keep and row.revoked_at is None:
            row.revoked_at = now


def logout(session: Session, principal: Principal) -> None:
    user = _actor(session, principal)
    session.get(UserSession, principal.session_id).revoked_at = utcnow()
    _audit(session, "account.logout", user, principal)


def update_user(session: Session, actor: Principal, user_id: str, *, enabled: bool, is_admin: bool) -> User:
    _actor(session, actor, admin=True)
    users = list(session.scalars(select(User).with_for_update()))
    user = next((item for item in users if item.id == user_id), None)
    if user is None:
        raise AccountError(404, "Account not found")
    if user.bootstrap_pending:
        raise AccountError(409, "Complete local administrator setup first")
    if enabled and not user.password_record:
        raise AccountError(
            409, "Reset this recovered account's password and two-factor authentication before enabling it"
        )
    if (
        user.enabled
        and user.is_admin
        and not (enabled and is_admin)
        and not any(item.id != user.id and item.enabled and item.is_admin for item in users)
    ):
        raise AccountError(409, "At least one enabled administrator is required")
    # Revocation on either role change prevents stale privileged principals.
    if user.enabled != enabled or user.is_admin != is_admin:
        revoke_sessions(session, user.id)
        stop_account_work(session, user.id)
    user.enabled, user.is_admin = enabled, is_admin
    _audit(session, "account.updated", user, actor)
    return user


def stop_account_work(session: Session, user_id: str) -> None:
    """Revoke queued/active authority without signaling any host process here.

    Share the transaction through a savepoint, but use the subject's data scope
    so workflow cancellation cannot traverse another account's private graph.
    Native cancellation remains the worker's owned-process operation.
    """
    from app.data_access import DataScope, ScopedSession
    from app.data_context import bind_data_scope
    from app.models import Agent, Run
    from app.runs import request_cancel
    from app.state import TERMINAL

    session.flush()
    scope = DataScope(user_id, execution=True)
    with ScopedSession(
        bind=session.connection(), scope=scope, join_transaction_mode="create_savepoint"
    ) as owned:
        with bind_data_scope(scope):
            for agent in owned.scalars(select(Agent).where(Agent.enabled.is_(True))):
                agent.enabled, agent.next_run_at = False, None
            for run in list(owned.scalars(select(Run).where(Run.status.not_in(TERMINAL)))):
                if run.status not in TERMINAL and run.status != "cancel_requested":
                    request_cancel(owned, run)
            owned.commit()
    session.expire_all()


def change_password(session: Session, actor: Principal, current_password: str, new_password: str) -> None:
    user = _actor(session, actor)
    if not password_matches(user.password_record, current_password):
        raise AccountError(403, "Current password is required")
    record = make_password_record(new_password)
    user.password_record, user.password_changed_at = record, utcnow()
    revoke_sessions(session, user.id)
    _retire_legacy_operator(session, user)
    _audit(session, "account.password_changed", user, actor)


def _retire_legacy_operator(session: Session, user: User) -> None:
    if user.legacy_operator:
        # A password rotation must not leave the former operator password or
        # cookie as an alternate path through compatibility endpoints.
        for row in session.scalars(
            select(Setting).where(
                or_(
                    Setting.key.in_(["operator_auth", "operator_session"]),
                    Setting.key.startswith("operator_session:", autoescape=True),
                )
            )
        ):
            session.delete(row)
        user.legacy_operator = False


def reset_user_credentials(
    session: Session,
    actor: Principal,
    user_id: str,
    *,
    admin_password: str,
    new_password: str,
    second_factor: str | None = None,
    reset_mfa: bool = False,
) -> User:
    administrator = _actor(session, actor, admin=True)
    if not password_matches(administrator.password_record, admin_password):
        raise AccountError(403, "Current administrator password is required")
    if administrator.totp_enabled_at is not None:
        from app.account_mfa import verify_second_factor

        if second_factor is None:
            raise AccountError(403, "Additional verification is required")
        # Serialize replay/recovery consumption with other account operations.
        administrator = session.scalar(select(User).where(User.id == administrator.id).with_for_update())
        verify_second_factor(session, administrator, second_factor)
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise AccountError(404, "Account not found")
    if user.bootstrap_pending:
        raise AccountError(409, "Complete local administrator setup first")
    if not user.password_record and not reset_mfa:
        raise AccountError(409, "Reset two-factor authentication when recovering this quarantined account")
    user.password_record = make_password_record(new_password)
    user.password_changed_at = utcnow()
    revoke_sessions(session, user.id)
    _retire_legacy_operator(session, user)
    if reset_mfa:
        user.totp_secret_ref, user.totp_enabled_at, user.totp_last_step = None, None, None
        user.recovery_code_hashes = []
        _audit(session, "account.mfa_reset", user, actor)
    _audit(session, "account.password_reset", user, actor)
    return user


def list_devices(session: Session, actor: Principal) -> list[dict]:
    _actor(session, actor)
    result = []
    now = utcnow()
    for row in session.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == actor.user_id,
            UserSession.revoked_at.is_(None),
        )
        .order_by(UserSession.created_at.desc())
    ):
        expires = parse_time(row.token_record.get("expires_at"))
        seen = parse_time(row.token_record.get("last_seen_at"))
        if (
            expires is None
            or expires <= now
            or seen is None
            or seen + timedelta(seconds=idle_seconds(row.token_record)) <= now
        ):
            continue
        result.append(
            {
                "id": row.id,
                "label": row.label,
                "created_at": row.created_at,
                "last_seen_at": seen,
                "expires_at": expires,
                "current": row.id == actor.session_id,
            }
        )
    return result


def revoke_device(session: Session, actor: Principal, session_id: str) -> None:
    user = _actor(session, actor)
    row = session.scalar(
        select(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.user_id == user.id,
        )
        .with_for_update()
    )
    if row is None:
        raise AccountError(404, "Device session not found")
    row.revoked_at = row.revoked_at or utcnow()
    _audit(session, "account.device_revoked", user, actor)
