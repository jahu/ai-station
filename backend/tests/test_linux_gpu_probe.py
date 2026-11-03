"""Fixed native probe ownership and uncertain-operation recovery; no real Docker."""

import copy
import json
import subprocess
from types import SimpleNamespace

import linux_gpu_probe as gpu
import pytest

UUIDS = ["GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
IMAGE = "sha256:" + "a" * 64
CID = "c" * 64


@pytest.fixture
def engine(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    state = SimpleNamespace(item=None, calls=[], mode="ok", signals=[])

    def command(engine, *argv, **kwargs):
        state.calls.append(argv)
        action = argv[0]
        if action == "create":
            record = gpu.read_record(tmp_path / "gpu-probe.json")
            state.item = {
                "Id": CID,
                "Name": "/" + record["name"],
                "Image": IMAGE,
                "Config": {
                    "Labels": {"ai-station.native-gpu-probe": record["token"]},
                    "User": record["user"],
                    "Entrypoint": ["/opt/venv/bin/python"],
                    "Cmd": ["-I", "-B", "-c", gpu.QUERY],
                },
                "Mounts": [],
                "HostConfig": {"NetworkMode": "none", "Privileged": False, "ReadonlyRootfs": True},
                "State": {"Running": False},
            }
            assert argv[argv.index("--gpus") + 1] == '"device=' + UUIDS[0] + '"'
            assert "CUDA_VISIBLE_DEVICES=" + UUIDS[0] in argv
            assert "--mount" not in argv and "--volume" not in argv
            if state.mode == "lost-create":
                raise subprocess.TimeoutExpired(argv, 20)
            return SimpleNamespace(returncode=0, stdout=CID, stderr="")
        if action == "inspect":
            return SimpleNamespace(
                returncode=0 if state.item else 1,
                stdout=json.dumps([state.item]),
                stderr="" if state.item else "No such container",
            )
        if action == "start":
            assert argv[-1] == CID
            if state.mode == "timeout":
                state.item["State"]["Running"] = True
                raise subprocess.TimeoutExpired(argv, 30)
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"uuids": UUIDS if state.mode == "ok" else []})
            )
        if action in {"stop", "rm"}:
            assert argv[-1] == CID
            state.signals.append(action)
            if action == "rm":
                state.item = None
            return SimpleNamespace(returncode=0)
        pytest.fail(f"Unexpected native command {argv}")

    monkeypatch.setattr(gpu, "command", command)
    return tmp_path, state


@pytest.mark.parametrize("mode,expected", [("ok", True), ("wrong-device", False)])
def test_probe_checks_actual_compute_devices_and_removes_only_its_container(engine, mode, expected):
    root, state = engine
    state.mode = mode
    assert gpu.probe(root, IMAGE, None, UUIDS) is expected
    assert state.signals == ["rm"]
    assert not (root / "gpu-probe.json").exists()


@pytest.mark.parametrize("mode,signals", [("lost-create", ["rm"]), ("timeout", ["stop", "rm"])])
def test_lost_acknowledgement_and_timeout_reinspect_before_cleanup(engine, mode, signals):
    root, state = engine
    state.mode = mode
    with pytest.raises(subprocess.TimeoutExpired):
        gpu.probe(root, IMAGE, None, UUIDS)
    assert state.signals == signals
    assert state.item is None


@pytest.mark.parametrize(
    "change", ["id", "label", "mount", "image", "command", "user", "network", "privileged", "writable"]
)
def test_changed_inventory_never_signals_a_foreign_container(engine, monkeypatch, change):
    root, state = engine
    original = gpu.cleanup
    monkeypatch.setattr(gpu, "cleanup", lambda *args: None)
    assert gpu.probe(root, IMAGE, None, UUIDS)
    item = copy.deepcopy(state.item)
    if change == "id":
        item["Id"] = "d" * 64
    elif change == "label":
        item["Config"]["Labels"] = {}
    elif change == "mount":
        item["Mounts"] = [{"Source": "/unrelated"}]
    elif change == "image":
        item["Image"] = "sha256:" + "e" * 64
    elif change == "command":
        item["Config"]["Cmd"][-1] = "different"
    elif change == "user":
        item["Config"]["User"] = "0:0"
    elif change == "network":
        item["HostConfig"]["NetworkMode"] = "host"
    elif change == "privileged":
        item["HostConfig"]["Privileged"] = True
    else:
        item["HostConfig"]["ReadonlyRootfs"] = False
    state.item = item
    with pytest.raises(ValueError, match="ownership"):
        original(None, root / "gpu-probe.json")
    assert not state.signals and (root / "gpu-probe.json").exists()


def test_previous_owned_probe_is_recovered_before_creating_another(engine, monkeypatch):
    root, state = engine
    original = gpu.cleanup
    monkeypatch.setattr(gpu, "cleanup", lambda *args: None)
    assert gpu.probe(root, IMAGE, None, UUIDS)
    first_name = state.item["Name"]
    state.item["State"]["Running"] = True
    monkeypatch.setattr(gpu, "cleanup", original)
    assert gpu.probe(root, IMAGE, None, UUIDS)
    assert state.signals == ["stop", "rm", "rm"]
    names = [c[4] for c in state.calls if c[0] == "create"]
    assert names[0] != names[1] and "/" + names[0] == first_name


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "shared"])
def test_probe_receipt_is_private_and_cannot_be_redirected(engine, monkeypatch, kind):
    root, state = engine
    original = gpu.cleanup
    monkeypatch.setattr(gpu, "cleanup", lambda *args: None)
    assert gpu.probe(root, IMAGE, None, UUIDS)
    path = root / "gpu-probe.json"
    if kind == "symlink":
        path.rename(root / "original")
        path.symlink_to(root / "original")
    elif kind == "hardlink":
        import os

        os.link(path, root / "second")
    else:
        path.chmod(0o644)
    with pytest.raises((ValueError, OSError)):
        original(None, path)
    assert not state.signals
