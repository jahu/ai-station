"""Disposable files/fake owned-guest commands; never install on the development OS."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import windows_gpu_install as gpu


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    app, store, config = tmp_path / "app", tmp_path / "gpu", tmp_path / "etc/docker/daemon.json"
    app.mkdir()
    config.parent.mkdir(parents=True)
    for path in (app, config.parent, config.parent.parent):
        path.chmod(0o755)
    config.write_text(json.dumps({"default-runtime": "runc", "log-driver": "json-file"}))
    config.chmod(0o644)
    (app / "windows-gpu").mkdir()
    monkeypatch.setattr(gpu, "APP", app)
    monkeypatch.setattr(gpu, "STORE", store)
    monkeypatch.setattr(gpu, "CONFIG", config)
    monkeypatch.setattr(gpu, "assert_guest", lambda *args, **kwargs: None)
    trusted = gpu.trusted

    def temporary_trust(path, **kwargs):
        if path.is_relative_to(tmp_path):
            return trusted(path, uid=os.getuid(), **kwargs)
        assert path in tmp_path.parents
        return path.lstat()  # Test sandbox ancestors only, never a production exemption.

    monkeypatch.setattr(gpu, "trusted", temporary_trust)
    state = {
        "packages": False,
        "live_restore": False,
        "runtime": False,
        "restarts": 0,
        "pid": 123,
        "failure": None,
        "calls": [],
        "change_after_reload": False,
        "change_after_restart": False,
    }

    def run(*argv, **kwargs):
        state["calls"].append(argv)
        if argv[:2] == ("/usr/bin/dpkg-query", "--show"):
            if not state["packages"]:
                raise subprocess.CalledProcessError(1, argv)
            return "\n".join(f"{name} installed {gpu.bundle.VERSION}" for name, *_ in gpu.bundle.PACKAGES)
        if argv[:2] == ("/usr/bin/dpkg", "--install"):
            assert argv[2:] == tuple(
                str(app / "windows-gpu" / p["filename"]) for p in gpu.bundle.metadata()["packages"]
            )
            assert kwargs["timeout"] == 300
            if state["failure"] == "install":
                raise KeyboardInterrupt()
            state["packages"] = True
            return ""
        if argv[:2] == ("/usr/bin/dockerd", "--validate"):
            assert json.loads(Path(argv[-1]).read_text())["runtimes"]["nvidia"] == gpu.RUNTIME
            return "configuration OK"
        if argv[:2] == ("/usr/bin/systemctl", "show"):
            return "process"
        if argv[:2] == ("/usr/bin/systemctl", "reload"):
            state["live_restore"] = True
            state["runtime"] = True
            if state["change_after_reload"]:
                state["pid"] += 1
            return ""
        if argv[:2] == ("/usr/bin/systemctl", "restart"):
            assert state["live_restore"]
            if state["failure"] == "restart":
                raise subprocess.CalledProcessError(1, argv)
            state["restarts"] += 1
            if state["change_after_restart"]:
                state["pid"] += 1
            return ""
        assert argv[:5] == (
            "/usr/bin/docker",
            "--host",
            "unix:///var/run/docker.sock",
            "--config",
            str(store / "client"),
        )
        args = argv[5:]
        if args == ("ps", "--quiet", "--no-trunc"):
            return "a" * 64
        if args == ("inspect", "--format", "{{json .State}}", "a" * 64):
            return json.dumps({"Running": True, "Pid": state["pid"], "StartedAt": "2026-11-01T00:00:00Z"})
        if args == ("info", "--format", "{{json .LiveRestoreEnabled}}"):
            return json.dumps(state["live_restore"])
        if args == ("info", "--format", "{{json .Runtimes}}"):
            return json.dumps({"nvidia": {}} if state["runtime"] else {})
        raise AssertionError(argv)

    monkeypatch.setattr(gpu, "run", run)
    return app, store, config, state


def test_offline_activation_retains_default_runtime_and_running_container_identity(fixture):
    _, store, config, state = fixture
    result = gpu.install("AIStation-" + "b" * 32)
    value = json.loads(config.read_text())
    assert value["default-runtime"] == "runc" and value["log-driver"] == "json-file"
    assert value["runtimes"]["nvidia"] == gpu.RUNTIME and value["live-restore"] is True
    receipt = json.loads((store / "receipt.json").read_text())
    assert receipt["phase"] == "complete" and receipt["running_before"]["a" * 64]["pid"] == 123
    assert state["pid"] == 123 and state["restarts"] == 1
    assert result["gpu_inference_verified"] is False
    assert json.loads((store / "original-daemon.json").read_text())["default-runtime"] == "runc"


def test_repeated_activation_checks_receipt_without_reinstall_or_restart(fixture):
    _, _, _, state = fixture
    gpu.install("AIStation-" + "b" * 32)
    state["calls"].clear()
    gpu.install("AIStation-" + "b" * 32)
    assert state["restarts"] == 1
    assert not any(c[:2] == ("/usr/bin/dpkg", "--install") for c in state["calls"])


def test_first_import_installs_before_daemon_start_without_contacting_it(fixture):
    _, store, _, state = fixture
    gpu.install(image_build=True)
    assert json.loads((store / "receipt.json").read_text())["phase"] == "image_prepared"
    assert state["restarts"] == 0
    assert not any(c[0] in {"/usr/bin/docker", "/usr/bin/systemctl"} for c in state["calls"])
    # Later app updates adopt the already-started prepared image without restart.
    state["live_restore"] = state["runtime"] = True
    gpu.install("AIStation-" + "b" * 32)
    assert state["restarts"] == 0


@pytest.mark.parametrize("where", ["install", "restart"])
def test_interrupted_activation_remains_pending_and_retries_without_losing_container(fixture, where):
    _, store, _, state = fixture
    state["failure"] = where
    with pytest.raises((KeyboardInterrupt, subprocess.CalledProcessError)):
        gpu.install("AIStation-" + "b" * 32)
    assert json.loads((store / "receipt.json").read_text())["phase"] == "installing"
    assert state["pid"] == 123
    state["failure"] = None
    gpu.install("AIStation-" + "b" * 32)
    assert json.loads((store / "receipt.json").read_text())["phase"] == "complete"


@pytest.mark.parametrize("when", ["reload", "restart"])
def test_changed_container_process_is_never_reported_preserved(fixture, when):
    _, store, _, state = fixture
    state[f"change_after_{when}"] = True
    with pytest.raises(ValueError, match="process|identities"):
        gpu.install("AIStation-" + "b" * 32)
    assert json.loads((store / "receipt.json").read_text())["phase"] == "installing"
    if when == "reload":
        assert state["restarts"] == 0
    calls = len(state["calls"])
    with pytest.raises(ValueError, match="identities"):
        gpu.install("AIStation-" + "b" * 32)
    assert not any(
        c[:2] in {("/usr/bin/dpkg", "--install"), ("/usr/bin/systemctl", "restart")}
        for c in state["calls"][calls:]
    )


def test_conflicting_existing_runtime_is_preserved_before_any_installation(fixture):
    _, store, config, state = fixture
    original = json.dumps({"runtimes": {"nvidia": {"path": "/custom/runtime"}}})
    config.write_text(original)
    with pytest.raises(ValueError, match="different NVIDIA"):
        gpu.install("AIStation-" + "b" * 32)
    assert config.read_text() == original and not state["calls"]
    assert not (store / "receipt.json").exists()


def test_symlinked_daemon_configuration_cannot_read_or_overwrite_another_file(fixture, tmp_path):
    _, _, config, state = fixture
    outside = tmp_path / "keep"
    outside.write_text("private data")
    config.unlink()
    config.symlink_to(outside)
    with pytest.raises(ValueError):
        gpu.install("AIStation-" + "b" * 32)
    assert outside.read_text() == "private data" and not state["calls"]


def test_normal_development_host_cannot_run_guest_activation(tmp_path, monkeypatch):
    execute = []
    monkeypatch.setattr(gpu, "run", lambda *args, **kwargs: execute.append(args))
    with pytest.raises(ValueError, match="guest installer"):
        gpu.install("AIStation-" + "b" * 32)
    assert not execute


def test_even_root_cannot_activate_on_a_native_linux_host(monkeypatch):
    monkeypatch.setattr(gpu.os, "getuid", lambda: 0)
    monkeypatch.setattr(gpu.os, "geteuid", lambda: 0)
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/sys/kernel/osrelease":
            return "6.8.0-generic"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="owned WSL"):
        gpu.install("AIStation-" + "b" * 32)


def test_timed_out_owned_subcommand_is_reaped_without_touching_another_process(monkeypatch):
    unrelated = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time;time.sleep(15)"], start_new_session=True
    )
    create = subprocess.Popen
    owned = []

    def launch(*args, **kwargs):
        child = create(*args, **kwargs)
        owned.append(child)
        return child

    monkeypatch.setattr(gpu.subprocess, "Popen", launch)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            gpu.run(
                sys.executable,
                "-I",
                "-c",
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(15)",
                timeout=0.3,
            )
        assert owned and all(child.poll() is not None for child in owned)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_different_pending_recipe_cannot_be_adopted(fixture):
    _, store, _, state = fixture
    store.mkdir(mode=0o700)
    (store / "receipt.json").write_text(json.dumps({"recipe": "another", "phase": "installing"}))
    (store / "receipt.json").chmod(0o600)
    with pytest.raises(ValueError, match="different"):
        gpu.install("AIStation-" + "b" * 32)
    assert not state["calls"]
