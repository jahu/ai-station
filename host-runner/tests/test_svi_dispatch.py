"""Typed native dispatch, source binding and resource ownership; no inference."""

import hashlib
import json
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import svi_environment, svi_video
from ai_station_runner.svi_identity import profile_identity
from ai_station_runner.wan_svi_context import METADATA_KEY, SHAPE
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError


def runtime():
    return {
        "profile": svi_environment.PROFILE,
        "manifest_sha256": svi_environment.fingerprint(svi_environment.recipe()),
        "environment_id": "a" * 64,
    }


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    image = tmp_path / "artifacts/reference.png"
    image.parent.mkdir()
    Image.new("RGB", (64, 64), "navy").save(image)
    source = {
        "relative_path": "artifacts/reference.png",
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "size_bytes": image.stat().st_size,
    }
    body = svi_video.SviRequest(
        run_id=uuid4(),
        deadline_at=time.time() + 1800,
        managed_runtime=runtime(),
        image=source,
        prompt="A paper boat moves across a pond",
        seed=317,
        gpu=7,
        permissions=["filesystem_read", "workspace_write"],
    )
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return {"run_id": kwargs["run_id"], "pid": 999, "executor": kwargs["executor"]}

    manager = SimpleNamespace(start=start)
    monkeypatch.setattr(
        svi_video, "get_settings", lambda: SimpleNamespace(host_data_dir=lambda: tmp_path, runner_id="test")
    )
    monkeypatch.setattr(
        svi_environment, "resolve_public", lambda *_: {"video_python": tmp_path / "owned/venv/bin/python"}
    )
    monkeypatch.setattr(
        svi_video, "capabilities", lambda *_: {"available": True, "eligible_gpu_indices": [7]}
    )
    monkeypatch.setattr(
        svi_video, "scope_prefix", lambda identity, ram: ["owned-memory-scope", identity, str(ram)]
    )
    return tmp_path, body, manager, calls


