"""Owned preflight child/receipt checks with neutral processes, not Mac Docker QA."""

import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import desktop_bridge as bridge
import pytest

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def setup(tmp_path):
    installed = tmp_path / "installed"
    (installed / "python/bin").mkdir(parents=True)
    (installed / "python/bin/python3").symlink_to(sys.executable)
    (installed / "scripts").mkdir()
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    data = state / "data"
    data.mkdir(mode=0o700)
    (data / "keep.txt").write_text("original user data")
    config = state / "desktop.env"
    config.write_text("AI_STATION_DATA_HOST_PATH=" + json.dumps(str(data)) + "\n")
    engine = SimpleNamespace(
        identity=("/fixed/docker", "unix:///fixed.sock"), environment={"PATH": os.defpath}
    )
    control = SimpleNamespace(stop_requested=threading.Event())
    return SimpleNamespace(
        installed=installed,
        state=state,
        data=data,
        config=config,
        engine=engine,
        control=control,
        value={"image_id": IMAGE},
    )


def child(setup, mode="pass", changes=None):
    # Real isolated interpreter and Popen handle, with a neutral proof producer.
    (setup.installed / "scripts/macos_transport_probe.py").write_text(
        "import argparse,json,os,signal,sys,time\nfrom pathlib import Path\n"
        "os.umask(0o077)\np=argparse.ArgumentParser()\n"
        "for k in ('output','data-directory','packaged-image','expected-cli','expected-endpoint'):p.add_argument('--'+k,required=True)\n"
        "a=p.parse_args();out=Path(a.output)\n"
        f"mode={mode!r}\n"
        "if mode=='before-dispatch':time.sleep(30)\n"
        "out.mkdir(mode=0o700)\n"
        "result={'probe_kind':'packaged_application','platform':'Darwin','image':a.packaged_image,'image_id':a.packaged_image,"
        "'chosen_data_directory':a.data_directory,'cleanup_complete':True,'transport_passed':True,'macos_installer_qualified':False,"
        "'checks':{'native_peer_uid':os.geteuid(),'socket_rebind':True,'client_restart':True,'sqlite_wal':True,"
        "'concurrent_writer_lock':True,'chosen_data_filesystem':True}}\n"
        f"result.update({changes or {}!r})\n"
        "def publish():\n (out/'result.json').write_text(json.dumps(result))\n"
        "def stop(*args):\n result.update(transport_passed=False);publish();sys.exit(1)\n"
        "if mode=='wait':\n signal.signal(signal.SIGTERM,stop);(out/'started').touch();time.sleep(30)\n"
        "if mode=='fail-clean':result.update(transport_passed=False)\n"
        "if mode=='fail-uncertain':result.update(transport_passed=False,cleanup_complete=False)\n"
        "publish()\n"
    )


def check(setup):
    with (setup.state / "desktop.log").open("a") as log:
        return bridge.check(
            setup.installed, setup.state, setup.config, setup.value, setup.engine, log, setup.control
        )


def test_packaged_child_verifies_selected_data_and_removes_only_pending_marker(setup):
    child(setup)
    assert check(setup)
    root = setup.state / "bridge-checks"
    assert not (root / "pending.json").exists()
    proofs = list(root.glob("*/result.json"))
    assert len(proofs) == 1 and proofs[0].stat().st_mode & 0o777 == 0o600
    assert json.loads(proofs[0].read_text())["image_id"] == IMAGE
    assert (setup.data / "keep.txt").read_text() == "original user data"


@pytest.mark.parametrize("mode", ["wait", "before-dispatch"])
def test_stop_waits_for_only_the_owned_child_and_preserves_original_data(setup, mode):
    child(setup, mode)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    result, errors = [], []

    def run():
        try:
            result.append(check(setup))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        marker = setup.state / "bridge-checks/pending.json"
        while time.monotonic() < deadline:
            if marker.exists() and (mode == "before-dispatch" or list(marker.parent.glob("*/started"))):
                break
            time.sleep(0.01)
        assert marker.exists()
        setup.control.stop_requested.set()
        thread.join(timeout=10)
        assert not thread.is_alive() and not errors and result == [False]
        assert not marker.exists() and unrelated.poll() is None
        assert (setup.data / "keep.txt").read_text() == "original user data"
    finally:
        setup.control.stop_requested.set()
        thread.join(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_failed_but_confirmed_clean_probe_can_be_retried(setup):
    child(setup, "fail-clean")
    with pytest.raises(RuntimeError, match="no station was started"):
        check(setup)
    assert not (setup.state / "bridge-checks/pending.json").exists()
    child(setup)
    assert check(setup)


def test_timeout_reports_failure_instead_of_silently_closing_setup(setup, monkeypatch):
    child(setup, "wait")
    monkeypatch.setattr(bridge, "STARTUP_TIMEOUT", 0.15)
    with pytest.raises(RuntimeError, match="timed out"):
        check(setup)
    assert not (setup.state / "bridge-checks/pending.json").exists()


def test_uncertain_probe_is_not_replayed_and_its_files_are_preserved(setup, monkeypatch):
    child(setup, "fail-uncertain")
    with pytest.raises(ValueError, match="cleanup was not confirmed"):
        check(setup)
    marker = setup.state / "bridge-checks/pending.json"
    before = marker.read_bytes()
    monkeypatch.setattr(bridge.subprocess, "Popen", lambda *a, **k: pytest.fail("Uncertain probe replayed"))
    with pytest.raises(ValueError, match="cleanup was not confirmed"):
        check(setup)
    assert marker.read_bytes() == before


def test_completed_private_receipt_recovers_after_parent_exit_without_replay(setup, monkeypatch):
    child(setup)
    assert check(setup)
    root = setup.state / "bridge-checks"
    attempt = next(root.iterdir()).name
    request = {"schema": 1, "attempt": attempt, "image": IMAGE, "data_directory": str(setup.data)}
    bridge.receipt(root / "pending.json", request)
    setup.control.stop_requested.set()
    monkeypatch.setattr(
        bridge.subprocess, "Popen", lambda *a, **k: pytest.fail("Stop dispatched a new probe")
    )
    assert check(setup) is False
    assert not (root / "pending.json").exists()
    assert (root / attempt / "result.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"image": "sha256:" + "b" * 64},
        {"chosen_data_directory": "/other"},
        {"platform": "Linux"},
        {"probe_kind": "developer_fixture"},
        {"macos_installer_qualified": True},
        {"checks": {"sqlite_wal": True}},
        {"image_id": "sha256:" + "b" * 64},
    ],
)
def test_foreign_or_incomplete_receipt_cannot_admit_startup(setup, changes):
    child(setup, changes=changes)
    with pytest.raises(ValueError):
        check(setup)
    assert (setup.state / "bridge-checks/pending.json").exists()


def test_failed_child_creation_has_no_pending_operation_to_replay(setup, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError("neutral child creation failure")

    monkeypatch.setattr(bridge.subprocess, "Popen", failed)
    with pytest.raises(OSError):
        check(setup)
    assert not (setup.state / "bridge-checks/pending.json").exists()


def test_unsafe_proof_directory_does_not_touch_external_files(setup, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (setup.state / "bridge-checks").symlink_to(outside)
    with pytest.raises(ValueError, match="private owned canonical"):
        check(setup)
    assert not list(outside.iterdir())
