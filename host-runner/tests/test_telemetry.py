import subprocess

from ai_station_runner.diagnostics import command_version
from ai_station_runner.telemetry import gpus


def test_missing_nvidia_fields_remain_unknown(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, stdout="7, GPU-id, Test GPU, 14, 1234, 12000, 42, [Not Supported], N/A\n"
        ),
    )
    result = gpus()[0]
    assert result["index"] == 7
    assert result["utilization"] == 14
    assert result["fan_percent"] is None
    assert result["power_watts"] is None


def test_command_failure_is_not_available_even_with_output(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/bin/tool")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout="", stderr="Could not initialize"),
    )
    assert command_version("tool")["status"] == "misconfigured"
