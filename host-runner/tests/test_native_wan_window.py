"""Closed native admission and bounded decoding; never invokes inference."""

from uuid import uuid4

import pytest
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.video import VideoRequest, start_video
from fastapi import HTTPException
from pydantic import ValidationError


def test_larger_window_refuses_before_filesystem_or_process_side_effects(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_WAN_NATIVE_WINDOW_FRAMES", "81")
    clear_settings_cache()
    try:
        body = VideoRequest(
            run_id=uuid4(),
            prompt="A cup on a table",
            frames=121,
            gpu=0,
            permissions=["filesystem_read", "workspace_write"],
        )
        with pytest.raises(HTTPException, match="not qualified"):
            start_video(None, body)
    finally:
        clear_settings_cache()


@pytest.mark.parametrize("window", [80, 120, 122, 161])
def test_operator_gate_is_closed_to_unreviewed_window_sizes(window):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, wan_native_window_frames=window)


@pytest.mark.parametrize("window", [81, 121])
def test_exact_environment_window_spelling_is_accepted(monkeypatch, window):
    monkeypatch.setenv("AI_STATION_WAN_NATIVE_WINDOW_FRAMES", str(window))
    assert Settings(_env_file=None).wan_native_window_frames == window
