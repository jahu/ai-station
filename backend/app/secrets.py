"""Secret references for connectors and chat providers. Values never enter the database."""

from __future__ import annotations

import os
import re

from app.config import get_settings
from app.paths import PathBoundaryError, safe_join, validate_relative
from app.providers import ProviderError

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def parse_secret_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("sk-") or "://" in ref:
        raise ValueError("Store a secret reference, not a credential value")
    if ref.startswith("env:"):
        name = ref[4:]
        if not _ENV_NAME.fullmatch(name):
            raise ValueError("Environment secret references must look like env:NAME")
        return ref
    if ref.startswith("file:"):
        relative = validate_relative(ref[5:])
        if not relative.startswith("secrets/"):
            raise PathBoundaryError("File secret references must stay under secrets/")
        return f"file:{relative}"
    raise ValueError("Use env:NAME or a stored secret; plaintext keys are not accepted")


def secret_file_ref(owner_id: str) -> str:
    return f"file:{validate_relative('secrets/' + owner_id)}"


def record_secret_key(record) -> str:
    """Stable account/record namespace; retain old single-operator storage paths."""
    if not record.id:
        raise ValueError("Persist the credential owner before storing a secret")
    owner = getattr(record, "owner_id", None)
    if not owner:
        return record.id
    return validate_relative(f"accounts/{owner}/{record.__tablename__}-{record.id}")


def validate_record_secret_ref(record, ref: str) -> str:
    """Ordinary accounts cannot borrow host environment or another record's secret."""
    from sqlalchemy.orm import object_session

    from app.data_access import ScopedSession
    from app.models import ChatProvider, User

    ref = parse_secret_ref(ref)
    session = object_session(record)
    if not ref or not isinstance(session, ScopedSession):
        return ref
    expected = secret_file_ref(record_secret_key(record)) if record.id else None
    if expected and ref == expected:
        return ref
    # A migrated record can retain its own previous private file, not substitute
    # any other legacy file by guessing a UUID.
    if record.id and ref == record.secret_ref == secret_file_ref(record.id):
        return ref
    if ref.startswith("env:"):
        owner = session.get(User, record.owner_id)
        if owner is not None and owner.is_admin and owner.id == session.scope.user_id:
            return ref
        if isinstance(record, ChatProvider) and record.builtin:
            from app.chat_providers import BUILTIN_KEY, local_endpoint

            configured = "env:AI_STATION_LLM_API_KEY" if get_settings().llm_api_key else ""
            if ref == configured and record.key == BUILTIN_KEY and record.endpoint == local_endpoint():
                return ref
    raise ValueError("Supply your own credential; this secret reference is unavailable")


def store_secret_file(owner_id: str, value: str) -> str:
    if not value or not value.strip():
        raise ValueError("A stored secret cannot be empty")
    if "\x00" in value:
        raise ValueError("A stored secret cannot contain a null byte")
    ref = secret_file_ref(owner_id)
    path = safe_join(get_settings().data_dir, ref[5:])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return ref


def clear_secret_file(ref: str) -> None:
    if not ref.startswith("file:"):
        return
    path = safe_join(get_settings().data_dir, ref[5:])
    path.unlink(missing_ok=True)


def resolve_secret(ref: str) -> str:
    ref = parse_secret_ref(ref)
    if not ref:
        return ""
    if ref.startswith("env:"):
        value = os.environ.get(ref[4:], "")
        if not value:
            raise ProviderError("The configured provider secret is missing")
        return value
    relative = ref[5:]
    raw = get_settings().data_dir.joinpath(relative)
    if raw.is_symlink():
        raise ProviderError("The configured provider secret is missing")
    path = safe_join(get_settings().data_dir, relative)
    if not path.is_file():
        raise ProviderError("The configured provider secret is missing")
    value = path.read_text(encoding="utf-8")
    if not value:
        raise ProviderError("The configured provider secret is missing")
    return value


def secret_present(ref: str) -> bool:
    if not ref:
        return False
    try:
        return bool(resolve_secret(ref))
    except (ProviderError, ValueError, PathBoundaryError, OSError):
        return False


def public_secret(ref: str) -> dict:
    source = "none"
    displayed = ""
    if ref.startswith("env:"):
        source = "env"
        displayed = ref
    elif ref.startswith("file:"):
        source = "stored"
    return {
        "secret_ref": displayed,
        "secret_source": source,
        "secret_present": secret_present(ref),
    }


def authorization_headers(ref: str, *, required: bool) -> dict[str, str]:
    if not ref:
        if required:
            raise ProviderError("The configured provider secret is missing")
        return {}
    return {"Authorization": f"Bearer {resolve_secret(ref)}"}
