"""Refreshing an unchanged verified renderer must not turn it cold again."""

from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from ai_station_runner import motion_runtime as runtime


@pytest.fixture
def cache(tmp_path, monkeypatch):
    state = SimpleNamespace(
        clock=0.0,
        futures=[],
        settings=SimpleNamespace(motion_image="ai-station-motion:fixture", host_data_dir=lambda: tmp_path),
    )

    def submit(*args):
        future = Future()
        state.futures.append(future)
        return future

    monkeypatch.setattr(runtime, "_probe", None)
    monkeypatch.setattr(runtime, "_last_ready", None)
    monkeypatch.setattr(runtime, "_pool", SimpleNamespace(submit=submit))
    monkeypatch.setattr(runtime, "get_settings", lambda: state.settings)
    monkeypatch.setattr(runtime, "available", lambda: True)
    monkeypatch.setattr(runtime, "observation", lambda value: value["identity"])
    monkeypatch.setattr(runtime.time, "monotonic", lambda: state.clock)
    return state


def test_background_revalidation_retains_only_a_previously_verified_selection(cache):
    assert runtime.capabilities()["readiness"] == "checking"
    cache.futures[0].set_result({"identity": "a" * 64})
    first = runtime.capabilities()
    assert first["available"] and first["observation"] == "a" * 64
    cache.clock = 31
    refreshing = runtime.capabilities()
    assert len(cache.futures) == 2 and not cache.futures[1].done()
    assert refreshing["available"] and refreshing["observation"] == first["observation"]
    cache.futures[1].set_exception(ValueError("Image disappeared"))
    assert runtime.capabilities()["available"] is False
    cache.clock = 62
    assert runtime.capabilities()["readiness"] == "checking"
    cache.futures[2].set_result({"identity": "b" * 64})
    assert runtime.capabilities()["observation"] == "b" * 64


def test_changed_selection_cannot_borrow_an_old_ready_result(cache):
    runtime.capabilities()
    cache.futures[0].set_result({"identity": "a" * 64})
    assert runtime.capabilities()["available"]
    cache.settings.motion_image = "ai-station-motion:another"
    changed = runtime.capabilities()
    assert changed["available"] is False and changed["readiness"] == "checking"
    assert "observation" not in changed
    cache.futures[1].set_result({"identity": "b" * 64})
    assert runtime.capabilities()["observation"] == "b" * 64
