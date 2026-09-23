import pytest
from app.config import clear_settings_cache
from app.db import migrate, reset_engine, session_factory


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
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
