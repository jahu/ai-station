import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import desktop_auto_update as journal
import desktop_windows_updates as windows
import pytest
from app.db import control_session_factory
from app.models import Run
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_desktop_linux_update import OWNER, PACKAGE, bundle
from test_desktop_update_authority import installation
from test_station_update_gate import updating


def prepared(accounts, tmp_path, monkeypatch, payload=None):
    identity, claim = updating(accounts)
    root = installation(tmp_path)
    installed = tmp_path / "installed"
    current = bundle(installed, PACKAGE | {"version": "0.4.0", "release_version": "0.4.0"})
    monkeypatch.setattr(windows, "guest", lambda: True)  # Isolated fixture; no real WSL or model.
    binding = {"schema": 1, "channel_id": str(uuid4()), "host_manifest_sha256": "b" * 64, "version": "0.4.0"}
    windows.bind(root, current, binding)
    fixture = Path(__file__).resolve().parents[2] / "packaging/windows/tests/fixtures/release-offer.json"
    document = json.loads(fixture.read_text())
    snapshot = document["expected"]
    if payload is not None:
        import hashlib

        from ai_station_runner.station_release_metadata import admit_release

        document["raw"]["assets"][0]["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
        document["raw"]["assets"][0]["size"] = len(payload)
        snapshot = admit_release(document["raw"])
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.parameters = {**run.parameters, "platform": "windows-x64", "fingerprint": snapshot["fingerprint"]}
        parameters = dict(run.parameters)
        session.commit()
    owner = windows.WindowsUpdates(root, installed, current)
    spawn = Mock()
    monkeypatch.setattr(journal.subprocess, "Popen", spawn)
    message = {"action": "updates.prepare", "run_id": identity, "request": parameters}
    assert owner.handle(message)["phase"] == "queued"
    return root, current, identity, claim, owner, snapshot, binding, spawn, message


def test_windows_native_preparation_is_finite_idempotent_and_uses_its_own_helper(
    accounts, tmp_path, monkeypatch
):
    root, _, identity, _, owner, _, _, spawn, message = prepared(accounts, tmp_path, monkeypatch)
    assert owner.handle(message)["phase"] == "queued" and spawn.call_count == 1
    assert spawn.call_args.args[0][2].endswith("/scripts/desktop_windows_updates.py")
    assert journal.request(root, identity)["request"]["platform"] == "windows-x64"
    with pytest.raises(ValueError):
        owner.handle({**message, "command": "powershell"})


@pytest.mark.parametrize("canceled", [False, True])
def test_verified_staging_never_runs_the_windows_installer(accounts, tmp_path, monkeypatch, canceled):
    root, _, identity, _, owner, snapshot, _, spawn, _ = prepared(accounts, tmp_path, monkeypatch)
    calls = []

    def download(*args, **kwargs):
        calls.append("verified-download")
        kwargs["check"]()
        return tmp_path / "fixed-package.exe", snapshot

    import desktop_release_download

    monkeypatch.setattr(desktop_release_download, "download", download)
    if canceled:
        with control_session_factory()() as session:
            session.get(Run, identity).status = "cancel_requested"
            session.commit()
    windows.prepare(root, identity)
    result = owner.inspect(identity)
    assert result["phase"] == ("canceled" if canceled else "ready")
    assert calls == ([] if canceled else ["verified-download"])
    assert spawn.call_count == 1  # Only its preparer, never an EXE or host command.
    if not canceled:
        assert result["target"] == windows.target(snapshot)


@pytest.mark.parametrize("proof_present", [False, True])
def test_native_host_completion_needs_bound_new_guest_readiness(
    accounts, tmp_path, monkeypatch, proof_present
):
    root, current, identity, _, _, snapshot, binding, _, _ = prepared(accounts, tmp_path, monkeypatch)
    target = bundle(
        tmp_path / "new", PACKAGE | {"version": "0.5.1", "release_version": "0.5.1", "bundle_id": "e" * 64}
    )
    windows.bind(root, target, {**binding, "version": "0.5.1", "host_manifest_sha256": "c" * 64})
    stage = {"target": windows.target(snapshot)}
    if proof_present:
        stage["host_completion"] = {
            "channel_id": binding["channel_id"],
            "host_manifest_sha256": "c" * 64,
            "version": "0.5.1",
            "installer_sha256": snapshot["packages"]["windows-x64"]["sha256"],
            "data_preserved": True,
            "backup_available": True,
        }
    journal.publish(root, identity, "applied", **stage)
    owner = windows.WindowsUpdates(root, tmp_path / "new", target)
    assert owner.inspect(identity)["phase"] == "applied"
    windows.ready(root, target, root / "desktop.env", OWNER)
    assert owner.inspect(identity)["phase"] == ("succeeded" if proof_present else "applied")


def test_wrong_or_expired_native_host_binding_does_not_advertise_installed_updates(
    accounts, tmp_path, monkeypatch
):
    root, _, identity, _, owner, _, binding, _, message = prepared(accounts, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="identity changed"):
        windows.bind(root, owner.value, {**binding, "channel_id": str(uuid4())})
    value = journal.read(root / windows.ATTACHMENT)
    journal.write(root / windows.ATTACHMENT, {**value, "updated_at": 0})
    assert owner.handle({"action": "updates.capabilities"})["installed"] is False
    assert owner.handle(message)["phase"] == "queued"  # Existing uncertain dispatch retains its stage.


@pytest.mark.parametrize("variant", ["verified", "changed", "canceled", "symlink"])
def test_native_export_is_bound_to_verified_bytes_and_never_accepts_a_caller_path(
    accounts, tmp_path, monkeypatch, variant
):
    import io

    payload = b"Synthetic Windows publisher byte fixture. Never executed."
    root, current, identity, _, owner, snapshot, binding, spawn, _ = prepared(
        accounts, tmp_path, monkeypatch, payload
    )
    name = snapshot["packages"]["windows-x64"]["name"]
    directory = root / "update-downloads"
    directory.mkdir(mode=0o700)
    package = directory / name
    package.write_bytes(payload)
    package.chmod(0o600)
    journal.publish(root, identity, "ready", target=windows.target(snapshot), package_name=name)
    if variant == "changed":
        package.write_bytes(b"A different package")
    elif variant == "canceled":
        with control_session_factory()() as session:
            session.get(Run, identity).status = "cancel_requested"
            session.commit()
    elif variant == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(payload)
        package.unlink()
        package.symlink_to(outside)
    output = io.BytesIO()
    body = {"channel_id": binding["channel_id"], "run_id": identity}
    if variant != "verified":
        with pytest.raises((ValueError, InterruptedError)):
            windows.export_package(root, current, body, output=output)
        assert not output.getvalue()
    else:
        windows.export_package(root, current, body, output=output)
        header, actual = output.getvalue().split(b"\n", 1)
        assert actual == payload
        assert json.loads(header)["target"] == windows.target(snapshot)
    assert spawn.call_count == 1
    with pytest.raises(ValueError):
        windows.export_package(root, current, {**body, "path": str(package)}, output=io.BytesIO())


def test_native_owner_acknowledgement_is_idempotent_after_guest_readiness(accounts, tmp_path, monkeypatch):
    from app.station_update_gate import take

    root, current, identity, claim, owner, snapshot, binding, spawn, _ = prepared(
        accounts, tmp_path, monkeypatch
    )
    journal.publish(root, identity, "ready", target=windows.target(snapshot))
    take(identity, claim)
    owner.handle({"action": "updates.apply", "run_id": identity})
    body = {
        "channel_id": binding["channel_id"],
        "run_id": identity,
        "fingerprint": snapshot["fingerprint"],
        "phase": "applying",
        "proof": None,
    }
    assert windows.host_result(root, current, body)["phase"] == "applying"
    target = bundle(tmp_path / "new", PACKAGE | {"version": "0.5.1", "release_version": "0.5.1"})
    windows.bind(root, target, {**binding, "version": "0.5.1", "host_manifest_sha256": "c" * 64})
    proof = {
        "version": "0.5.1",
        "host_manifest_sha256": "c" * 64,
        "installer_sha256": snapshot["packages"]["windows-x64"]["sha256"],
        "data_preserved": True,
        "backup_available": True,
    }
    complete = {**body, "phase": "applied", "proof": proof}
    assert windows.host_result(root, target, complete)["phase"] == "applied"
    windows.ready(root, target, root / "desktop.env", OWNER)
    assert windows.host_result(root, target, complete)["phase"] == "succeeded"
    assert not (root / windows.PENDING).exists()
    assert windows.host_result(root, target, complete)["phase"] == "succeeded"
    assert spawn.call_count == 1


def test_privileged_guest_continuation_needs_the_original_latched_idle_operation(
    accounts, tmp_path, monkeypatch
):
    from app.models import User
    from app.station_update_gate import take

    root, current, identity, claim, owner, snapshot, binding, spawn, _ = prepared(
        accounts, tmp_path, monkeypatch
    )
    context = {
        "channel_id": binding["channel_id"],
        "run_id": identity,
        "fingerprint": snapshot["fingerprint"],
    }
    with pytest.raises(ValueError, match="has not started"):
        windows.authorize_guest_update(root, context)
    journal.publish(root, identity, "ready", target=windows.target(snapshot))
    take(identity, claim)
    owner.handle({"action": "updates.apply", "run_id": identity})
    windows.host_result(root, current, {**context, "phase": "applying", "proof": None})
    with control_session_factory()() as session:
        row = session.get(Run, identity)
        session.get(User, row.owner_id).is_admin = False
        session.commit()
    result = windows.authorize_guest_update(root, context)
    assert result["run_id"] == identity and result["target_version"] == "0.5.1"
    assert spawn.call_count == 1  # Continuation only reads proof; it starts no installer.
    with pytest.raises(ValueError):
        windows.authorize_guest_update(root, {**context, "fingerprint": "f" * 64})


def test_native_activation_ack_is_idempotent_after_the_original_idle_gate_was_latched(
    accounts, tmp_path, monkeypatch
):
    from app import station_update_gate

    root, current, identity, claim, owner, snapshot, binding, _, _ = prepared(accounts, tmp_path, monkeypatch)
    assert station_update_gate.take(identity, claim)
    journal.publish(root, identity, "apply_requested", target=windows.target(snapshot))
    message = {
        "channel_id": binding["channel_id"],
        "run_id": identity,
        "fingerprint": snapshot["fingerprint"],
        "phase": "applying",
        "proof": None,
    }
    assert windows.host_result(root, current, message)["phase"] == "applying"
    first = journal.state(root, identity)["native_host_started_at"]
    assert windows.host_result(root, current, message)["phase"] == "applying"
    assert journal.state(root, identity)["native_host_started_at"] == first


def test_revoked_initial_administrator_refusal_is_durable_and_never_launches_a_helper(
    accounts, tmp_path, monkeypatch
):
    from app import station_update_gate
    from app.models import User

    identity, claim = updating(accounts)
    root = installation(tmp_path)
    installed = tmp_path / "installed"
    current = bundle(installed, PACKAGE | {"version": "0.4.0", "release_version": "0.4.0"})
    monkeypatch.setattr(windows, "guest", lambda: True)
    windows.bind(
        root,
        current,
        {
            "schema": 1,
            "channel_id": str(uuid4()),
            "host_manifest_sha256": "b" * 64,
            "version": "0.4.0",
        },
    )
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.parameters = {**run.parameters, "platform": "windows-x64"}
        parameters = dict(run.parameters)
        session.commit()
        assert station_update_gate.take(identity, claim)
        session.get(User, run.owner_id).is_admin = False
        session.commit()
    spawn = Mock()
    monkeypatch.setattr(journal.subprocess, "Popen", spawn)
    owner = windows.WindowsUpdates(root, installed, current)
    result = owner.handle({"action": "updates.prepare", "run_id": identity, "request": parameters})
    assert result["phase"] == "failed"
    assert owner.inspect(identity) == result  # Lost ACK remains inspectable, no permanent gate.
    spawn.assert_not_called()
