import importlib
import subprocess
from pathlib import Path

import pytest
from ai_station_runner import diagnostics, nvidia, telemetry


@pytest.fixture
def projected(monkeypatch, tmp_path):
    binary = tmp_path / "nvidia-smi"
    binary.write_text("fixture only; never executed")
    binary.chmod(0o700)
    monkeypatch.setattr(nvidia, "WSL_NVIDIA_SMI", binary)
    monkeypatch.setattr(nvidia.shutil, "which", lambda _: None)
    monkeypatch.setattr(nvidia, "is_wsl", lambda: True)
    return binary


def test_projected_binary_is_used_only_when_path_is_missing(projected, monkeypatch):
    assert nvidia.executable() == str(projected)
    monkeypatch.setattr(nvidia.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    assert nvidia.executable() == "nvidia-smi"


def test_linux_never_adopts_a_projected_wsl_binary(projected, monkeypatch):
    monkeypatch.setattr(nvidia, "is_wsl", lambda: False)
    assert nvidia.executable() == "nvidia-smi"


@pytest.mark.parametrize("state", ["missing", "nonexecutable", "directory"])
def test_invalid_projected_cli_is_not_adopted(projected, state):
    if state == "missing":
        projected.unlink()
    elif state == "nonexecutable":
        projected.chmod(0o600)
    else:
        projected.unlink()
        projected.mkdir()
    assert nvidia.executable() == "nvidia-smi"


@pytest.mark.parametrize(
    "release, expected",
    [("6.6.87.2-microsoft-standard-WSL2", True), ("6.8.0-88-generic", False), (None, False)],
)
def test_wsl_detection_uses_the_kernel_not_ambient_environment(monkeypatch, release, expected):
    def read(path):
        assert str(path) == "/proc/sys/kernel/osrelease"
        if release is None:
            raise PermissionError()
        return release

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setenv("WSL_DISTRO_NAME", "untrusted")
    assert nvidia.is_wsl() is expected


def test_sensor_rejection_retains_actual_wsl_devices_and_unknown_sensors(projected, monkeypatch):
    calls = []

    def query(argv, **kwargs):
        calls.append((argv, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Not Supported")
        return subprocess.CompletedProcess(
            argv, 0, stdout="3, GPU-first, NVIDIA One, 512, 12288\n7, GPU-second, NVIDIA Two, N/A, 24576\n"
        )

    monkeypatch.setattr(subprocess, "run", query)
    result = telemetry.gpus()
    assert [g["index"] for g in result] == [3, 7]
    assert [g["memory_total_mib"] for g in result] == [12288, 24576]
    assert result[0]["memory_used_mib"] == 512 and result[1]["memory_used_mib"] is None
    for gpu in result:
        assert all(gpu[k] is None for k in ["utilization", "temperature_c", "fan_percent", "power_watts"])
    assert len(calls) == 2 and all(argv[0] == str(projected) for argv, _ in calls)
    assert calls[1][0][1] == "--query-gpu=index,uuid,name,memory.used,memory.total"
    assert all(kwargs["timeout"] == 5 and kwargs["check"] is False for _, kwargs in calls)


def test_supported_wsl_sensors_need_no_second_query(projected, monkeypatch):
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout="3, GPU-one, NVIDIA One, 20, 512, 12288, 42, N/A, 80\n"
        )

    monkeypatch.setattr(subprocess, "run", query)
    result = telemetry.gpus()
    assert result[0]["utilization"] == 20 and result[0]["temperature_c"] == 42
    assert len(calls) == 1 and calls[0][0] == str(projected)


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("nvidia-smi", 5)])
def test_missing_or_unresponsive_wsl_cli_is_not_retried(projected, monkeypatch, error):
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        raise error

    monkeypatch.setattr(subprocess, "run", query)
    assert telemetry.gpus() == [] and len(calls) == 1


@pytest.mark.parametrize("failure", ["exit", "timeout", "permission", "malformed"])
def test_failed_wsl_fallback_never_invents_devices(projected, monkeypatch, failure):
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 1, stdout="")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        if failure == "permission":
            raise PermissionError()
        return subprocess.CompletedProcess(argv, 1 if failure == "exit" else 0, stdout="bad,row")

    monkeypatch.setattr(subprocess, "run", query)
    assert telemetry.gpus() == []
    assert len(calls) == 2


def test_native_nvml_failure_is_not_hidden_with_a_reduced_query(monkeypatch):
    monkeypatch.setattr(nvidia, "is_wsl", lambda: False)
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Driver/library version mismatch")

    monkeypatch.setattr(subprocess, "run", query)
    assert telemetry.gpus() == [] and len(calls) == 1


def test_diagnostics_execute_the_same_projected_cli(projected, monkeypatch):
    monkeypatch.setattr(
        nvidia.shutil, "which", lambda value: str(projected) if value == str(projected) else None
    )
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="NVIDIA-SMI version: fixture")

    monkeypatch.setattr(subprocess, "run", query)
    assert diagnostics.command_version("nvidia-smi")["status"] == "available"
    assert calls == [[str(projected), "--version"]]


@pytest.mark.parametrize("name", ["avatar_prepare", "video_prepare", "effects_prepare", "fish_prepare"])
def test_guided_media_driver_checks_use_the_same_projected_cli(projected, monkeypatch, name):
    module = importlib.import_module(f"ai_station_runner.{name}")
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="580.88\n580.88\n")

    monkeypatch.setattr(subprocess, "run", query)
    assert module.driver_supported("570.0")
    assert calls == [[str(projected), "--query-gpu=driver_version", "--format=csv,noheader"]]


@pytest.mark.parametrize("name", ["effects_prepare", "fish_prepare"])
def test_bf16_checks_retain_exact_device_indexes(projected, monkeypatch, name):
    module = importlib.import_module(f"ai_station_runner.{name}")
    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="3, 8.6\n7, 7.5\n")

    monkeypatch.setattr(subprocess, "run", query)
    devices = [{"index": i, "memory_total_mib": 12288} for i in [3, 7]]
    assert module.compatible_devices(devices) == devices[:1]
    assert calls == [[str(projected), "--query-gpu=index,compute_cap", "--format=csv,noheader,nounits"]]


def test_process_inspection_uses_projection_and_does_not_claim_unsupported_success(projected, monkeypatch):
    from ai_station_runner.gpu_processes import collect

    calls = []

    def query(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(subprocess, "run", query)
    result = collect()
    assert result["status"] == "unavailable" and result["processes"] == []
    assert calls[0][0] == str(projected)
