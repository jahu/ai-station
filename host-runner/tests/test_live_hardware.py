from types import SimpleNamespace

from ai_station_runner import live_hardware


def test_cuda13_profile_refuses_older_architectures_and_small_gpus(monkeypatch):
    monkeypatch.setattr(
        live_hardware.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="3, 6.1\n7, 8.6\n9, 7.5\n")
    )
    hardware = {
        "gpus": [
            {"index": 3, "memory_total_mib": 12288},
            {"index": 7, "memory_total_mib": 6144},
            {"index": 9, "memory_total_mib": 2048},
        ]
    }
    assert live_hardware.compatible_gpus(hardware) == [hardware["gpus"][1]]


def test_unreadable_architecture_is_unknown_instead_of_guessed_compatible(monkeypatch):
    monkeypatch.setattr(
        live_hardware.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="7, [N/A]\n")
    )
    assert live_hardware.compatible_gpus({"gpus": [{"index": 7, "memory_total_mib": 12288}]}) == []
