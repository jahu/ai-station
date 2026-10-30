"""Trusted, atomic lifecycle transition from operator storage to account scopes.

This is not an HTTP operation or a general ownership reassignment service.
The production default stays operator until the complete cutover is qualified.
"""

from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import utcnow
from app.models import AccountEvent, Setting, User

KEY = "auth.account_profile"


def accounts_enabled():
    return get_settings().access_profile == "accounts"


def prepare_profile(session, *, accounts_active: bool | None = None):
    from app.data_access import ROOTS, ScopedSession

    if isinstance(session, ScopedSession):
        raise PermissionError("Access-profile changes require a trusted lifecycle session")
    active = accounts_enabled() if accounts_active is None else accounts_active
    if active != accounts_enabled():
        raise RuntimeError("API and workers must use the same access profile")
    receipt = session.get(Setting, KEY)
    if not active:
        users = session.scalar(select(func.count()).select_from(User))
        if receipt is not None or users > 1:
            raise RuntimeError("Accounts were activated; refusing operator access to private user data")
        return None
    if receipt is not None:
        return dict(receipt.value)
    users = list(session.scalars(select(User).order_by(User.created_at, User.id)))
    from app.legacy_account_refresh import refresh

    identity_refresh = refresh(session, users)
    # This also preserves legacy records written after migration 0038 while the
    # operator profile was still in use. Adopt only an unambiguous sole identity,
    # including its pending first-admin identity. Never guess across users.
    owner = users[0] if len(users) == 1 else None
    adopted = {}
    unassigned = {}
    for model in ROOTS:
        count = session.scalar(select(func.count()).select_from(model).where(model.owner_id.is_(None)))
        if count and owner is not None:
            session.execute(update(model).where(model.owner_id.is_(None)).values(owner_id=owner.id))
        adopted[model.__tablename__] = count if owner is not None else 0
        unassigned[model.__tablename__] = count if owner is None else 0
    if any(unassigned.values()):
        raise RuntimeError("Unassigned legacy records require ownership inspection before account activation")
    value = {
        "version": 1,
        "activated_at": utcnow().isoformat(),
        "legacy_owner_id": owner.id if owner else None,
        "adopted": adopted,
        "unassigned": unassigned,
        "identity_refresh": identity_refresh,
    }
    session.add(Setting(key=KEY, value=value))
    session.add(
        AccountEvent(
            action="access_profile.accounts", subject_user_id=owner.id if owner else None, details=value
        )
    )
    session.flush()
    return value


def waiting_for_first_admin(session):
    return (
        accounts_enabled()
        and session.scalar(select(User.id).where(User.bootstrap_pending.is_(True))) is not None
    )
