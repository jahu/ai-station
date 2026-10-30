"""Preserve current private-account authority while restoring older user data.

These functions run only against stopped-service recovery staging, never through
HTTP. Credential snapshots stay in memory and are never included in receipts.
"""

from datetime import datetime

JSON_FIELDS = {"password_record", "recovery_code_hashes"}
TIME_FIELDS = {"created_at", "updated_at", "password_changed_at", "totp_enabled_at"}


def current_authority(connection):
    import json

    from app.models import User

    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
        return None
    # Fixed schema identifiers, never supplied by the operator or a backup.
    fields = tuple(User.__table__.columns.keys())
    columns = ",".join(f'"{key}"' for key in fields)
    rows = [dict(zip(fields, row, strict=True)) for row in connection.execute(f"SELECT {columns} FROM users")]
    if not any(not row["bootstrap_pending"] for row in rows):
        return None
    for row in rows:
        for key in JSON_FIELDS:
            row[key] = json.loads(row[key])
        for key in TIME_FIELDS:
            if row[key] is not None:
                row[key] = datetime.fromisoformat(row[key])
    return rows


def preserve_authority(session, authority, now, *, password=None, legacy_owner=None):
    from app.models import AccountEvent, User, UserSession, UserSetting
    from sqlalchemy import select, update

    from station_recovery.storage import RecoveryError

    restored = list(session.scalars(select(User)))
    if authority is None:
        if legacy_owner is not None:
            raise RecoveryError("Legacy ownership mapping requires readable current accounts")
        # Unclaimed bootstrap fixtures retain operator recovery. Any claimed
        # account, including a migrated operator, requires current authority;
        # unreadability must never revive historical passwords or MFA state.
        if any(not row.bootstrap_pending for row in restored):
            raise RecoveryError(
                "Current private account authority is unavailable; recover administrator access before restoring account data"
            )
        return {}
    if password is not None:
        raise RecoveryError(
            "Operator password replacement cannot reset private accounts; use named administrator recovery"
        )
    if not any(row["enabled"] and row["is_admin"] and not row["bootstrap_pending"] for row in authority):
        raise RecoveryError("Current private account authority has no enabled administrator")
    identities = {row["id"] for row in authority}
    names = {row["normalized_username"]: row["id"] for row in authority}
    if len(identities) != len(authority) or len(names) != len(authority):
        raise RecoveryError("Current private account identity is ambiguous")
    mapping = {}
    if legacy_owner is not None:
        from app.account_credentials import username_identity
        from app.data_access import ROOTS

        try:
            selected = names[username_identity(legacy_owner)[1]]
        except (KeyError, ValueError) as exc:
            raise RecoveryError("Choose an existing current account for legacy ownership") from exc
        if len(restored) != 1:
            raise RecoveryError("Legacy owner mapping requires one unambiguous initial identity")
        initial = restored[0]
        if (
            not (initial.bootstrap_pending or initial.legacy_operator)
            or initial.totp_enabled_at is not None
            or initial.totp_secret_ref
            or initial.recovery_code_hashes
            or initial.id in identities
            and initial.id != selected
        ):
            raise RecoveryError("Only an unclaimed or pre-account legacy identity can be mapped")
        # Bootstrap can rename `admin` to the owner's chosen username while
        # retaining its UUID. Free the old name before restoring current users,
        # including a different account legitimately called `admin` today.
        initial.normalized_username = "recovery-" + initial.id
        session.flush()
        if initial.id != selected:
            original_id = initial.id
            # The staging-only placeholder avoids a username constraint clash
            # with the real account. No claimed current identity is renamed.
            for value in authority:
                session.merge(User(**value))
            session.flush()
            for model in ROOTS:
                foreign = session.scalar(
                    select(model.id)
                    .where(model.owner_id.is_not(None), model.owner_id != original_id)
                    .limit(1)
                )
                if foreign is not None:
                    raise RecoveryError("Legacy data has another owner; review ownership before recovery")
                session.execute(update(model).where(model.owner_id == original_id).values(owner_id=selected))
            for model, field in (
                (UserSetting, "user_id"),
                (UserSession, "user_id"),
                (AccountEvent, "actor_user_id"),
                (AccountEvent, "subject_user_id"),
            ):
                column = getattr(model, field)
                session.execute(update(model).where(column == original_id).values(**{field: selected}))
            session.delete(initial)
            session.flush()
            restored = []
            mapping = {"legacy_owner_mapping": {"previous_owner_id": original_id, "owner_id": selected}}
        else:
            for value in authority:
                session.merge(User(**value))
            session.flush()
    for row in restored:
        if row.normalized_username in names and names[row.normalized_username] != row.id:
            raise RecoveryError(
                "Backup identity differs from current accounts; explicit legacy owner mapping is required"
            )
    # A legacy copy migrates into a new pending owner. Do not guess which live
    # account should inherit all of its private files and history.
    if any(row.bootstrap_pending and row.id not in identities for row in restored):
        raise RecoveryError("Legacy backup needs explicit initial-owner mapping before account recovery")
    for value in authority:
        session.merge(User(**value))
    for row in restored:
        if row.id not in identities:
            # Keep the UUID for old data provenance, but never revive a removed
            # account or its historical password/administrator authority.
            row.enabled, row.is_admin, row.bootstrap_pending = False, False, False
            row.password_record = {}
    revoked = 0
    for device in session.scalars(select(UserSession).where(UserSession.revoked_at.is_(None))):
        device.revoked_at = now
        revoked += 1
    for pending in session.scalars(
        select(UserSetting).where(UserSetting.key.startswith("auth.", autoescape=True))
    ):
        session.delete(pending)
    for user_id in identities:
        session.add(
            AccountEvent(
                action="account.offline_recovery",
                subject_user_id=user_id,
                details={"sessions_revoked": True},
            )
        )
    return {"accounts_preserved": len(identities), "account_sessions_revoked": revoked, **mapping}
