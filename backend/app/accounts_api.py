"""Account API, registered only with the complete ownership/authentication cutover."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import account_mfa, accounts
from app.account_credentials import username_identity
from app.account_http import attach_cookie, attempt_budget, clear_cookies
from app.db import control_session_scope
from app.models import User, UserSession
from app.private_access import private_access_enabled, secure_cookie

router = APIRouter(prefix="/api", tags=["accounts"])
DB = Annotated[Session, Depends(control_session_scope)]


class IdentityPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        return username_identity(value)[0]


class Credentials(IdentityPassword):
    second_factor: SecretStr | None = Field(default=None, min_length=1, max_length=64)


class Setup(IdentityPassword):
    password: SecretStr = Field(min_length=12, max_length=200)


class CreateUser(Setup):
    is_admin: StrictBool = False


class UserPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    is_admin: StrictBool


class Reauthenticate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=200)


class VerifyFactor(Reauthenticate):
    code: SecretStr = Field(min_length=1, max_length=64)


class ChangePassword(Reauthenticate):
    new_password: SecretStr = Field(min_length=12, max_length=200)


class ResetCredentials(ChangePassword):
    second_factor: SecretStr | None = Field(default=None, min_length=1, max_length=64)
    reset_mfa: StrictBool = False


def principal(request: Request, session: DB) -> accounts.Principal:
    value = getattr(request.state, "account_principal", None)
    if not isinstance(value, accounts.Principal):
        raise HTTPException(401, "Account login required")
    accounts._actor(session, value)
    return value


Actor = Annotated[accounts.Principal, Depends(principal)]


def _status(session, actor) -> dict:
    pending = session.scalar(select(User.id).where(User.bootstrap_pending.is_(True))) is not None
    user = session.get(User, actor.user_id) if actor else None
    device = session.get(UserSession, actor.session_id) if actor else None
    return {
        "authenticated": user is not None,
        "setup_required": pending,
        "user": accounts.public_user(user) if user else None,
        "session_idle_seconds": 1800,
        "session_max_age_seconds": 43200,
        "expires_at": device.token_record.get("expires_at") if device else None,
    }


@router.get("/auth")
def status(request: Request, response: Response, session: DB):
    response.headers["Cache-Control"] = "no-store"
    return _status(session, getattr(request.state, "account_principal", None))


@router.post("/auth/setup", status_code=201)
def setup(body: Setup, request: Request, response: Response, session: DB):
    peer = request.client.host if request.client else ""
    host = request.url.hostname or ""
    local = peer in {"127.0.0.1", "::1"} and host in {"127.0.0.1", "::1", "localhost"}
    # Fresh setup must finish on loopback before enabling any reverse proxy/LAN
    # service; a proxy's loopback peer is not authority to claim an administrator.
    local = local and not private_access_enabled(session)
    attempt_budget(session, purpose="admin", identity="bootstrap")
    user = accounts.bootstrap_admin(
        session, body.username, body.password.get_secret_value(), local_setup=local
    )
    grant = accounts.login(session, user.username, body.password.get_secret_value(), label="Initial setup")
    session.commit()
    attach_cookie(
        response, grant.token, grant.max_age, secure=secure_cookie(request.headers.get("host", ""), session)
    )
    return _status(session, grant.principal)


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, session: DB):
    try:
        identity = username_identity(body.username)[1]
    except ValueError:
        identity = "invalid-username"
    attempt_budget(session, purpose="login", identity=identity)
    grant = accounts.login(
        session,
        body.username,
        body.password.get_secret_value(),
        second_factor=body.second_factor.get_secret_value() if body.second_factor else None,
        label=request.headers.get("user-agent", "")[:160],
    )
    # Issuing the new device can evict the previous one at the device limit.
    # An already expired/revoked old device must not roll back a valid login.
    previous = accounts.authenticate_cookies(session, dict(request.cookies))
    if previous is not None:
        accounts.logout(session, previous)
    session.commit()
    attach_cookie(
        response, grant.token, grant.max_age, secure=secure_cookie(request.headers.get("host", ""), session)
    )
    return _status(session, grant.principal)


@router.post("/auth/logout")
def logout(request: Request, response: Response, session: DB):
    actor = getattr(request.state, "account_principal", None)
    if actor is not None:
        accounts.logout(session, actor)
        session.commit()
    clear_cookies(response)
    return {"authenticated": False}


@router.post("/account/password")
def password(body: ChangePassword, actor: Actor, response: Response, session: DB):
    attempt_budget(session, purpose="security", identity=actor.user_id)
    accounts.change_password(
        session, actor, body.password.get_secret_value(), body.new_password.get_secret_value()
    )
    session.commit()
    clear_cookies(response)
    return {"authenticated": False}


@router.get("/account/devices")
def devices(actor: Actor, session: DB):
    return accounts.list_devices(session, actor)


@router.delete("/account/devices/{session_id}")
def revoke(session_id: UUID, actor: Actor, response: Response, session: DB):
    accounts.revoke_device(session, actor, str(session_id))
    session.commit()
    if str(session_id) == actor.session_id:
        clear_cookies(response)
    return {"revoked": True}


@router.get("/admin/users")
def users(actor: Actor, session: DB):
    accounts._actor(session, actor, admin=True)
    return [
        accounts.public_user(user)
        for user in session.scalars(select(User).order_by(User.created_at, User.id))
    ]


@router.post("/admin/users", status_code=201)
def create(body: CreateUser, actor: Actor, session: DB):
    accounts._actor(session, actor, admin=True)
    attempt_budget(session, purpose="admin", identity=actor.user_id)
    user = accounts.create_user(
        session, actor, body.username, body.password.get_secret_value(), is_admin=body.is_admin
    )
    session.commit()
    return accounts.public_user(user)


@router.patch("/admin/users/{user_id}")
def update(user_id: UUID, body: UserPolicy, actor: Actor, session: DB):
    user = accounts.update_user(session, actor, str(user_id), enabled=body.enabled, is_admin=body.is_admin)
    session.commit()
    return accounts.public_user(user)


@router.delete("/admin/users/{user_id}")
def remove(user_id: UUID, actor: Actor, session: DB):
    user = accounts.update_user(session, actor, str(user_id), enabled=False, is_admin=False)
    session.commit()
    return accounts.public_user(user)


@router.post("/admin/users/{user_id}/credentials")
def reset_credentials(user_id: UUID, body: ResetCredentials, actor: Actor, response: Response, session: DB):
    accounts._actor(session, actor, admin=True)
    attempt_budget(session, purpose="admin", identity=actor.user_id)
    user = accounts.reset_user_credentials(
        session,
        actor,
        str(user_id),
        admin_password=body.password.get_secret_value(),
        new_password=body.new_password.get_secret_value(),
        reset_mfa=body.reset_mfa,
        second_factor=body.second_factor.get_secret_value() if body.second_factor else None,
    )
    session.commit()
    if str(user_id) == actor.user_id:
        clear_cookies(response)
    return accounts.public_user(user)


@router.post("/account/mfa/enroll")
def enroll(body: Reauthenticate, actor: Actor, response: Response, session: DB):
    attempt_budget(session, purpose="security", identity=actor.user_id)
    enrollment = account_mfa.begin_enrollment(session, actor, body.password.get_secret_value())
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "secret": enrollment.secret,
        "provisioning_uri": enrollment.provisioning_uri,
        "expires_at": enrollment.expires_at,
    }


@router.post("/account/mfa/confirm")
def confirm(body: VerifyFactor, actor: Actor, response: Response, session: DB):
    attempt_budget(session, purpose="security", identity=actor.user_id)
    codes = account_mfa.confirm_enrollment(
        session, actor, body.password.get_secret_value(), body.code.get_secret_value()
    )
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"recovery_codes": codes}


@router.post("/account/mfa/recovery-codes")
def recovery(body: VerifyFactor, actor: Actor, response: Response, session: DB):
    attempt_budget(session, purpose="security", identity=actor.user_id)
    codes = account_mfa.regenerate_recovery_codes(
        session, actor, body.password.get_secret_value(), body.code.get_secret_value()
    )
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"recovery_codes": codes}


@router.post("/account/mfa/disable")
def disable(body: VerifyFactor, actor: Actor, response: Response, session: DB):
    attempt_budget(session, purpose="security", identity=actor.user_id)
    account_mfa.disable_mfa(session, actor, body.password.get_secret_value(), body.code.get_secret_value())
    session.commit()
    clear_cookies(response)
    return {"authenticated": False}
