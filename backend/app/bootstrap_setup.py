"""Host-local first-admin proof for a browser crossing Docker's bridge.

The launcher reads this private file through the owned container console. No
HTTP endpoint returns the proof. It authorizes only the pending initial setup.
"""

from __future__ import annotations

import argparse
import hmac
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from app.config import get_settings
from app.models import User
from app.paths import safe_join

RELATIVE_PATH = "secrets/bootstrap/local-setup"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def pending_setup(session) -> bool:
    return session.scalar(select(User.id).where(User.bootstrap_pending.is_(True))) is not None


def _path() -> Path:
    root = get_settings().data_dir
    if (root / RELATIVE_PATH).is_symlink():
        raise ValueError("The local setup proof must be an owned regular file")
    return safe_join(root, RELATIVE_PATH)


def _read() -> str:
    descriptor = os.open(_path(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "r", encoding="ascii") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_size > 128
        ):
            raise ValueError("The local setup proof must remain private to its owner")
        value = source.read(128).strip()
    if not TOKEN.fullmatch(value):
        raise ValueError("The local setup proof is incomplete")
    return value


def ensure_setup_proof(session) -> None:
    """Called under the startup database transaction, before serving requests."""
    if not pending_setup(session):
        return
    try:
        _read()
        return
    except FileNotFoundError:
        pass
    path = _path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".local-setup-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as target:
            target.write(secrets.token_urlsafe(32))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def valid_setup_proof(session, supplied: str | None) -> bool:
    if not supplied or not TOKEN.fullmatch(supplied) or not pending_setup(session):
        return False
    try:
        return hmac.compare_digest(_read(), supplied)
    except (OSError, ValueError):
        return False


def discard_setup_proof() -> None:
    # The committed pending=False identity is the authoritative one-use fence.
    # A cleanup failure cannot reopen setup or invalidate the new login.
    try:
        _path().unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def setup_url(session, base: str) -> str:
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("First setup requires a local browser URL")
    base = base.rstrip("/")
    return base + "/#/?setup_token=" + _read() if pending_setup(session) else base


def main():
    from app.db import control_session_factory

    parser = argparse.ArgumentParser(description="Print the private local first-setup URL")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    with control_session_factory()() as session:
        print(setup_url(session, args.url))


if __name__ == "__main__":
    main()
