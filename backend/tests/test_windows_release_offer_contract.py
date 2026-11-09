"""Windows publisher admission shares the control-plane fingerprint contract."""

import json
from pathlib import Path

from ai_station_runner.station_release_metadata import admit_release


def test_windows_powershell_fixture_matches_the_shared_release_authority():
    source = Path(__file__).resolve().parents[2] / "packaging/windows/tests/fixtures/release-offer.json"
    fixture = json.loads(source.read_text())
    assert admit_release(fixture["raw"]) == fixture["expected"]


def target_run():
    from types import SimpleNamespace
    from uuid import uuid4

    source = Path(__file__).resolve().parents[2] / "packaging/windows/tests/fixtures/release-offer.json"
    snapshot = json.loads(source.read_text())["expected"]
    package = snapshot["packages"]["windows-x64"]
    run = SimpleNamespace(
        id=str(uuid4()),
        parameters={"platform": "windows-x64"},
        metadata_json={"release": snapshot, "target_version": snapshot["version"]},
    )
    target = {
        "version": snapshot["version"],
        "asset_id": package["id"],
        "installer_sha256": package["sha256"],
        "installer_bytes": package["size_bytes"],
    }
    return run, target


def test_windows_target_binds_the_approved_executable_without_a_fabricated_linux_image(monkeypatch):
    from app import station_update_install as native

    run, target = target_run()
    monkeypatch.setattr(native, "__version__", "0.5.1")
    for phase in ("ready", "apply_requested", "applying", "applied", "succeeded"):
        reply = {"run_id": run.id, "request": run.parameters, "phase": phase, "target": target}
        assert native.checked_reply(run, reply) == reply
        run.metadata_json["native_update"] = reply


def test_changed_or_ambiguous_windows_target_cannot_be_acknowledged():
    import pytest
    from app.station_update_install import checked_target

    run, target = target_run()
    for change in (
        {"asset_id": True},
        {"installer_sha256": "b" * 64},
        {"installer_bytes": True},
        {"installer_bytes": target["installer_bytes"] + 1},
        {"version": "0.5.2"},
        {"bundle_id": "d" * 64},
    ):
        with pytest.raises(ValueError):
            checked_target(run, target | change)
