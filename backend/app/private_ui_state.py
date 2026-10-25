"""Non-secret, versioned operator policy; node keys belong only to the Runner."""

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import Setting

KEY = "private_ui_access"
DEFAULT = {"revision": 0, "enabled": False, "password_required": False}


def read(session=None):
    if session is None:
        from app.db import session_factory

        try:
            with session_factory()() as current:
                return read(current)
        except OperationalError:
            return dict(DEFAULT)
    row = session.get(Setting, KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else dict(DEFAULT)


def lock(session):
    row = session.get(Setting, KEY)
    if row is None:
        try:
            with session.begin_nested():
                session.add(Setting(key=KEY, value=dict(DEFAULT)))
                session.flush()
        except IntegrityError:
            pass
    session.execute(update(Setting).where(Setting.key == KEY).values(value=Setting.value))
    row = session.get(Setting, KEY, populate_existing=True)
    return row
