import pytest
from ai_station_runner import avatars as native_avatar
from ai_station_runner.config import clear_settings_cache
from test_avatars import avatar_bridge as avatar_bridge


def test_native_avatar_readiness_uses_existing_installation_without_launching(avatar_bridge):
    host, calls = avatar_bridge
    response = host.get("/v1/avatar/capabilities")
    assert response.status_code == 200 and response.json()["available"]
    assert response.json()["offline"] and response.json()["max_audio_seconds"] == 60
    assert not calls


@pytest.mark.parametrize("missing", ["installation", "gpu"])
def test_native_avatar_readiness_reports_missing_resources(avatar_bridge, monkeypatch, missing):
    host, calls = avatar_bridge
    if missing == "installation":
        monkeypatch.setenv("AI_STATION_ECHOMIMIC_MODELS", "")
        clear_settings_cache()
    else:
        monkeypatch.setattr(native_avatar, "collect", lambda root: {"gpus": []})
    assert host.get("/v1/avatar/capabilities").json()["available"] is False
    assert not calls
