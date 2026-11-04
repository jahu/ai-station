"""One-time refresh of an identity staged before operator access was retired."""

import re

from sqlalchemy import or_, select

from app.account_credentials import password_record_valid
from app.db import utcnow
from app.models import Setting, UserSession
from app.operator_auth import SESSION_KEY, SETUP_KEY, parse_time

FIELDS = ("token_hash", "salt", "issued_at", "last_seen_at", "expires_at", "idle_timeout_seconds")


def refresh(session, users):
    source = session.get(Setting, SETUP_KEY)
    candidates = [user for user in users if user.legacy_operator]
    if not candidates and len(users) == 1 and users[0].bootstrap_pending and source is not None:
        candidates = users
    if len(candidates) > 1:
        raise RuntimeError("Legacy account identities require inspection before activation")
    if not candidates:
        return None
    user = candidates[0]
    raw = source.value if source is not None and isinstance(source.value, dict) else {}
    credential = {key: raw[key] for key in ("algorithm", "salt", "hash", "iterations") if key in raw}
    valid = password_record_valid(credential)
    changed = user.password_record != credential
    sessions = list(session.scalars(select(UserSession).where(UserSession.user_id == user.id)))
    now = utcnow()
    if changed or not valid:
        for row in sessions:
            row.revoked_at = row.revoked_at or now
    pending = user.bootstrap_pending
    user.password_record = credential if valid else {}
    user.legacy_operator = True
    user.bootstrap_pending = False
    # Preserve administrative disable/demotion decisions. Only a pending
    # identity can become enabled by importing its newly configured password.
    user.enabled = valid and (user.enabled or pending)
    if not valid:
        return {"status": "quarantined", "credential_changed": changed, "sessions_added": 0}
    source_sessions = {}
    for row in session.scalars(
        select(Setting).where(
            or_(Setting.key == SESSION_KEY, Setting.key.startswith(SESSION_KEY + ":", autoescape=True))
        )
    ):
        value = row.value
        digest = row.key.partition(":")[2] if row.key != SESSION_KEY else None
        if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            continue
        if (
            not isinstance(value, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("token_hash", "")))
            or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("salt", "")))
        ):
            continue
        if any(parse_time(value.get(key)) is None for key in ("issued_at", "last_seen_at", "expires_at")):
            continue
        source_sessions[row.key] = (digest, {key: value[key] for key in FIELDS if key in value})
    existing = {row.legacy_operator_key: row for row in sessions if row.legacy_operator_key}
    for key, row in existing.items():
        if key not in source_sessions:
            row.revoked_at = row.revoked_at or now
    added = 0
    for key, (digest, record) in source_sessions.items():
        row = existing.get(key)
        same = row is not None and all(
            row.token_record.get(field) == record.get(field) for field in ("token_hash", "salt", "issued_at")
        )
        if same:
            # Never reactivate a device revoked through the account API.
            if row.revoked_at is None:
                old_seen = parse_time(row.token_record.get("last_seen_at"))
                new_seen = parse_time(record.get("last_seen_at"))
                if old_seen and new_seen and old_seen > new_seen:
                    record["last_seen_at"] = row.token_record["last_seen_at"]
                row.token_record = record
            continue
        if row is not None:
            row.revoked_at = row.revoked_at or now
            row.legacy_operator_key = None
            row.lookup_hash = None
            session.flush()  # Free unique indexes before inserting a replacement.
        session.add(
            UserSession(
                user_id=user.id,
                lookup_hash=digest,
                token_record=record,
                legacy_operator_key=key,
                label="Migrated operator session",
            )
        )
        added += 1
    return {"status": "refreshed", "credential_changed": changed, "sessions_added": added}
