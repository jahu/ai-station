"""Operator credentials and revocable sessions for explicit private UI access."""

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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory, session_scope, utcnow
from app.models import Setting
from app.private_access import access_origins, private_access_enabled, secure_cookie

router = APIRouter(prefix="/api/operator-auth", tags=["operator"])
DB = Annotated[Session, Depends(session_scope)]
SETUP_KEY = "operator_auth"
SESSION_KEY = "operator_session"
COOKIE = "ais_operator"
ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 12
SESSION_HOURS = 12
SESSION_IDLE_MINUTES = 30
SESSION_IDLE_SECONDS = SESSION_IDLE_MINUTES * 60
SESSION_ABSOLUTE_SECONDS = SESSION_HOURS * 3600
LAST_SEEN_MIN_WRITE_SECONDS = 60
COOKIE_POLICY = {
    "httponly": True,
    "samesite": "strict",
    "secure": False,
    "path": "/",
}
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
    if private_access_enabled() and not auth:
        raise RuntimeError(
            "Private network access requires an operator password; configure it on localhost first"
        )
    return decision


def session_key(session: Session, token: str | None = None) -> str:
    if not token:
        return SESSION_KEY
    row = session.get(Setting, SESSION_KEY)
    legacy = dict(row.value) if row and isinstance(row.value, dict) else {}
    if session_verdict(legacy, token) in {"valid", "idle", "expired"}:
        return SESSION_KEY
    return SESSION_KEY + ":" + hashlib.sha256(token.encode()).hexdigest()


def stored_session(session: Session, token: str | None = None) -> dict:
    row = session.get(Setting, session_key(session, token))
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    return value if value.get("token_hash") and value.get("salt") else {}


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def idle_seconds(value: dict) -> int:
    try:
        seconds = int(value.get("idle_timeout_seconds") or SESSION_IDLE_SECONDS)
    except (TypeError, ValueError):
        return SESSION_IDLE_SECONDS
    return SESSION_IDLE_SECONDS if seconds <= 0 else seconds


def idle_deadline(value: dict) -> datetime | None:
    last_seen = parse_time(value.get("last_seen_at")) or parse_time(value.get("issued_at"))
    return None if last_seen is None else last_seen + timedelta(seconds=idle_seconds(value))


def cookie_max_age(value: dict, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    remaining = idle_seconds(value)
    expires = parse_time(value.get("expires_at"))
    if expires is not None:
        remaining = min(remaining, int((expires - now).total_seconds()))
    idle_at = idle_deadline(value)
    if idle_at is not None:
        remaining = min(remaining, int((idle_at - now).total_seconds()))
    return max(0, remaining)


def attach_session_cookie(response: Response, token: str, *, max_age: int, secure: bool = False) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=COOKIE_POLICY["httponly"],
        samesite=COOKIE_POLICY["samesite"],
        secure=secure,
        path=COOKIE_POLICY["path"],
        max_age=max_age,
    )


def clear_session_row(session: Session, token: str | None = None) -> None:
    row = session.get(Setting, session_key(session, token))
    if row is not None:
        session.delete(row)


def session_verdict(value: dict, token: str | None, *, now: datetime | None = None) -> str:
    now = now or utcnow()
    if not token or not value:
        return "missing"
    try:
        salt = bytes.fromhex(value.get("salt") or "")
        expected = value.get("token_hash") or ""
    except (TypeError, ValueError):
        return "mismatch"
    if not salt or not expected:
        return "mismatch"
    actual = hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, actual):
        return "mismatch"
    expires = parse_time(value.get("expires_at"))
    if expires is None or now >= expires:
        return "expired"
    last_seen = parse_time(value.get("last_seen_at")) or parse_time(value.get("issued_at"))
    if last_seen is None:
        return "valid"
    if now >= last_seen + timedelta(seconds=idle_seconds(value)):
        return "idle"
    return "valid"


def session_valid(session: Session, token: str | None) -> bool:
    return session_verdict(stored_session(session, token), token) == "valid"


def persist_session(session: Session, payload: dict, key: str = SESSION_KEY) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=payload))
    else:
        row.value = payload


