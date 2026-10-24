"""A bounded profile cannot accidentally load models outside its kernel scope."""

from uuid import uuid4

import pytest
from ai_station_runner import memory_scope
from ai_station_runner.wan_profiles import prepare_job


def bounded(**changes):
    return {
        "run_id": str(uuid4()),
        "memory_profile": "bounded_11g",
        "width": 1280,
        "height": 704,
        "steps": 20,
        **changes,
    }


def test_default_loader_never_requires_or_changes_a_memory_scope(monkeypatch):
    monkeypatch.setattr(memory_scope, "require_scope", lambda *a: pytest.fail("Legacy launch changed"))
    assert prepare_job({}) == "default"


def test_bounded_loader_is_fixed_and_requires_its_actual_scope(monkeypatch):
    seen = []
    monkeypatch.setattr(memory_scope, "require_scope", lambda *a: seen.append(a))
    request = bounded()
    assert prepare_job(request) == "fp8_e4m3fn"
    assert seen == [(request["run_id"], 11264)]


def test_absent_kernel_scope_prevents_bounded_model_loading(monkeypatch):
    def reject(*args):
        raise ValueError("No verified scope")

    monkeypatch.setattr(memory_scope, "require_scope", reject)
    with pytest.raises(ValueError, match="No verified scope"):
        prepare_job(bounded())


@pytest.mark.parametrize(
    "change",
    [{"width": 512}, {"height": 288}, {"steps": 4}, {"steps": True}, {"steps": 41}],
)
def test_unqualified_geometry_or_steps_reject_before_scope_or_model_import(monkeypatch, change):
    monkeypatch.setattr(
        memory_scope, "require_scope", lambda *a: pytest.fail("Invalid profile reached scope")
    )
    with pytest.raises(ValueError, match="1280x704"):
        prepare_job(bounded(**change))


@pytest.mark.parametrize("profile", [None, [], True, "arbitrary"])
def test_unrecognized_profile_cannot_select_execution_settings(profile):
    with pytest.raises(ValueError, match="Unsupported fixed Wan memory profile"):
        prepare_job({"memory_profile": profile})
