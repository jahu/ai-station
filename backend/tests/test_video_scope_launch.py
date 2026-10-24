"""The typed native entry chooses fixed owned scope parameters, never raw argv."""

import json
from uuid import uuid4

import pytest
from ai_station_runner import memory_scope, video
from ai_station_runner.config import clear_settings_cache
from fastapi import HTTPException
from test_video import bridge as bridge


def request(**changes):
    return video.VideoRequest(
        run_id=uuid4(), prompt="Coast", gpu=7, permissions=["filesystem_read", "workspace_write"], **changes
    )


def test_default_native_request_and_launch_keep_their_previous_identity(bridge):
    body = request()
    assert "memory_profile" not in body.model_dump(mode="json")

    class Manager:
        def start(self, **kwargs):
            assert kwargs["argv"][1:3] == ["-m", "ai_station_runner.video_job"]
            assert "XDG_RUNTIME_DIR" not in kwargs["env"]
            return kwargs

    video.start_video(Manager(), body)


def test_disabled_profile_rejects_before_creating_a_work_directory(bridge):
    body = request(memory_profile="bounded_11g")
    with pytest.raises(HTTPException) as error:
        video.start_video(None, body)
    assert error.value.status_code == 409
    root = video.get_settings().host_data_dir().resolve()
    assert not (root / "runs" / str(body.run_id)).exists()


def test_bounded_native_launch_persists_scope_choice_and_keeps_process_manager_ownership(bridge, monkeypatch):
    monkeypatch.setenv("AI_STATION_WAN_BOUNDED_PROFILE", "true")
    monkeypatch.setattr(memory_scope, "available", lambda: True)
    monkeypatch.setattr(memory_scope.shutil, "which", lambda name: "/usr/bin/systemd-run")
    clear_settings_cache()
    body = request(memory_profile="bounded_11g")

    class Manager:
        def start(self, **kwargs):
            prefix = memory_scope.scope_prefix(str(body.run_id), 11264)
            assert kwargs["argv"][: len(prefix)] == prefix
            assert kwargs["argv"][len(prefix) + 1 : len(prefix) + 3] == ["-m", "ai_station_runner.video_job"]
            assert kwargs["run_id"] == str(body.run_id) and kwargs["executor"] == "wan_video"
            assert kwargs["env"]["OMP_NUM_THREADS"] == "4"
            assert kwargs["env"]["XDG_RUNTIME_DIR"]
            assert "AI_STATION_LLM_API_KEY" not in kwargs["env"]
            config = json.loads(kwargs["cwd"].joinpath("request.json").read_text())
            assert config["request"]["memory_profile"] == "bounded_11g"
            assert "weight_dtype" not in config["request"]
            return kwargs

    video.start_video(Manager(), body)
