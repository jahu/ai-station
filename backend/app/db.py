"""SQLite engine, WAL, and Alembic migrations."""

from __future__ import annotations

import fcntl
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class UTCDateTime(TypeDecorator):
    """Store naive UTC, return timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        url = settings.sqlite_url()
        if url.startswith("sqlite:///"):
            path = Path(url.removeprefix("sqlite:///"))
            if path.parent and str(path.parent) not in ("", "."):
                path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        kwargs = {"connect_args": connect_args, "pool_pre_ping": True}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(_engine, "connect", _apply_sqlite_pragmas)
            # sqlite3's legacy transaction mode otherwise leaves SELECT outside
            # the transaction. A short, explicit transaction serializes claims,
            # event sequencing, resource reservations, and scheduler ticks.
            event.listen(_engine, "connect", _disable_legacy_transactions)
            event.listen(_engine, "begin", _begin_immediate)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def _disable_legacy_transactions(connection, _record) -> None:
    connection.isolation_level = None


def _begin_immediate(connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def sqlite_busy(error) -> bool:
    """Only SQLite busy/locked errors are transient; preserve other failures."""
    from sqlalchemy.exc import OperationalError

    if not isinstance(error, OperationalError) or not isinstance(error.orig, sqlite3.OperationalError):
        return False
    code = getattr(error.orig, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 255) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def control_session_factory() -> sessionmaker[Session]:
    """Trusted authentication/configuration/queue coordination, never user data lookup."""
    get_engine()
    assert _session_factory is not None
    return _session_factory


def _context_session() -> Session:
    from app.data_context import UNBOUND, current_data_scope

    scope = current_data_scope()
    if scope is UNBOUND:
        from app.account_profile import accounts_enabled

        if accounts_enabled():
            from app.data_access import DataAccessError

            raise DataAccessError("An explicit owner scope or trusted control session is required")
        # Existing worker/startup code remains in place during the staged
        # cutover. Bound requests, including missing principals, never use it.
        return control_session_factory()()
    from app.data_access import ScopedSession

    return ScopedSession(bind=get_engine(), scope=scope, expire_on_commit=False)


def session_factory():
    # Resolve at invocation, so factories captured before a task starts still
    # inherit its owner. asyncio.to_thread propagates the owning context too.
    return _context_session


def control_session_scope() -> Iterator[Session]:
    with control_session_factory()() as session:
        yield session


def session_scope() -> Iterator[Session]:
    factory = session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().sqlite_url().replace("%", "%%"))
    return cfg


def require_upgrade_finished(data_dir: Path) -> None:
    pending = data_dir / "runtime/desktop-upgrade-pending.json"
    if pending.exists() or pending.is_symlink():
        raise RuntimeError("Finish or abort the pending offline desktop upgrade before starting AI Station")


def migrate() -> None:
    settings = get_settings()
    require_upgrade_finished(settings.data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "db").mkdir(parents=True, exist_ok=True)
    for name in (
        "artifacts",
        "uploads",
        "thumbnails",
        "logs",
        "runs",
        "worktrees",
        "telemetry",
        "cache",
        "runtime",
        "backups",
    ):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
    # Multiple containers can start together. Only one may migrate at a time.
    with (settings.data_dir / "runtime" / "migrations.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require_upgrade_finished(settings.data_dir)
        command.upgrade(alembic_config(), "head")
