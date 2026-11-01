import json
import os
from pathlib import Path

import pytest
from ai_station_runner import windows_storage as storage

GIB = 1024**3


@pytest.fixture
def guest(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    root = home / ".local/share/ai-station-desktop"
    boot = tmp_path / "boot"
    boot.write_text("fixture-boot")
    marker = tmp_path / "guest-marker"
    marker.touch()
    monkeypatch.setattr(storage, "HOME", home)
    monkeypatch.setattr(storage, "ROOT", root)
    monkeypatch.setattr(storage, "BOOT", boot)
    monkeypatch.setattr(storage, "GUEST", marker)
    monkeypatch.setattr(storage, "marker", lambda: None)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(storage.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda _: storage.Usage(1000 * GIB, 200 * GIB, 800 * GIB)
    )
    storage.write(100 * GIB, 20 * GIB)
    return root


def test_actual_virtual_growth_reduces_physical_quota_without_reclaim_credit(guest, monkeypatch):
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda _: storage.Usage(1000 * GIB, 205 * GIB, 795 * GIB)
    )
    assert storage.disk_usage(guest).free == 15 * GIB - storage.HEADROOM
    assert storage.disk_usage(guest).total == 100 * GIB
    # Removing files cannot claim more Windows space until Windows observes it.
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda _: storage.Usage(1000 * GIB, 100 * GIB, 900 * GIB)
    )
    assert storage.disk_usage(guest).free == 20 * GIB - storage.HEADROOM


@pytest.mark.parametrize(
    "change",
    [
        {"observed_at": 54.9},
        {"observed_at": 101},
        {"observed_at": float("nan")},
        {"observed_at": True},
        {"boot_id": "previous-boot"},
        {"free_bytes": -1},
        {"free_bytes": 101 * GIB},
        {"free_bytes": True},
        {"total_bytes": 2**61},
        {"schema": True},
        {"unrecognized": "field"},
    ],
)
def test_stale_invalid_and_previous_boot_reports_cannot_admit_writes(guest, change):
    path = guest / "windows-volume.json"
    value = {**json.loads(path.read_text()), **change}
    path.write_text(json.dumps(value))
    assert storage.physical(guest)["status"] == "unavailable"
    assert storage.disk_usage(guest).free == 0


@pytest.mark.parametrize("unsafe", ["missing", "symlink", "hardlink", "public", "oversize", "invalid_json"])
def test_unsafe_reports_are_not_adopted_or_overwritten(guest, tmp_path, unsafe):
    path = guest / "windows-volume.json"
    original = path.read_bytes()
    if unsafe in {"missing", "symlink", "hardlink"}:
        path.unlink()
    if unsafe == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(original)
        path.symlink_to(outside)
    elif unsafe == "hardlink":
        outside = tmp_path / "outside"
        outside.write_bytes(original)
        outside.chmod(0o600)
        os.link(outside, path)
    elif unsafe == "public":
        path.chmod(0o644)
    elif unsafe == "oversize":
        path.write_text(" " * 4097)
    elif unsafe == "invalid_json":
        path.write_text("bad json")
    assert storage.disk_usage(guest).free == 0
    if unsafe in {"symlink", "hardlink", "public"}:
        with pytest.raises(ValueError, match="private"):
            storage.write(100 * GIB, 20 * GIB)
        assert path.read_bytes() == original


def test_atomic_refresh_retains_private_mode_and_only_updates_capacity(guest):
    storage.write(100 * GIB, 10 * GIB)
    report = guest / "windows-volume.json"
    assert report.stat().st_mode & 0o777 == 0o600
    assert storage.disk_usage(guest).free == 10 * GIB - storage.HEADROOM
    assert sorted(p.name for p in guest.iterdir()) == ["windows-volume.json"]


def test_linux_keeps_its_actual_filesystem_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "GUEST", tmp_path / "absent")
    expected = storage.shutil.disk_usage(tmp_path)
    assert storage.physical(tmp_path) is None
    assert storage.disk_usage(tmp_path) == expected


def test_fixed_entry_point_rejects_paths_and_non_decimal_inputs(monkeypatch):
    monkeypatch.setattr(storage.sys, "argv", ["helper", "100", "../somewhere"])
    with pytest.raises(ValueError, match="byte counts"):
        storage.main()


def test_untrusted_guest_marker_is_rejected(tmp_path, monkeypatch):
    marker = tmp_path / "guest"
    marker.write_text("untrusted")
    marker.chmod(0o666)
    monkeypatch.setattr(storage, "GUEST", marker)
    with pytest.raises(ValueError, match="immutable"):
        storage.marker()
