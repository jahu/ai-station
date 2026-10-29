"""Typed candidate dispatch, replay ownership and immutable launch inputs."""

import json
import sys
import time
import wave
from uuid import uuid4

import pytest
from ai_station_runner import sonic_jobs as jobs
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.sonic_contract import PROFILE, digest, inspect_inputs
from PIL import Image
from pydantic import ValidationError


class Manager:
    def __init__(self, root):
        self.data_dir, self.records, self.calls = root, {}, []

    def inspect(self, run_id):
        if run_id not in self.records:
            raise ProcessNotOwned(run_id)
        return self.records[run_id]

    def start(self, **values):
        self.calls.append(values)
        owned = {"run_id": values["run_id"], "executor": values["executor"], "pid": 77}
        self.records[values["run_id"]] = owned
        return owned


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_STATION_REAL_GPU_TESTS", "1")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-never-reach-native-env")
    monkeypatch.setattr(jobs, "installation_observation", lambda *args: "c" * 64)
    monkeypatch.setattr("ai_station_runner.memory_scope.shutil.which", lambda name: "/usr/bin/systemd-run")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    portrait, audio = artifacts / "portrait.png", artifacts / "speech.wav"
    Image.new("RGB", (512, 768), "white").save(portrait)
    with wave.open(str(audio), "wb") as target:
        target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        target.writeframes(b"\x00" * (16321 * 2))

    def media(path):
        return {
            "relative_path": path.relative_to(tmp_path).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": digest(path),
        }

    body = jobs.WholeAvatarRequest(
        run_id=uuid4(),
        recipe={"id": PROFILE, "observation": "c" * 64},
        portrait=media(portrait),
        audio=media(audio),
        seed=43,
        gpus=[7, 11],
        permissions=["filesystem_read", "workspace_write"],
        deadline_at=time.time() + 600,
        observed_input=inspect_inputs(tmp_path, media(portrait), media(audio)),
    )
    manager = Manager(tmp_path)
    arguments = {
        "python": sys.executable,
        "runtime": tmp_path / "installed",
        "models": tmp_path / "weights",
        "hardware": {"gpus": [{"index": 7, "uuid": "GPU-first"}, {"index": 11, "uuid": "GPU-second"}]},
    }
    return body, manager, arguments


def test_launcher_uses_fixed_argv_private_scope_and_only_allocated_discovered_gpus(prepared):
    body, manager, arguments = prepared
    launched = jobs.start_qualification(manager, body, **arguments)
    assert launched["executor"] == "sonic_whole" and len(manager.calls) == 1
    call = manager.calls[0]
    assert call["deadline_at"] == body.deadline_at
    assert call["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-first,GPU-second"
    assert "AWS_SECRET_ACCESS_KEY" not in call["env"]
    assert "--property=MemoryMax=18432M" in call["argv"] and "--property=MemorySwapMax=0" in call["argv"]
    assert "--property=RuntimeMaxSec=14400" in call["argv"]
    config = call["cwd"] / "request.json"
    assert config.stat().st_mode & 0o777 == 0o600
    assert json.loads(config.read_text()) == body.native_request()
    assert call["argv"][-2:] == ["--request", str(config)]
    assert call["env"]["PYTHONPATH"].endswith("/host-runner")
    assert call["env"]["TMPDIR"] == str(call["cwd"])


def test_lost_start_reply_reuses_exact_owned_journal_without_a_second_dispatch(prepared, monkeypatch):
    body, manager, arguments = prepared
    start = manager.start

    def lost(**kwargs):
        start(**kwargs)
        raise TimeoutError("Dispatch reply lost")

    monkeypatch.setattr(manager, "start", lost)
    with pytest.raises(TimeoutError):
        jobs.start_qualification(manager, body, **arguments)
    recovered = jobs.start_qualification(manager, body, **arguments)
    assert recovered["pid"] == 77 and len(manager.calls) == 1


@pytest.mark.parametrize(
    "change", ["body", "python", "runtime", "models", "receipt", "request", "wrong-executor", "journal-gone"]
)
def test_replay_cannot_change_launch_identity_or_reexecute_unknown_work(prepared, change):
    body, manager, arguments = prepared
    jobs.start_qualification(manager, body, **arguments)
    work = manager.calls[0]["cwd"]
    if change == "body":
        body = body.model_copy(update={"seed": 44})
    elif change in {"python", "runtime", "models"}:
        arguments[change] = sys.executable if change == "python" else manager.data_dir / "different"
        if change == "python":
            arguments[change] = "/bin/true"
    elif change in {"receipt", "request"}:
        path = work / ("launch.json" if change == "receipt" else "request.json")
        path.write_text("{}")
    elif change == "wrong-executor":
        manager.records[str(body.run_id)]["executor"] = "someone_else"
    else:
        manager.records.clear()
    with pytest.raises(ValueError):
        jobs.start_qualification(manager, body, **arguments)
    assert len(manager.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("gpus", [7, 7]),
        ("gpus", [True]),
        ("gpus", [-1]),
        ("gpus", [7, 11, 12]),
        ("permissions", []),
        ("permissions", ["filesystem_read", "network_external"]),
        ("command", "arbitrary"),
        ("model_dir", "/outside"),
        ("steps", 4),
        ("seed", True),
    ],
)
def test_invalid_permissions_devices_or_free_form_execution_controls_are_rejected(prepared, field, value):
    body, manager, _ = prepared
    with pytest.raises(ValidationError):
        jobs.WholeAvatarRequest.model_validate({**body.model_dump(), field: value})
    assert not manager.calls and not (manager.data_dir / "runs").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "missing-gpu",
        "duplicate-gpu-uuid",
        "changed-model",
        "changed-input",
        "scope-unavailable",
        "opt-in-missing",
        "journal-without-receipt",
    ],
)
def test_unsafe_dispatch_does_not_create_work_or_launch_a_process(prepared, monkeypatch, fault):
    body, manager, arguments = prepared
    if fault == "missing-gpu":
        arguments["hardware"]["gpus"].pop()
    elif fault == "duplicate-gpu-uuid":
        arguments["hardware"]["gpus"][1]["uuid"] = "GPU-first"
    elif fault == "changed-model":
        monkeypatch.setattr(jobs, "installation_observation", lambda *args: "f" * 64)
    elif fault == "changed-input":
        (manager.data_dir / "artifacts/speech.wav").write_bytes(b"changed")
    elif fault == "scope-unavailable":
        monkeypatch.setattr("ai_station_runner.memory_scope.shutil.which", lambda name: None)
    elif fault == "opt-in-missing":
        monkeypatch.delenv("AI_STATION_REAL_GPU_TESTS")
    else:
        manager.records[str(body.run_id)] = {"executor": "sonic_whole", "pid": 77}
    with pytest.raises(ValueError):
        jobs.start_qualification(manager, body, **arguments)
    assert not manager.calls and not (manager.data_dir / "runs").exists()