def touch_session(session: Session, token: str | None = None, *, now: datetime | None = None) -> dict | None:
    now = now or utcnow()
    row = session.get(Setting, session_key(session, token))
    if row is None or not isinstance(row.value, dict):
        return None
    value = dict(row.value)
    last_seen = parse_time(value.get("last_seen_at"))
    if last_seen is not None and (now - last_seen).total_seconds() < LAST_SEEN_MIN_WRITE_SECONDS:
        return None
    value["last_seen_at"] = now.isoformat()
    if not parse_time(value.get("issued_at")):
        value["issued_at"] = now.isoformat()
    if not value.get("idle_timeout_seconds"):
        value["idle_timeout_seconds"] = SESSION_IDLE_SECONDS
    row.value = value
    return value


def clear_all_sessions(session: Session) -> None:
    for row in session.scalars(
        select(Setting).where((Setting.key == SESSION_KEY) | Setting.key.startswith(SESSION_KEY + ":"))
    ):
        session.delete(row)
    session.flush()


def issue_session(session: Session, response: Response, request: Request) -> str:
    token = secrets.token_hex(32)
    salt = os.urandom(16)
    now = utcnow()
    payload = {
        "token_hash": hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest(),
        "salt": salt.hex(),
        "issued_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=SESSION_HOURS)).isoformat(),
        "idle_timeout_seconds": SESSION_IDLE_SECONDS,
    }
    rows = list(
        session.scalars(
            select(Setting).where((Setting.key == SESSION_KEY) | Setting.key.startswith(SESSION_KEY + ":"))
        )
    )
    active = []
    for row in rows:
        expires = parse_time(row.value.get("expires_at"))
        idle = idle_deadline(row.value)
        if expires is None or now >= expires or (idle is not None and now >= idle):
            session.delete(row)
        else:
            active.append(row)
    session.flush()
    if len(active) >= 10:
        session.delete(min(active, key=lambda row: row.value.get("issued_at", "")))
        session.flush()
    key = (
        SESSION_KEY
        if session.get(Setting, SESSION_KEY) is None
        else SESSION_KEY + ":" + hashlib.sha256(token.encode()).hexdigest()
    )
    persist_session(session, payload, key)
    attach_session_cookie(
        response,
        token,
        max_age=cookie_max_age(payload, now=now),
        secure=secure_cookie(request.headers.get("host", "")),
    )
    return token


def drop_session(session: Session, response: Response, token: str | None = None) -> None:
    if token:
        clear_session_row(session, token)
    response.delete_cookie(COOKIE, path=COOKIE_POLICY["path"])


def unauthorized() -> JSONResponse:
    response = JSONResponse({"detail": "Operator login required"}, status_code=401)
    response.delete_cookie(COOKIE, path=COOKIE_POLICY["path"])
    return response


def public_status(session: Session, token: str | None = None, *, authority: str = "") -> dict:
    settings = get_settings()
    auth = configured(session)
    decision = lan_bind_decision(settings.bind_host, auth_configured=auth)
    origins = sorted(access_origins())
    private = bool(origins)
    if private:
        decision.update(
            lan_exposure="private" if auth else "forbidden",
            reason=(
                "Private network access requires the operator password. Host Runner stays on its private socket."
            ),
        )
    value = stored_session(session, token)
    verdict = session_verdict(value, token) if auth else "missing"
    if verdict in {"expired", "idle"}:
        clear_session_row(session, token)
        value = {}
        verdict = "missing"
    authenticated = verdict == "valid"
    idle_at = idle_deadline(value) if authenticated else None
    return {
        "configured": auth,
        "session_required": auth,
        "authenticated": authenticated,
        "session_scope": "private-network" if private else "loopback",
        "session_idle_seconds": SESSION_IDLE_SECONDS,
        "session_max_age_seconds": SESSION_ABSOLUTE_SECONDS,
        "session_cookie": {**COOKIE_POLICY, "secure": secure_cookie(authority)},
        "issued_at": value.get("issued_at") if authenticated else None,
        "last_seen_at": value.get("last_seen_at") if authenticated else None,
        "expires_at": value.get("expires_at") if authenticated else None,
        "idle_expires_at": idle_at.isoformat() if idle_at is not None else None,
        "bind_host": settings.bind_host,
        "lan_exposure": decision["lan_exposure"],
        "lan_bind_allowed": bool(settings.lan_host and auth),
        "access_urls": origins,
        "password_removal_allowed": not private,
        "reason": decision["reason"],
    }


