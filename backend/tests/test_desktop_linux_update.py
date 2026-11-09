import copy
import fcntl
import hashlib
import json
import subprocess
from unittest.mock import Mock

import desktop
import desktop_linux_update as update
import desktop_versions as versions
import pytest
from test_desktop_versions import installation as installation

PACKAGE = {
    "schema": 1,
    "platform": "Linux",
    "architecture": "x86_64",
    "version": "0.5.0",
    "release_version": "0.5.0",
    "source_dirty": False,
    "desktop_protocol": desktop.DESKTOP_PROTOCOL,
    "source_epoch": 1794210000,
    "bundle_id": "a" * 64,
    "image_id": "sha256:" + "b" * 64,
    "image_tag": "ai-station:desktop-" + "a" * 16,
    "files": {},
}
OWNER = "c" * 32


def bundle(path, value=None):
    path.mkdir(parents=True)
    (path / "neutral").write_bytes(b"verified package contents")
    value = copy.deepcopy(value or PACKAGE)
    value["files"] = {"neutral": desktop.digest(path / "neutral")}
    (path / "desktop-manifest.json").write_text(json.dumps(value))
    return value


def deb(tmp_path, value=None):
    root = tmp_path / "debian"
    value = bundle(root / "usr/lib/ai-station", value)
    control = root / "DEBIAN"
    control.mkdir()
    control.chmod(0o755)  # dpkg requires this even under the runner's private umask.
    (control / "control").write_text(
        "Package: ai-station\nVersion: 0.5.0\nArchitecture: amd64\nMaintainer: QA\nDescription: synthetic installer fixture\n"
    )
    path = tmp_path / "update.deb"
    subprocess.run(
        ["dpkg-deb", "--build", "--root-owner-group", str(root), str(path)], capture_output=True, check=True
    )
    path.chmod(0o400)
    snapshot = {
        "version": "0.5.0",
        "packages": {
            "linux-amd64": {
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        },
    }
    return path, snapshot, value


def test_verified_debian_is_retained_without_running_scripts_or_touching_data(tmp_path):
    package, snapshot, value = deb(tmp_path)
    root = tmp_path / "desktop"
    root.mkdir(mode=0o700)
    (root / "existing-data").write_bytes(b"keep")
    retained, observed = update.retain_package(root, package, snapshot)
    assert observed == value
    assert retained == root / "releases" / value["bundle_id"]
    assert (retained / "neutral").read_bytes() == b"verified package contents"
    assert (root / "existing-data").read_bytes() == b"keep"
    assert list((root / "update-staging").iterdir()) == []
    assert update.retain_package(root, package, snapshot)[0] == retained


@pytest.mark.parametrize("mutation", ["hash", "version", "platform", "dirty", "protocol"])
def test_changed_or_incompatible_package_never_becomes_active(tmp_path, mutation):
    value = copy.deepcopy(PACKAGE)
    if mutation in {"platform", "dirty", "protocol"}:
        value.update(
            {
                "platform": {"platform": "Darwin"},
                "dirty": {"source_dirty": True},
                "protocol": {"desktop_protocol": 999},
            }[mutation]
        )
    package, snapshot, _ = deb(tmp_path, value)
    if mutation == "hash":
        snapshot["packages"]["linux-amd64"]["sha256"] = "f" * 64
    elif mutation == "version":
        snapshot["version"] = "0.6.0"
    root = tmp_path / "desktop"
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        update.retain_package(root, package, snapshot)
    assert not (root / "releases").exists()
    assert not (root / versions.RECEIPT).exists()


def test_ready_receipt_bootstraps_existing_data_only_after_trusted_start_and_refuses_other_version(
    installation,
):
    root, config, data = installation
    (data / "db").mkdir()
    database = data / "db/ai-station.sqlite"
    database.write_bytes(b"existing pre-updater data")
    update.ready(root, PACKAGE, config, OWNER)
    receipt = versions.load(root)
    assert receipt["phase"] == "ready" and receipt["package"]["version"] == "0.5.0"
    assert database.read_bytes() == b"existing pre-updater data"
    update.ready(root, PACKAGE, config, "d" * 32)
    before = (root / versions.RECEIPT).read_bytes()
    with pytest.raises(ValueError, match="different active version"):
        update.ready(root, PACKAGE | {"bundle_id": "e" * 64}, config, OWNER)
    assert (root / versions.RECEIPT).read_bytes() == before


def test_installed_launcher_follows_verified_active_payload_and_refuses_tampering(installation):
    root, config, _ = installation
    target = root / "releases" / PACKAGE["bundle_id"]
    value = bundle(target)
    update.ready(root, value, config, OWNER)
    old = value | {"bundle_id": "d" * 64, "version": "0.4.0"}
    assert update.active_payload(root, old) == target
    assert update.active_payload(root, value) is None
    (target / "neutral").write_bytes(b"modified")
    with pytest.raises(ValueError, match="changed"):
        update.active_payload(root, old)


def test_normal_linux_configuration_has_the_same_frozen_namespace_as_explicit_runner_socket(
    tmp_path, monkeypatch
):
    root = tmp_path / "desktop"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(desktop.platform, "system", lambda: "Linux")
    monkeypatch.setattr(desktop, "free_port", lambda: 8766)
    config = desktop.configuration(root)
    assert "AI_STATION_RUNNER_SOCKET" not in config.read_text()
    data, implicit = versions.namespace(config)
    update.ready(root, PACKAGE, config, OWNER)
    config.write_text(config.read_text() + f'AI_STATION_RUNNER_SOCKET="{data}/runtime/runner/runner.sock"\n')
    assert versions.namespace(config) == (data, implicit)
    assert versions.load(root)["namespace_sha256"] == implicit


def test_remote_docker_is_refused_before_any_image_or_signal(monkeypatch):
    monkeypatch.setattr(update.shutil, "which", lambda *args, **kwargs: "/usr/bin/true")
    call = Mock()
    monkeypatch.setattr(update.subprocess, "run", call)
    with pytest.raises(ValueError, match="local Unix"):
        update.local_engine({"DOCKER_HOST": "tcp://remote.example:2375"})
    call.assert_not_called()


@pytest.mark.parametrize("operation", ["--status", "--stop"])
def test_active_version_routing_never_turns_status_or_stop_into_startup(
    installation, tmp_path, monkeypatch, capsys, operation
):
    root, _, _ = installation
    bundle(tmp_path / "system-package")
    monkeypatch.setattr(desktop, "ROOT", tmp_path / "system-package")
    monkeypatch.setattr(desktop, "state_root", lambda: root)
    monkeypatch.setattr(desktop.sys, "argv", ["station", operation])
    monkeypatch.setattr(desktop.signal, "signal", Mock())
    routed = Mock(side_effect=AssertionError("Status/Stop must address the existing owner directly"))
    monkeypatch.setattr(update, "active_payload", routed)
    reply = {"instance_id": "f" * 32, "ready": True, "background": True, "stopping": False}
    control = Mock(return_value=reply)
    monkeypatch.setattr(desktop, "control_request", control)
    with (root / "desktop.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        desktop.main()
    routed.assert_not_called()
    assert json.loads(capsys.readouterr().out)["running"] is True
    assert control.call_count == (2 if operation == "--stop" else 1)
