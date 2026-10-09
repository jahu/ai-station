"""Local operator credential. Required before any non-loopback bind, which stays unpublished."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import Setting

router = APIRouter(prefix="/api/operator-auth", tags=["operator"])
DB = Annotated[Session, Depends(session_scope)]
SETUP_KEY = "operator_auth"
ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 12
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=MIN_PASSWORD, max_length=200)
    current_password: SecretStr | None = None


class ClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=200)


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


def public_status(session: Session) -> dict:
    settings = get_settings()
    auth = configured(session)
    decision = lan_bind_decision(settings.bind_host, auth_configured=auth)
    return {
        "configured": auth,
        "bind_host": settings.bind_host,
        "lan_exposure": decision["lan_exposure"],
        "lan_bind_allowed": False,
        "reason": decision["reason"],
    }


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
def status(session: DB):
    return public_status(session)


@router.put("")
def set_password(body: PasswordBody, session: DB):
    password = body.password.get_secret_value()
    if configured(session):
        current = body.current_password.get_secret_value() if body.current_password else ""
        if not verify_password(session, current):
            raise HTTPException(403, "Current operator password is required")
    save_secret(session, password)
    session.commit()
    return public_status(session)


@router.post("/clear")
def clear_password(body: ClearBody, session: DB):
    if not configured(session):
        return public_status(session)
    if not verify_password(session, body.current_password.get_secret_value()):
        raise HTTPException(403, "Current operator password is required")
    row = session.get(Setting, SETUP_KEY)
    if row is not None:
        session.delete(row)
    session.commit()
    return public_status(session)