def remember_activity(request: Request, session: Session, token: str) -> None:
    updated = touch_session(session, token)
    payload = updated or stored_session(session, token)
    if updated is None:
        return
    request.state.operator_cookie_refresh = {
        "token": token,
        "max_age": cookie_max_age(payload),
    }


def refresh_operator_cookie(request: Request, response: Response) -> None:
    # Login, logout and rotation own their cookie; activity must not restore
    # the previous token after those handlers have replaced or removed it.
    if any(value.startswith(COOKIE + "=") for value in response.headers.getlist("set-cookie")):
        return
    refresh = getattr(request.state, "operator_cookie_refresh", None)
    if not isinstance(refresh, dict):
        return
    token = refresh.get("token")
    max_age = refresh.get("max_age")
    if isinstance(token, str) and isinstance(max_age, int) and max_age > 0:
        attach_session_cookie(
            response, token, max_age=max_age, secure=secure_cookie(request.headers.get("host", ""))
        )


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
            if private_access_enabled():
                return unauthorized()
            return None
        token = request.cookies.get(COOKIE)
        verdict = session_verdict(stored_session(db, token), token)
        if verdict == "valid" and token:
            remember_activity(request, db, token)
            db.commit()
            return None
        if verdict in {"expired", "idle"}:
            clear_session_row(db, token)
            db.commit()
            return unauthorized()
    finally:
        db.close()
    return unauthorized()


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
def status(request: Request, response: Response, session: DB):
    token = request.cookies.get(COOKIE)
    body = public_status(session, token, authority=request.headers.get("host", ""))
    if token and not body["authenticated"]:
        response.delete_cookie(COOKIE, path=COOKIE_POLICY["path"])
    if session.deleted:
        session.commit()
    return body


@router.put("")
def set_password(body: PasswordBody, request: Request, response: Response, session: DB):
    password = body.password.get_secret_value()
    if configured(session):
        current = body.current_password.get_secret_value() if body.current_password else ""
        if not verify_password(session, current):
            raise HTTPException(403, "Current operator password is required")
    save_secret(session, password)
    clear_all_sessions(session)
    token = issue_session(session, response, request)
    session.commit()
    return public_status(session, token, authority=request.headers.get("host", ""))


@router.post("/clear")
def clear_password(body: ClearBody, response: Response, session: DB):
    if private_access_enabled():
        raise HTTPException(409, "Disable private network access before removing the operator password")
    if not configured(session):
        drop_session(session, response)
        session.commit()
        return public_status(session)
    if not verify_password(session, body.current_password.get_secret_value()):
        raise HTTPException(403, "Current operator password is required")
    row = session.get(Setting, SETUP_KEY)
    if row is not None:
        session.delete(row)
    clear_all_sessions(session)
    drop_session(session, response)
    session.commit()
    return public_status(session)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, session: DB):
    # A durable, global budget cannot be bypassed with spoofed proxy/IP headers.
    key = "operator_login_budget"
    row = session.get(Setting, key)
    now = utcnow()
    value = dict(row.value) if row else {}
    start = parse_time(value.get("start"))
    if start is None or (now - start).total_seconds() >= 60:
        value = {"start": now.isoformat(), "attempts": 0}
    if value.get("attempts", 0) >= 10:
        raise HTTPException(
            429, "Too many login attempts. Try again in one minute.", headers={"Retry-After": "60"}
        )
    value["attempts"] += 1
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()
    if not verify_password(session, body.password.get_secret_value()):
        raise HTTPException(403, "Operator password is incorrect")
    token = issue_session(session, response, request)
    session.commit()
    return public_status(session, token, authority=request.headers.get("host", ""))


@router.post("/logout")
def logout(request: Request, response: Response, session: DB):
    drop_session(session, response, request.cookies.get(COOKIE))
    session.commit()
    return public_status(session, authority=request.headers.get("host", ""))
