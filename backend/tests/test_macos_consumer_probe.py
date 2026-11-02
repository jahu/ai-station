"""An expensive fresh-host experiment cannot silently execute as a normal test."""

import json

import macos_consumer_probe as probe
import pytest


def test_ordinary_host_is_rejected_before_directories_or_subprocesses(monkeypatch):
    monkeypatch.delenv("AI_STATION_REAL_MAC_CONSUMER_TESTS", raising=False)
    monkeypatch.setattr(probe.Path, "home", lambda: pytest.fail("Accessed a real home before opt-in"))
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: pytest.fail("Unexpected real process"))
    with pytest.raises(ValueError, match="explicit fresh standard public Intel"):
        probe.main()


def test_failure_evidence_locates_code_without_exception_or_local_contents():
    private_material = "PRIVATE_SETUP_LINK_AND_ACCOUNT_FIXTURE"
    try:
        raise RuntimeError(private_material)
    except RuntimeError as error:
        detail = probe.failure(error)
    assert detail["error_type"] == "RuntimeError"
    assert detail["failure_site"]["file"] == "test_macos_consumer_probe.py"
    assert detail["failure_site"]["line"] > 0
    assert private_material not in json.dumps(detail)
    assert "/home/" not in json.dumps(detail)


def test_missing_dependency_reports_only_its_module_identity():
    error = ModuleNotFoundError("PRIVATE_EXCEPTION_MESSAGE", name="ai_station_runner")
    assert probe.failure(error) == {
        "error_type": "ModuleNotFoundError",
        "missing_module": "ai_station_runner",
    }
