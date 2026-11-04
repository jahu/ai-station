from types import SimpleNamespace

import pytest
from app import download_storage as storage

GIB = 1024**3


def hardware(free=10 * GIB, status="ready"):
    return {"disk": {"physical_storage": {"status": status, "total_bytes": 100 * GIB, "free_bytes": free}}}


def test_catalog_uses_physical_windows_ceiling_and_preserves_linux_values():
    virtual = SimpleNamespace(total=1000 * GIB, free=800 * GIB)
    assert storage.capacity(virtual, hardware())["free_bytes"] == 10 * GIB
    assert storage.capacity(virtual, hardware())["total_bytes"] == 100 * GIB
    assert storage.capacity(virtual, {})["free_bytes"] == 800 * GIB


@pytest.mark.parametrize(
    "report",
    [hardware(status="unavailable"), hardware(free=-1), hardware(free=True), hardware(free=101 * GIB)],
)
def test_unknown_or_invalid_physical_capacity_never_falls_back_to_virtual(report):
    with pytest.raises(ValueError, match="Windows controls"):
        storage.capacity(SimpleNamespace(total=1000 * GIB, free=800 * GIB), report)


def test_windows_guard_checks_loss_of_physical_budget_during_transfer(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000 * GIB, free=800 * GIB)
    )
    runner = SimpleNamespace(hardware=lambda: hardware(free=GIB))
    guard = storage.DownloadStorage(tmp_path, hardware(), runner, lambda: 2 * GIB)
    guard.check()
    clock[0] += 6
    with pytest.raises(ValueError, match="Not enough free application storage"):
        guard.check()


def test_missing_followup_report_does_not_silently_become_linux(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])
    runner = SimpleNamespace(hardware=lambda: {})
    guard = storage.DownloadStorage(tmp_path, hardware(), runner, lambda: 0)
    clock[0] += 6
    with pytest.raises(ValueError, match="disappeared"):
        guard.check()


def test_guest_local_growth_is_counted_before_next_native_poll(tmp_path, monkeypatch):
    free = [800 * GIB]
    monkeypatch.setattr(
        storage.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000 * GIB, free=free[0])
    )
    guard = storage.DownloadStorage(tmp_path, hardware(), SimpleNamespace(), lambda: 8 * GIB)
    guard.check()
    free[0] -= 3 * GIB
    with pytest.raises(ValueError, match="Not enough free application storage"):
        guard.check()


def test_linux_does_not_add_native_refresh_requests(tmp_path, monkeypatch):
    guard = storage.DownloadStorage(tmp_path, {}, SimpleNamespace(), lambda: 0)
    monkeypatch.setattr(storage.time, "monotonic", lambda: guard.observed + 60)
    guard.check()
