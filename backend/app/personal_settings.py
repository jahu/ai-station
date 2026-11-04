"""Known personal preferences, separated from machine configuration and secrets."""

from copy import deepcopy

from sqlalchemy import select

from app.data_access import ScopedSession
from app.models import Setting, UserSetting

KEYS = {
    "conversation_preferences",
    "media_prompt_translation",
    "image_model_defaults",
    "memory_embedding_activity",
}


def preference_row(session, key: str, *, default: dict | None = None, lock: bool = False):
    if key not in KEYS:
        raise ValueError("Unknown personal preference")
    if isinstance(session, ScopedSession):
        owner = session.scope.user_id
        statement = select(UserSetting).where(UserSetting.user_id == owner, UserSetting.key == key)
    else:
        statement = select(Setting).where(Setting.key == key)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None and default is not None:
        row = (
            UserSetting(user_id=owner, key=key, value=deepcopy(default))
            if isinstance(session, ScopedSession)
            else Setting(key=key, value=deepcopy(default))
        )
        session.add(row)
        session.flush()
    return row