def test_native_dispatch_fixes_argv_scope_gpu_home_and_absolute_deadline(fixture):
    root, body, manager, calls = fixture
    result = svi_video.start_video(manager, body)
    call = calls[0]
    assert result["executor"] == "wan_svi_video"
    assert call["argv"][:3] == ["owned-memory-scope", str(body.run_id), "18432"]
    assert call["argv"][3] == str(root / "owned/venv/bin/python")
    assert call["argv"][4].endswith("svi_video_job.py")
    assert call["deadline_at"] == body.deadline_at
    assert call["env"]["CUDA_VISIBLE_DEVICES"] == "7"
    assert call["env"]["HF_HUB_OFFLINE"] == call["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert call["env"]["HOME"] == str(call["cwd"] / "home")
    assert "LD_LIBRARY_PATH" not in call["env"]
    config = json.loads((call["cwd"] / "request.json").read_text())
    assert config["profile_identity"] == profile_identity(runtime(), body.image.sha256)
    assert config["request"] == body.model_dump(mode="json")
    assert (call["cwd"] / "request.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(HTTPException, match="Inspect existing"):
        svi_video.start_video(manager, body)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["permissions", "gpu", "expired", "too_long", "image_hash", "symlink"])
def test_invalid_dispatch_refuses_before_creating_run_work(fixture, change):
    root, body, manager, calls = fixture
    if change == "permissions":
        body.permissions = ["filesystem_read"]
    elif change == "gpu":
        body.gpu = 0
    elif change == "expired":
        body.deadline_at = time.time() - 1
    elif change == "too_long":
        body.deadline_at = time.time() + 7200
    elif change == "image_hash":
        body.image.sha256 = "b" * 64
    else:
        target = root / "outside.png"
        (root / "artifacts/reference.png").rename(target)
        (root / "artifacts/reference.png").symlink_to(target)
    with pytest.raises((HTTPException, ValueError)):
        svi_video.start_video(manager, body)
    assert not calls and not (root / "runs").exists()


def motion(root, profile):
    count = 16 * 60 * 104 * 4
    header = {
        "motion": {"shape": list(SHAPE), "dtype": "F32", "data_offsets": [0, count]},
        "__metadata__": {METADATA_KEY: profile},
    }
    raw = json.dumps(header).encode()
    path = root / "artifacts/motion.safetensors"
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + bytes(count))
    return {
        "relative_path": "artifacts/motion.safetensors",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def test_prior_motion_matches_the_original_anchor_and_complete_engine(fixture):
    root, body, manager, calls = fixture
    body.previous_motion = svi_video.MediaInput.model_validate(
        motion(root, profile_identity(runtime(), body.image.sha256))
    )
    svi_video.start_video(manager, body)
    assert len(calls) == 1


def test_motion_from_a_different_original_image_is_rejected(fixture):
    root, body, manager, calls = fixture
    body.previous_motion = svi_video.MediaInput.model_validate(
        motion(root, profile_identity(runtime(), "b" * 64))
    )
    with pytest.raises(ValueError, match="profile changed"):
        svi_video.start_video(manager, body)
    assert not calls and not (root / "runs").exists()


@pytest.mark.parametrize("extra", [{"argv": ["sh"]}, {"steps": 4}, {"width": 512}, {"seed": True}])
def test_clients_cannot_choose_a_graph_command_or_unqualified_recipe(fixture, extra):
    values = fixture[1].model_dump(mode="json")
    values.update(extra)
    with pytest.raises(ValidationError):
        svi_video.SviRequest.model_validate(values)


def test_actual_api_remains_unavailable_without_qualification(fixture, monkeypatch):
    root, body, manager, calls = fixture
    from ai_station_runner import app as native

    monkeypatch.setattr(native, "manager", lambda: manager)
    monkeypatch.setattr(svi_video, "capabilities", capabilities_original)
    monkeypatch.setattr(svi_environment, "QUALIFIED", False)
    client = TestClient(native.app)
    assert client.get("/v1/video/svi/capabilities").json()["available"] is False
    result = client.post("/v1/runs/svi", json=body.model_dump(mode="json"))
    assert result.status_code == 409 and "qualified" in result.json()["detail"]
    assert not calls and not (root / "runs").exists()


capabilities_original = svi_video.capabilities


def test_motion_profile_binds_the_anchor_and_opaque_engine_without_per_window_seed():
    observation = runtime()
    first = profile_identity(observation, "b" * 64)
    assert first == profile_identity(observation, "b" * 64)
    assert first != profile_identity(observation, "c" * 64)
    assert first != profile_identity({**observation, "environment_id": "d" * 64}, "b" * 64)
    with pytest.raises(ValueError):
        profile_identity({**observation, "profile": "wan22-5b-linux-x86-64-python312-v1"}, "b" * 64)


def test_fake_engine_reattaches_same_native_identity_and_cancel_escalates_only_owned_group(
    fixture, monkeypatch
):
    """Real OS ownership/Stop with a synthetic executable, no model or GPU."""
    from ai_station_runner.processes import ProcessManager

    root, body, _, _ = fixture
    binary = root / "owned/venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!" + sys.executable + "\nimport signal,time\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\nprint('fake-engine-ready',flush=True)\n"
        "while True:time.sleep(.1)\n"
    )
    binary.chmod(0o700)
    monkeypatch.setattr(svi_video, "scope_prefix", lambda *_: [])
    manager = ProcessManager(root, grace_seconds=0.05)
    recovered = None
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        started = svi_video.start_video(manager, body)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = manager.inspect(str(body.run_id))
            if "fake-engine-ready" in result["stdout"]:
                break
            time.sleep(0.01)
        assert "fake-engine-ready" in result["stdout"]
        recovered = ProcessManager(root, grace_seconds=0.05)
        attached = recovered.inspect(str(body.run_id))
        assert attached["alive"]
        for key in ("pid", "process_group_id", "start_ticks", "boot_id", "deadline_at", "executor"):
            assert attached[key] == started[key]
        assert recovered.cancel(str(body.run_id))["status"] == "canceled"
        assert unrelated.poll() is None
    finally:
        if recovered:
            recovered.shutdown()
        manager.shutdown()
        unrelated.terminate()
        unrelated.wait(timeout=3)
