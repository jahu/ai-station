import fcntl
from datetime import timedelta
from types import SimpleNamespace

import desktop_auto_update as operation
import desktop_update_recovery as recovery
import desktop_versions as versions
import pytest
from app.db import control_session_factory, utcnow
from app.models import Run, User
from app.station_update_gate import take
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_desktop_auto_update import prepared
from test_desktop_linux_update import PACKAGE, bundle


def suspended(accounts, tmp_path, monkeypatch):
    root, owner, identity, claim, _, _ = prepared(accounts, tmp_path, monkeypatch)
    target = PACKAGE | {
        "bundle_id": "d" * 64,
        "image_id": "sha256:" + "e" * 64,
        "image_tag": "ai-station:desktop-" + "d" * 16,
    }
    installed = root / "releases" / target["bundle_id"]
    target = bundle(installed, target)
    installed.chmod(0o700)
    installed.parent.chmod(0o700)
    engine = SimpleNamespace(identity=("/usr/bin/docker", "unix:///run/docker.sock"))
    folder = operation.folder(root, identity)
    (folder / "helper.lock").touch(mode=0o600)
    (root / "desktop.lock").touch(mode=0o600)
    take(identity, claim)
    operation.publish(
        root,
        identity,
        "apply_requested",
        target=versions.package_identity(target),
        engine=list(engine.identity),
    )
    recovery.begin(root, identity)
    operation.publish(root, identity, "inspection_required")
    with control_session_factory()() as session:
        run = session.get(Run, identity)
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
        run.status = "interrupted"
        session.commit()
    monkeypatch.setattr(operation.linux, "attested_engine", lambda *args: engine)
    return root, identity, installed, target, engine


@pytest.mark.parametrize("native_phase", ["prepared", "applied"])
def test_resume_inspects_original_dispatch_and_does_not_repeat_an_already_applied_publish(
    accounts, tmp_path, monkeypatch, native_phase
):
    import desktop_upgrade_image as coordinator

    root, identity, installed, target, engine = suspended(accounts, tmp_path, monkeypatch)
    calls = []

    class Core:
        def state(self):
            return {"current": "original-dispatch", "commands": {"original-dispatch": {}}}

        def resume(self):
            calls.append("inspect-original")
            return {"phase": native_phase}

        def run(self, action):
            calls.append(action)
            return {"phase": "applied"}

        def finish(self, *, activate):
            calls.append("finish")
            assert activate
            return {"phase": "applied"}

    def client(*args):
        assert args[0] == root and args[2] is engine and args[-1] == identity
        return Core()

    monkeypatch.setattr(coordinator, "UpgradeImage", client)
    assert recovery.resume(root, console=True, approved=True) == installed
    assert calls == (
        ["inspect-original", "publish", "finish"]
        if native_phase == "prepared"
        else ["inspect-original", "finish"]
    )
    assert operation.state(root, identity)["phase"] == "applied"
    assert (root / recovery.MARKER).exists()  # Only actual healthy readiness clears it.


def test_explicit_local_os_resume_can_finish_after_worker_and_account_authority_disappear(
    accounts, tmp_path, monkeypatch
):
    import desktop_update_authority as authority

    root, identity, _, _, _ = suspended(accounts, tmp_path, monkeypatch)
    item = recovery.pending(root)
    with control_session_factory()() as session:
        session.get(User, session.get(Run, identity).owner_id).is_admin = False
        session.commit()
    with pytest.raises(ValueError):
        authority.authority(root, identity, expected=item["saved"]["request"], idle=True)
    proof = authority.authority(
        root, identity, expected=item["saved"]["request"], idle=True, native_resume=True
    )
    assert proof["request"] == item["saved"]["request"]


def test_active_original_helper_is_never_replayed(accounts, tmp_path, monkeypatch):
    root, identity, _, _, _ = suspended(accounts, tmp_path, monkeypatch)
    with (operation.folder(root, identity) / "helper.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert recovery.pending(root)["active"]
        with pytest.raises(RuntimeError, match="still running"):
            recovery.resume(root, console=True, approved=True)


def test_changed_marker_is_refused_before_resume(accounts, tmp_path, monkeypatch):
    root, _, _, _, _ = suspended(accounts, tmp_path, monkeypatch)
    marker = operation.read(root / recovery.MARKER)
    operation.write(root / recovery.MARKER, marker | {"request_sha256": "f" * 64})
    with pytest.raises(ValueError, match="no longer matches"):
        recovery.pending(root)


def test_changed_local_engine_is_refused_before_any_coordinator_action(accounts, tmp_path, monkeypatch):
    import desktop_upgrade_image as coordinator

    root, _, _, _, _ = suspended(accounts, tmp_path, monkeypatch)
    monkeypatch.setattr(
        operation.linux,
        "attested_engine",
        lambda *args: SimpleNamespace(identity=("/other/docker", "unix:///run/other.sock")),
    )

    def forbidden(*args):
        raise AssertionError("No coordinator should run on the replacement daemon")

    monkeypatch.setattr(coordinator, "UpgradeImage", forbidden)
    with pytest.raises(RuntimeError, match="original local Docker"):
        recovery.resume(root, console=True, approved=True)


@pytest.mark.parametrize("verified_abort", [True, False])
def test_aborted_transaction_reopens_previous_version_only_with_original_coordinator_proof(
    accounts, tmp_path, monkeypatch, verified_abort
):
    import desktop_upgrade_image as coordinator

    root, identity, _, target, engine = suspended(accounts, tmp_path, monkeypatch)
    saved = operation.request(root, identity)
    previous = root / "releases" / saved["previous"]["bundle_id"]
    bundle(previous, PACKAGE | {"version": "0.4.0", "release_version": "0.4.0"})
    previous.chmod(0o700)
    calls = []

    class Aborted:
        def state(self):
            return {"current": None, "commands": {"original": {}}}

        def run(self, action):
            calls.append(action)
            return {"phase": "aborted"}

        def finish(self, *, activate):
            assert activate is False
            calls.append("confirm-abort")
            if verified_abort:
                core = root / "image-upgrades"
                core.mkdir(mode=0o700)
                core /= identity
                core.mkdir(mode=0o700)
                operation.write(
                    core / "request.json",
                    {
                        "operation_id": identity,
                        "previous": saved["previous"],
                        "target": versions.package_identity(target),
                        "namespace_sha256": saved["namespace_sha256"],
                        "engine": list(engine.identity),
                    },
                )
                operation.write(
                    core / "state.json",
                    {
                        "current": None,
                        "final": {
                            "phase": "aborted",
                            "operation_id": identity,
                            "target_bundle": target["bundle_id"],
                        },
                    },
                )

    monkeypatch.setattr(coordinator, "UpgradeImage", lambda *args: Aborted())
    if verified_abort:
        assert recovery.resume(root, console=True, approved=True) == previous
        assert not (root / recovery.MARKER).exists()
        assert operation.state(root, identity)["phase"] == "failed"
    else:
        with pytest.raises(ValueError, match="not confirmed"):
            recovery.resume(root, console=True, approved=True)
        assert (root / recovery.MARKER).exists()
    assert calls == ["status", "confirm-abort"]
