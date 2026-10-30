import pytest
from app.config import clear_settings_cache
from app.db import migrate, reset_engine, session_factory


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    from ai_station_runner.config import Settings as RunnerSettings
    from app.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setitem(RunnerSettings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AI_STATION_DATABASE_URL", "")
    monkeypatch.setenv("AI_STATION_ENABLE_TEST_EXECUTOR", "true")
    monkeypatch.setenv("AI_STATION_RUNNER_SOCKET", str(tmp_path / "absent.sock"))
    clear_settings_cache()
    reset_engine()
    migrate()
    yield
    reset_engine()
    clear_settings_cache()


@pytest.fixture
def session():
    with session_factory()() as current:
        yield current


@pytest.fixture
def legacy_schema(tmp_path):
    """Project synthetic unowned fixture rows into a real historical schema.

    Ownership migrations deliberately reject downgrading populated databases.
    Historical migration tests must start from a legacy database instead of
    weakening that protection. Only the disposable, unclaimed fixture may be
    copied; account data is never stripped to make a downgrade succeed.
    """
    import sqlite3
    from pathlib import Path

    from alembic import command
    from app.db import alembic_config, get_engine
    from sqlalchemy import MetaData, create_engine, select

    def prepare(revision):
        source = get_engine()
        metadata = MetaData()
        with source.connect() as connection:
            metadata.reflect(
                connection,
                only=lambda name, _: name != "alembic_version" and not name.startswith("memory_fts"),
            )
            for table in metadata.tables.values():
                if "owner_id" in table.c:
                    assert (
                        connection.scalar(
                            select(table.c.owner_id).where(table.c.owner_id.is_not(None)).limit(1)
                        )
                        is None
                    )
            users = metadata.tables["users"]
            assert (
                connection.scalar(select(users.c.id).where(users.c.bootstrap_pending.is_(False)).limit(1))
                is None
            )
            rows = {
                table.name: [dict(row) for row in connection.execute(select(table)).mappings()]
                for table in metadata.tables.values()
            }
        legacy_file = tmp_path / f"legacy-{revision}.sqlite"
        legacy = create_engine(f"sqlite:///{legacy_file}")
        try:
            with legacy.begin() as connection:
                config = alembic_config()
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
                old = MetaData()
                old.reflect(
                    connection,
                    only=lambda name, _: name != "alembic_version" and not name.startswith("memory_fts"),
                )
                connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
                for table in old.sorted_tables:
                    for row in rows.get(table.name, []):
                        connection.execute(
                            table.insert().values(
                                **{key: value for key, value in row.items() if key in table.c}
                            )
                        )
                assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        finally:
            legacy.dispose()
        # SQLite backup replaces the fixture DB atomically without leaving WAL
        # pages from its former schema or changing the configured artifact root.
        database = source.url.database
        assert database is not None and Path(database).resolve().is_relative_to(tmp_path.resolve())
        reset_engine()
        with sqlite3.connect(legacy_file) as original, sqlite3.connect(database) as destination:
            original.backup(destination)

    return prepare
