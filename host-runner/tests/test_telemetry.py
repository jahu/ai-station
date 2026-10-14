import subprocess

import pytest
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


def test_compute_processes_are_bounded_and_do_not_expose_paths(monkeypatch):
    from ai_station_runner.gpu_processes import collect

    calls = []

    def query(argv, **kwargs):
        calls.append((argv, kwargs))
        kwargs["stdout"].write(
            'GPU-abc, 123, "/private/python,worker", 256\nGPU-xyz, 456, /bin/server, [N/A]\nGPU-abc, 123, duplicate, 512\n'
        )
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='GPU-abc, 123, "/private/python,worker", 256\nGPU-xyz, 456, /bin/server, [N/A]\nGPU-abc, 123, duplicate, 512\n',
        )

    monkeypatch.setattr(subprocess, "run", query)
    result = collect()
    assert result["status"] == "available" and len(result["processes"]) == 2
    assert result["processes"][0] == {
        "gpu_uuid": "GPU-abc",
        "pid": 123,
        "name": "python,worker",
        "memory_used_mib": 256,
    }
    assert result["processes"][1]["memory_used_mib"] is None
    assert calls[0][0] == [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ]
    assert calls[0][1]["timeout"] == 3


def test_compute_process_partial_and_truncated_are_explicit(monkeypatch):
    from ai_station_runner.gpu_processes import collect

    data = "bad,row\nGPU-x, -1, python, N/A\n" + "".join(
        f"GPU-x, {i}, /bin/python, 1\n" for i in range(1, 131)
    )

    def query(*a, **k):
        k["stdout"].write(data)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", query)
    result = collect()
    assert result["status"] == "partial" and result["truncated"]
    assert len(result["processes"]) == 128
    assert all(p["pid"] > 0 for p in result["processes"])


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "oversize"])
def test_compute_process_failure_is_not_empty_success(monkeypatch, failure):
    from ai_station_runner.gpu_processes import collect

    def query(*a, **k):
        if failure == "missing":
            raise FileNotFoundError()
        if failure == "timeout":
            raise subprocess.TimeoutExpired("nvidia-smi", 3)
        k["stdout"].write("x" * 65537)
        return subprocess.CompletedProcess(
            [], 1 if failure == "exit" else 0, stdout="x" * 65537, stderr="private details"
        )

    monkeypatch.setattr(subprocess, "run", query)
    result = collect()
    assert result["status"] == "unavailable" and result["processes"] == []
    assert "private details" not in str(result)


def test_compute_process_endpoint_is_operational_and_accepts_no_command(monkeypatch):
    from ai_station_runner import app as runner
    from fastapi.testclient import TestClient

    calls = []

    def observation():
        calls.append(True)
        return {"status": "available", "sampled_at": None, "processes": [], "truncated": False}

    monkeypatch.setattr(runner, "collect_gpu_processes", observation)
    with TestClient(runner.app) as client:
        assert client.get("/v1/gpu-processes").json()["status"] == "available"
        assert client.post("/v1/gpu-processes", json={"command": "unrestricted"}).status_code == 405
    assert calls == [True]
