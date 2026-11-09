from unittest.mock import Mock

import desktop_auto_update as module
import desktop_versions as versions
import pytest
from app.db import control_session_factory
from app.models import Run
from app.station_update_gate import take
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_desktop_linux_update import PACKAGE, bundle
from test_desktop_update_authority import installation
from test_station_update_gate import updating


def prepared(accounts, tmp_path, monkeypatch):
    identity, claim = updating(accounts)
    root = installation(tmp_path)
    installed = tmp_path / "installed"
    value = bundle(installed, PACKAGE | {"version": "0.4.0", "release_version": "0.4.0"})
    owner = module.DesktopUpdates(root, installed, value)
    spawn = Mock()
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    with control_session_factory()() as session:
        coordinates = dict(session.get(Run, identity).parameters)
    message = {"action": "updates.prepare", "run_id": identity, "request": coordinates}
    assert owner.handle(message)["phase"] == "queued"
    return root, owner, identity, claim, message, spawn


def test_identical_native_preparation_reuses_journal_without_dispatching_twice(
    accounts, tmp_path, monkeypatch
):
    root, owner, identity, _, message, spawn = prepared(accounts, tmp_path, monkeypatch)
    assert owner.handle(message)["phase"] == "queued"
    assert spawn.call_count == 1
    assert (module.folder(root, identity) / "request.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        owner.handle({**message, "request": {**message["request"], "fingerprint": "f" * 64}})
    assert spawn.call_count == 1


@pytest.mark.parametrize("failure", [None, "download", "activation", "cancel"])
def test_owned_helper_stages_preserves_exact_consent_and_never_replays_installation(
    accounts, tmp_path, monkeypatch, failure
):
    root, owner, identity, claim, message, spawn = prepared(accounts, tmp_path, monkeypatch)
    installed = tmp_path / "target"
    target = bundle(
        installed,
        PACKAGE
        | {
            "bundle_id": "d" * 64,
            "image_id": "sha256:" + "e" * 64,
            "image_tag": "ai-station:desktop-" + "d" * 16,
            "source_epoch": PACKAGE["source_epoch"] + 1,
        },
    )
    calls = []

    def download(*args, **kwargs):
        calls.append("download")
        if failure == "download":
            raise ValueError("Synthetic corrupt download")
        if failure == "cancel":
            with control_session_factory()() as session:
                session.get(Run, identity).status = "cancel_requested"
                session.commit()
        kwargs["check"](True)
        return tmp_path / "package.deb", {"version": "0.5.0"}

    def sleeping(_seconds):
        take(identity, claim)
        assert owner.handle({"action": "updates.apply", "run_id": identity})["phase"] == "apply_requested"

    def apply(app_root, retained, value, run_id, *, consent, engine=None):
        assert (app_root, retained, value, run_id) == (root, installed, target, identity)
        assert consent(versions.package_identity(owner.value), versions.package_identity(target)) is True
        calls.append("activate")
        if failure == "activation":
            raise RuntimeError("Synthetic interruption after consent")
        previous = versions.load(root)
        core = root / "image-upgrades"
        core.mkdir(mode=0o700)
        core /= identity
        core.mkdir(mode=0o700)
        saved = module.request(root, identity)
        module.write(
            core / "request.json",
            {
                "operation_id": identity,
                "previous": saved["previous"],
                "target": versions.package_identity(target),
                "namespace_sha256": saved["namespace_sha256"],
                "engine": list(engine.identity),
            },
        )
        module.write(
            core / "state.json",
            {
                "current": None,
                "final": {
                    "operation_id": identity,
                    "phase": "applied",
                    "schema_before": "0045",
                    "schema_after": "0045",
                    "backup_relative": f"desktop-upgrades/{identity}/original.sqlite",
                    "backup_verified": True,
                },
            },
        )
        versions.save(root, previous | {"package": versions.package_identity(target), "phase": "starting"})
        return True

    monkeypatch.setattr(module, "download", download)
    monkeypatch.setattr(module.linux, "retain_package", lambda *args, **kwargs: (installed, target))
    monkeypatch.setattr(module.linux, "apply", apply)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module.linux,
        "attestation",
        lambda *args: (
            SimpleNamespace(identity=("/usr/bin/docker", "unix:///run/docker.sock")),
            "owned-daemon",
        ),
    )
    monkeypatch.setattr(module.time, "sleep", sleeping)
    if failure in {"download", "activation"}:
        with pytest.raises((ValueError, RuntimeError)):
            module.execute(root, identity)
    else:
        module.execute(root, identity)
    result = owner.inspect(identity)
    assert (
        result["phase"]
        == {None: "applied", "download": "failed", "activation": "inspection_required", "cancel": "canceled"}[
            failure
        ]
    )
    assert calls.count("activate") == (1 if failure in {None, "activation"} else 0)
    assert spawn.call_count == (2 if failure is None else 1)
    # Starting the same helper again only inspects a retained non-queued stage.
    before = list(calls)
    module.execute(root, identity)
    assert calls == before
    if failure is None:
        module.linux.ready(root, target, root / "desktop.env", "e" * 32)
        from desktop_update_recovery import MARKER, acknowledge_ready

        assert acknowledge_ready(root, target)
        assert not (root / MARKER).exists()
        assert not acknowledge_ready(root, target)
        new_owner = module.DesktopUpdates(root, installed, target)
        assert new_owner.inspect(identity)["phase"] == "succeeded"
        assert result["request"] == message["request"]


def test_native_apply_requires_idle_gate_even_after_verified_preparation(accounts, tmp_path, monkeypatch):
    root, owner, identity, _, _, _ = prepared(accounts, tmp_path, monkeypatch)
    module.publish(root, identity, "ready")
    with pytest.raises(ValueError, match="idle dispatch gate"):
        owner.handle({"action": "updates.apply", "run_id": identity})
    assert owner.inspect(identity)["phase"] == "ready"


@pytest.mark.parametrize("activation_started", [False, True])
def test_lost_helper_is_not_replayed_or_left_permanently_preparing(
    accounts, tmp_path, monkeypatch, activation_started
):
    root, owner, identity, _, _, spawn = prepared(accounts, tmp_path, monkeypatch)
    module.publish(root, identity, "applying" if activation_started else "downloading", helper_started_at=0)
    result = owner.inspect(identity)
    assert result["phase"] == ("inspection_required" if activation_started else "failed")
    assert result["error"] and spawn.call_count == 1


@pytest.mark.parametrize("entry", ["desktop_auto_update.py", "desktop_windows_updates.py"])
def test_isolated_native_helper_bootstraps_its_verified_siblings_without_pythonpath(tmp_path, entry):
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2]
    # Only the runner dependency is supplied from this checkout; deliberately do
    # not supply scripts/. The entry point must restore its own sibling imports.
    code = (
        "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
        "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(source / "host-runner"),
            str(source / "scripts" / entry),
            "--help",
        ],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path / "untrusted")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--run-id" in result.stdout and "ModuleNotFoundError" not in result.stderr
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before  # Keep the existing autouse test database untouched.
