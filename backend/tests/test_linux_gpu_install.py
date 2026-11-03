"""Normal tests never run a privileged command or change host configuration."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import linux_gpu_install as gpu
import pytest
import windows_gpu_install as common


@pytest.fixture
def setup(tmp_path, monkeypatch):
    app, store, config = tmp_path / "app", tmp_path / "store", tmp_path / "etc/docker/daemon.json"
    (app / "windows-gpu").mkdir(parents=True)
    config.parent.mkdir(parents=True)
    for path in (app, app / "windows-gpu", config.parent, config.parent.parent):
        path.chmod(0o755)
    config.write_text(json.dumps({"log-driver": "local", "live-restore": False}))
    config.chmod(0o644)
    monkeypatch.setattr(gpu, "APP", app)
    monkeypatch.setattr(gpu, "STORE", store)
    monkeypatch.setattr(gpu, "CONFIG", config)
    monkeypatch.setattr(gpu, "identity", lambda: 1000)
    monkeypatch.setattr(gpu, "daemon", lambda: "system-daemon-original")
    monkeypatch.setattr(gpu, "existing_tools", lambda: False)
    original_trust = common.trusted

    def trust(path, **kwargs):
        if path.is_relative_to(tmp_path):
            return original_trust(path, uid=os.getuid(), **kwargs)
        assert path in tmp_path.parents
        return path.lstat()

    monkeypatch.setattr(common, "trusted", trust)
    monkeypatch.setattr(gpu, "trusted", trust)
    state = SimpleNamespace(installed={}, calls=[], failure=None, edit=False)

    def run(*argv, **kwargs):
        state.calls.append(argv)
        if argv[0] == "/usr/bin/dpkg-query":
            name = argv[-1]
            if name not in state.installed:
                raise subprocess.CalledProcessError(1, argv)
            return " ".join(state.installed[name])
        if argv[:2] == ("/usr/bin/dpkg", "--install"):
            assert kwargs == {"timeout": 300}
            assert argv[2:] == tuple(
                str(app / "windows-gpu" / p["filename"]) for p in gpu.bundle.metadata()["packages"]
            )
            for name, *_ in gpu.bundle.PACKAGES:
                state.installed[name] = ("installed", gpu.bundle.VERSION)
                if state.failure == "partial":
                    raise subprocess.CalledProcessError(1, argv)
            if state.edit:
                config.write_text('{"administrator_changed":true}')
            return ""
        if argv[:2] == ("/usr/bin/dockerd", "--validate"):
            assert json.loads(Path(argv[-1]).read_text())["runtimes"]["nvidia"] == gpu.RUNTIME
            if state.failure == "validation":
                raise subprocess.CalledProcessError(1, argv)
            return "configuration OK"
        pytest.fail(f"Unexpected privileged command: {argv}")

    monkeypatch.setattr(gpu, "run", run)
    return SimpleNamespace(app=app, store=store, config=config, state=state)


def test_fixed_packages_preserve_settings_without_restarting_anything(setup):
    original = setup.config.read_bytes()
    result = gpu.install()
    assert result == {"status": "prepared", "restart_required": True, "gpu_ready": False}
    value = json.loads(setup.config.read_text())
    assert value["log-driver"] == "local" and value["live-restore"] is False
    assert "default-runtime" not in value and value["runtimes"] == {"nvidia": gpu.RUNTIME}
    assert (setup.store / "original-daemon.json").read_bytes() == original
    assert (setup.store / "original-daemon.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((setup.store / "receipt.json").read_text())["phase"] == "prepared"
    assert len([c for c in setup.state.calls if c[0] == "/usr/bin/dpkg"]) == 1
    assert not any(c[0].endswith(("systemctl", "docker", "usermod")) for c in setup.state.calls)


def test_lost_success_acknowledgement_inspects_without_reinstalling(setup):
    gpu.install()
    setup.state.calls.clear()
    assert gpu.install()["restart_required"]
    assert all(c[0] == "/usr/bin/dpkg-query" for c in setup.state.calls)


def test_partial_owned_package_transaction_can_resume_after_inspection(setup):
    original = setup.config.read_bytes()
    setup.state.failure = "partial"
    with pytest.raises(subprocess.CalledProcessError):
        gpu.install()
    assert setup.config.read_bytes() == original
    assert json.loads((setup.store / "receipt.json").read_text())["phase"] == "installing"
    setup.state.failure = None
    assert gpu.install()["status"] == "prepared"


@pytest.mark.parametrize("change", ["config", "package", "daemon", "backup", "receipt-link"])
def test_changed_completed_operation_refuses_before_any_install(setup, monkeypatch, change):
    gpu.install()
    if change == "config":
        setup.config.write_text('{"administrator_changed":true}')
    elif change == "package":
        setup.state.installed[gpu.bundle.PACKAGES[0][0]] = ("installed", "99.0")
    elif change == "daemon":
        monkeypatch.setattr(gpu, "daemon", lambda: "different-system-daemon")
    elif change == "backup":
        (setup.store / "original-daemon.json").write_text("changed")
    else:
        path = setup.store / "receipt.json"
        original = path.with_name("retained-receipt.json")
        path.rename(original)
        path.symlink_to(original)
    setup.state.calls.clear()
    with pytest.raises((ValueError, OSError)):
        gpu.install()
    assert not any(c[0] == "/usr/bin/dpkg" for c in setup.state.calls)


@pytest.mark.parametrize("kind", ["validation", "concurrent-edit"])
def test_failure_never_replaces_original_or_concurrent_administrator_config(setup, kind):
    original = setup.config.read_bytes()
    if kind == "validation":
        setup.state.failure = "validation"
    else:
        setup.state.edit = True
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        gpu.install()
    assert setup.config.read_bytes() == (
        original if kind == "validation" else b'{"administrator_changed":true}'
    )
    assert (setup.store / "original-daemon.json").read_bytes() == original


def test_existing_unowned_toolkit_is_never_upgraded_or_reconfigured(setup):
    setup.state.installed[gpu.bundle.PACKAGES[0][0]] = ("installed", gpu.bundle.VERSION)
    original = setup.config.read_bytes()
    with pytest.raises(ValueError, match="Existing graphics tools"):
        gpu.install()
    assert setup.config.read_bytes() == original
    assert not (setup.store / "receipt.json").exists()


@pytest.mark.parametrize("mode", ["symlink", "hardlink", "shared"])
def test_unsafe_docker_config_is_rejected_before_package_commands(setup, mode):
    path = setup.config
    if mode == "symlink":
        original = path.with_name("original.json")
        path.rename(original)
        path.symlink_to(original)
    elif mode == "hardlink":
        os.link(path, path.with_name("second.json"))
    else:
        path.chmod(0o666)
    with pytest.raises(ValueError):
        gpu.install()
    assert not setup.state.calls


def test_custom_runtime_is_preserved(setup):
    setup.config.write_text('{"default-runtime":"custom"}')
    with pytest.raises(ValueError, match="custom Docker"):
        gpu.install()
    assert not setup.state.calls


def test_fresh_default_config_and_missing_directory_are_supported(setup):
    setup.config.unlink()
    setup.config.parent.rmdir()
    assert gpu.install()["status"] == "prepared"
    assert not (setup.store / "original-daemon.json").exists()
    assert json.loads(setup.config.read_text()) == {"runtimes": {"nvidia": gpu.RUNTIME}}


@pytest.mark.parametrize(
    "uid,args,invoking",
    [
        (1000, ["helper"], "1000"),
        (0, ["helper", "--command"], "1000"),
        (0, ["helper"], "0"),
        (0, ["helper"], "../1000"),
    ],
)
def test_entry_requires_privileged_fixed_action_and_real_invoking_uid(monkeypatch, uid, args, invoking):
    monkeypatch.setattr(gpu.os, "getuid", lambda: uid)
    monkeypatch.setattr(gpu.os, "geteuid", lambda: uid)
    monkeypatch.setattr(gpu.sys, "argv", args)
    monkeypatch.setenv("PKEXEC_UID", invoking)
    monkeypatch.setattr(gpu, "run", lambda *a, **k: pytest.fail("No commands before admission"))
    with pytest.raises(ValueError):
        gpu.identity()
