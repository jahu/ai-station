"""Local operator credential and loopback session. Non-loopback bind stays unpublished."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory, session_scope, utcnow
from app.models import Setting

router = APIRouter(prefix="/api/operator-auth", tags=["operator"])
DB = Annotated[Session, Depends(session_scope)]
SETUP_KEY = "operator_auth"
SESSION_KEY = "operator_session"
COOKIE = "ais_operator"
ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 12
SESSION_HOURS = 12
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
PUBLIC_GET = {"/api/health", "/api/operator-auth"}
PUBLIC_POST = {"/api/operator-auth/login", "/api/operator-auth/logout"}


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=MIN_PASSWORD, max_length=200)
    current_password: SecretStr | None = None


class ClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=200)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=200)


def loopback_host(host: str | None) -> bool:
    return (host or "127.0.0.1").strip().lower() in LOOPBACK


def digest(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def stored_secret(session: Session) -> dict:
    row = session.get(Setting, SETUP_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    return value if value.get("algorithm") == ALGORITHM and value.get("hash") and value.get("salt") else {}


def configured(session: Session) -> bool:
    return bool(stored_secret(session))


def verify_password(session: Session, password: str) -> bool:
    record = stored_secret(session)
    if not record:
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        iterations = int(record.get("iterations") or ITERATIONS)
    except (TypeError, ValueError):
        return False
    expected = record["hash"]
    actual = digest(password, salt, iterations)
    return hmac.compare_digest(expected, actual)


def lan_bind_decision(bind_host: str, *, auth_configured: bool) -> dict:
    if loopback_host(bind_host):
        return {
            "allowed": True,
            "bind_host": bind_host,
            "lan_exposure": "disabled",
            "reason": "The UI/API stays on loopback. LAN publish is not enabled.",
        }
    if not auth_configured:
        return {
            "allowed": False,
            "bind_host": bind_host,
            "lan_exposure": "forbidden",
            "reason": "Non-loopback bind requires operator authentication first; LAN exposure is unpublished.",
        }
    return {
        "allowed": False,
        "bind_host": bind_host,
        "lan_exposure": "unpublished",
        "reason": (
            "Operator authentication is configured, but authenticated LAN/node transport is not enabled. "
            "Keep the publish address on 127.0.0.1."
        ),
    }


def refuse_non_loopback_bind(session: Session | None = None) -> dict:
    settings = get_settings()
    auth = configured(session) if session is not None else False
    decision = lan_bind_decision(settings.bind_host, auth_configured=auth)
    if not decision["allowed"]:
        raise RuntimeError(decision["reason"])
    return decision


def session_valid(session: Session, token: str | None) -> bool:
    if not token:
        return False
    row = session.get(Setting, SESSION_KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    try:
        salt = bytes.fromhex(value.get("salt") or "")
        expected = value.get("token_hash") or ""
        expires = value.get("expires_at") or ""
    except (TypeError, ValueError):
        return False
    if not salt or not expected or not expires:
        return False
    try:
        deadline = datetime.fromisoformat(expires)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        return False
    if utcnow() >= deadline:
        return False
    actual = hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, actual)


def issue_session(session: Session, response: Response) -> str:
    token = secrets.token_hex(32)
    salt = os.urandom(16)
    expires = utcnow() + timedelta(hours=SESSION_HOURS)
    payload = {
        "token_hash": hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest(),
        "salt": salt.hex(),
        "expires_at": expires.isoformat(),
    }
    row = session.get(Setting, SESSION_KEY)
    if row is None:
        session.add(Setting(key=SESSION_KEY, value=payload))
    else:
        row.value = payload
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_HOURS * 3600,
        path="/",
        secure=False,
    )
    return token


def drop_session(session: Session, response: Response) -> None:
    row = session.get(Setting, SESSION_KEY)
    if row is not None:
        session.delete(row)
    response.delete_cookie(COOKIE, path="/")


def public_status(session: Session, token: str | None = None) -> dict:
    settings = get_settings()
    auth = configured(session)
    decision = lan_bind_decision(settings.bind_host, auth_configured=auth)
    return {
        "configured": auth,
        "session_required": auth,
        "authenticated": session_valid(session, token) if auth else False,
        "session_scope": "loopback",
        "bind_host": settings.bind_host,
        "lan_exposure": decision["lan_exposure"],
        "lan_bind_allowed": False,
        "reason": decision["reason"],
    }


def require_operator_session(request: Request) -> JSONResponse | None:
    path = request.url.path
    if not path.startswith("/api") or request.method == "OPTIONS":
        return None
    normalized = path.rstrip("/") or "/"
    public_get = {item.rstrip("/") for item in PUBLIC_GET}
    public_post = {item.rstrip("/") for item in PUBLIC_POST}
    if request.method in {"GET", "HEAD"} and normalized in public_get:
        return None
    if request.method == "POST" and normalized in public_post:
        return None
    db = session_factory()()
    try:
        if not configured(db):
            return None
        if session_valid(db, request.cookies.get(COOKIE)):
            return None
    finally:
        db.close()
    return JSONResponse({"detail": "Operator login required"}, status_code=401)


def save_secret(session: Session, password: str) -> None:
    salt = os.urandom(16)
    payload = {
        "algorithm": ALGORITHM,
        "iterations": ITERATIONS,
        "salt": salt.hex(),
        "hash": digest(password, salt),
    }
    row = session.get(Setting, SETUP_KEY)
    if row is None:
        session.add(Setting(key=SETUP_KEY, value=payload))
    else:
        row.value = payload


@router.get("")
def status(request: Request, session: DB):
    return public_status(session, request.cookies.get(COOKIE))


@router.put("")
def set_password(body: PasswordBody, response: Response, session: DB):
    password = body.password.get_secret_value()
    if configured(session):
        current = body.current_password.get_secret_value() if body.current_password else ""
        if not verify_password(session, current):
            raise HTTPException(403, "Current operator password is required")
    save_secret(session, password)
    token = issue_session(session, response)
    session.commit()
    return public_status(session, token)


@router.post("/clear")
def clear_password(body: ClearBody, response: Response, session: DB):
    if not configured(session):
        drop_session(session, response)
        session.commit()
        return public_status(session)
    if not verify_password(session, body.current_password.get_secret_value()):
        raise HTTPException(403, "Current operator password is required")
    row = session.get(Setting, SETUP_KEY)
    if row is not None:
        session.delete(row)
    drop_session(session, response)
    session.commit()
    return public_status(session)


@router.post("/login")
def login(body: LoginBody, response: Response, session: DB):
    if not verify_password(session, body.password.get_secret_value()):
        raise HTTPException(403, "Operator password is incorrect")
    token = issue_session(session, response)
    session.commit()
    return public_status(session, token)


@router.post("/logout")
def logout(response: Response, session: DB):
    drop_session(session, response)
    session.commit()
    return public_status(session)
