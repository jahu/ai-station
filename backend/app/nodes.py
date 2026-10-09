"""Authenticated node invitations on loopback. LAN transport stays unpublished."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope, utcnow
from app.models import StationNode
from app.operator_auth import configured, public_status

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
DB = Annotated[Session, Depends(session_scope)]
LOCAL_NODE = {
    "id": "local",
    "name": "This workstation",
    "kind": "host-runner",
    "transport": "unix-socket",
    "ownership": "local",
    "status": "registered",
    "authenticated": True,
    "token_issued": False,
    "created_at": None,
    "registered_at": None,
    "revoked_at": None,
}


class InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=16, max_length=200)
    name: str | None = Field(default=None, max_length=200)


def digest(token: str, salt: bytes) -> str:
    return hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest()


def public_node(row: StationNode) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "transport": row.transport,
        "ownership": row.ownership,
        "status": row.status,
        "authenticated": row.status == "registered",
        "token_issued": bool(row.token_hash) and row.status == "pending",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "registered_at": row.registered_at.isoformat() if row.registered_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def inventory(session: Session) -> dict:
    status = public_status(session)
    remotes = session.scalars(select(StationNode).order_by(StationNode.created_at.asc())).all()
    return {
        "items": [LOCAL_NODE, *[public_node(row) for row in remotes]],
        "remote_registration": "loopback-token",
        "lan_exposure": status["lan_exposure"],
        "lan_bind_allowed": False,
        "summary": (
            "The local Host Runner is registered over its Unix socket. Remote invitations use a "
            "one-time token accepted only on this loopback API. Authenticated LAN/node transport "
            "is unpublished, so a registered remote still has no network path."
        ),
    }


def match_pending(session: Session, token: str) -> StationNode | None:
    for row in session.scalars(select(StationNode).where(StationNode.status == "pending")):
        try:
            salt = bytes.fromhex(row.token_salt)
        except ValueError:
            continue
        if row.token_hash and hmac.compare_digest(row.token_hash, digest(token, salt)):
            return row
    return None


@router.get("")
def list_nodes(session: DB):
    return inventory(session)


@router.post("/invitations")
def invite(body: InviteBody, session: DB):
    if not configured(session):
        raise HTTPException(403, "Store an operator password before issuing node invitations")
    token = "aisn_" + secrets.token_urlsafe(32)
    salt = os.urandom(16)
    row = StationNode(
        name=body.name.strip(),
        kind="host-runner",
        ownership="remote",
        transport="unpublished",
        status="pending",
        token_hash=digest(token, salt),
        token_salt=salt.hex(),
    )
    if not row.name:
        raise HTTPException(422, "Node name is required")
    session.add(row)
    session.commit()
    session.refresh(row)
    return {**public_node(row), "token": token, "token_once": True}


@router.post("/register")
def register(body: RegisterBody, session: DB):
    token = body.token.get_secret_value().strip()
    row = match_pending(session, token)
    if row is None:
        raise HTTPException(403, "Invitation token is invalid or already used")
    if body.name and body.name.strip():
        row.name = body.name.strip()
    row.status = "registered"
    row.registered_at = utcnow()
    row.token_hash = ""
    row.token_salt = ""
    session.commit()
    session.refresh(row)
    return public_node(row)


@router.post("/{node_id}/revoke")
def revoke(node_id: str, session: DB):
    if node_id == "local":
        raise HTTPException(403, "The local Host Runner cannot be revoked")
    if not configured(session):
        raise HTTPException(403, "Store an operator password before revoking nodes")
    row = session.get(StationNode, node_id)
    if row is None:
        raise HTTPException(404, "Node not found")
    if row.status == "revoked":
        return public_node(row)
    row.status = "revoked"
    row.revoked_at = utcnow()
    row.token_hash = ""
    row.token_salt = ""
    session.commit()
    session.refresh(row)
    return public_node(row)
