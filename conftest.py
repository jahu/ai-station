"""Normal tests must never inherit workstation integrations from a developer .env."""

import pytest
from ai_station_runner.config import Settings as RunnerSettings
from ai_station_runner.config import clear_settings_cache as clear_runner
from app.config import Settings, clear_settings_cache


@pytest.fixture(autouse=True)
def ignore_workstation_dotenv(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setitem(RunnerSettings.model_config, "env_file", None)
    clear_settings_cache()
    clear_runner()
    yield
    clear_settings_cache()
    clear_runner()
