"""Offline WSL updater contracts. Temporary files and fake dpkg; no host install."""

import hashlib
import importlib.util
import io
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import desktop
import pytest

SPEC = importlib.util.spec_from_file_location(
    "wsl_guest_update", Path(__file__).parents[2] / "packaging/windows/guest_update.py"
)
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)
BYTES = b"Synthetic reviewed desktop package, never executed"


def receipt(epoch):
    return {
        "schema": 1,
        "desktop_protocol": 2,
        "source_head": str(epoch) * 40,
        "base": "ubuntu:24.04@sha256:" + "a" * 64,
        "package_sha256": hashlib.sha256(BYTES).hexdigest(),
        "package": {
            "Package": "ai-station",
            "Version": f"0.1.0~preview.{epoch}+" + "b" * 16,
            "Architecture": "amd64",
            "X-AI-Station-Desktop-Protocol": "2",
        },
        "sources": {name: "c" * 64 for name in ["guest.Dockerfile", "guest_control.py", "wsl.conf"]},
    }


@pytest.mark.parametrize(
    "field,value", [("schema", True), ("desktop_protocol", 3), ("source_head", "bad"), ("package_sha256", "")]
)
def test_invalid_update_identity_rejected_before_execution(field, value):
    target = receipt(2)
    target[field] = value
    with pytest.raises(ValueError):
        guest.plan(receipt(1), target)


@pytest.mark.parametrize("key", ["guest.Dockerfile", "wsl.conf", "guest_control.py"])
def test_guest_os_and_bridge_changes_require_a_separately_qualified_migration(key):
    target = receipt(2)
    target["sources"][key] = "d" * 64
    with pytest.raises(ValueError, match="recipe|bridge"):
        guest.plan(receipt(1), target)


def test_update_receipts_do_not_reinterpret_windows_archive_metadata():
    old, new = receipt(1), receipt(2)
    new["rootfs_sha256"] = "d" * 64
    new["rootfs_bytes"] = 100
    assert guest.plan(old, new) == {"previous": old, "target": receipt(2)}


@pytest.mark.parametrize("size", [True, 0, -1, 1024**3])
def test_invalid_package_lengths_do_not_create_files(tmp_path, size):
    with pytest.raises(ValueError):
        guest.receive(io.BytesIO(BYTES), tmp_path / "stage", hashlib.sha256(BYTES).hexdigest(), size)
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize(
    "data,expected",
    [(BYTES[:-1], "interrupted"), (BYTES + b"extra", "trailing"), (b"x" * len(BYTES), "checksum")],
)
def test_interrupted_or_changed_package_never_survives_admission(tmp_path, data, expected):
    with pytest.raises(ValueError, match=expected):
        guest.receive(io.BytesIO(data), tmp_path / "stage", hashlib.sha256(BYTES).hexdigest(), len(BYTES))
    assert not (tmp_path / "stage").exists()


def test_existing_transfer_destination_is_never_deleted_on_create_failure(tmp_path):
    path = tmp_path / "keep"
    path.write_bytes(b"Existing important bytes")
    with pytest.raises(FileExistsError):
        guest.receive(io.BytesIO(BYTES), path, hashlib.sha256(BYTES).hexdigest(), len(BYTES))
    assert path.read_bytes() == b"Existing important bytes"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "directory"])
def test_update_files_reject_links_unsafe_permissions_and_wrong_types(tmp_path, kind):
    file = tmp_path / "file"
    file.write_bytes(b"fixture")
    file.chmod(0o600)
    target = tmp_path / "target"
    if kind == "symlink":
        target.symlink_to(file)
    elif kind == "hardlink":
        os.link(file, target)
    elif kind == "public":
        target.write_bytes(b"public")
        target.chmod(0o644)
    else:
        target.mkdir()
    with pytest.raises(ValueError):
        guest.regular(target, os.getuid(), private=True)


def test_no_root_guest_update_is_permitted_on_the_development_host():
    with pytest.raises(ValueError, match="owned WSL2"):
        guest.assert_host("AIStation-" + "a" * 32)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home, store = tmp_path / "home", tmp_path / "updates"
    home.mkdir(mode=0o700)
    (home / ".local").mkdir(mode=0o700)
    (home / ".local/share").mkdir(mode=0o700)
    root = home / ".local/share/ai-station-desktop"
    root.mkdir(parents=True, mode=0o700)
    db_dir = root / "data/db"
    db_dir.mkdir(parents=True, mode=0o700)
    (root / "data").chmod(0o700)
    database = db_dir / "ai-station.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE runs(status TEXT);INSERT INTO runs VALUES('succeeded');CREATE TABLE private_data(value TEXT);INSERT INTO private_data VALUES('Synthetic account, library and memory bytes');"
        )
    database.chmod(0o600)
    manifest = tmp_path / "guest.json"
    manifest.write_text(json.dumps(receipt(1)))
    manifest.chmod(0o600)
    monkeypatch.setattr(guest, "HOME", home)
    monkeypatch.setattr(guest, "STORE", store)
    monkeypatch.setattr(guest, "RECEIPT", manifest)
    monkeypatch.setattr(guest, "PENDING_MARKER", tmp_path / "pending-marker.json")
    # Preserve real filesystem/link/permission checks in disposable ordinary-user
    # files; production always requires UID 0 for root-owned update material.
    regular, directory, locked = guest.regular, guest.directory, guest.locked
    uid = os.getuid()
    monkeypatch.setattr(
        guest, "regular", lambda path, owner, **kw: regular(path, uid if owner == 0 else owner, **kw)
    )
    monkeypatch.setattr(
        guest, "directory", lambda path, owner, **kw: directory(path, uid if owner == 0 else owner, **kw)
    )
    monkeypatch.setattr(
        guest, "locked", lambda path, owner, **kw: locked(path, uid if owner == 0 else owner, **kw)
    )
    calls = []
    monkeypatch.setattr(guest, "check_package", lambda *args: calls.append("validated"))
    monkeypatch.setattr(guest, "installed", lambda target: calls.append("verified_installed_files"))

    def install(*args):
        assert args[:2] == ("/usr/bin/dpkg", "--install")
        assert Path(args[2]).read_bytes() == BYTES
        assert json.loads((store / "pending.json").read_text())["phase"] == "installing"
        assert len(list(store.glob("*.sqlite"))) == 1
        calls.append("installed")
        return ""

    monkeypatch.setattr(guest, "run", install)
    return root, store, database, manifest, calls


def apply():
    return guest.update(io.BytesIO(BYTES), receipt(1), receipt(2), len(BYTES), os.getuid())


def test_complete_update_preserves_private_data_and_original_backup(fixture):
    root, store, database, manifest, calls = fixture
    before = database.read_bytes()
    result = apply()
    assert result == {"status": "updated", "backup_available": True, "data_preserved": True}
    assert database.read_bytes() == before
    assert json.loads(manifest.read_text()) == receipt(2)
    assert manifest.stat().st_mode & 0o777 == 0o644  # Ordinary station must confirm the guest receipt.
    assert calls == ["validated", "installed", "verified_installed_files"]
    assert not list(store.glob("*.part")) and not (store / "pending.json").exists()
    assert not guest.PENDING_MARKER.exists()
    backups = list(store.glob("*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("SELECT value FROM private_data").fetchone() == (
            "Synthetic account, library and memory bytes",
        )
    old_backup = backups[0].read_bytes()
    assert apply()["status"] == "updated"
    assert calls.count("installed") == 1  # Lost final acknowledgement does not reinstall completed bytes.
    assert backups[0].read_bytes() == old_backup


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested", "waiting_for_approval"])
def test_active_work_refuses_update_without_touching_package_or_database(fixture, status):
    root, store, database, manifest, calls = fixture
    with sqlite3.connect(database) as db:
        db.execute("UPDATE runs SET status=?", (status,))
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="active"):
        apply()
    assert database.read_bytes() == before
    assert json.loads(manifest.read_text()) == receipt(1)
    assert calls == ["validated"]
    assert not list(store.glob("*.sqlite")) and not (store / "pending.json").exists()


def test_live_desktop_owner_is_never_stopped_or_replaced(fixture):
    root, store, database, manifest, calls = fixture
    with guest.locked(root / "desktop.lock", os.getuid(), create=True):
        with pytest.raises(RuntimeError, match="still active"):
            apply()
    assert calls == [] and json.loads(manifest.read_text()) == receipt(1)


def test_different_pending_update_is_not_adopted(fixture):
    root, store, database, manifest, calls = fixture
    store.mkdir(mode=0o700)
    guest.atomic_json(store / "pending.json", {"operation": "a" * 64, "phase": "installing"})
    with pytest.raises(ValueError, match="different update"):
        apply()
    assert calls == []


def test_package_failure_retains_original_database_backup_and_pending_identity(fixture, monkeypatch):
    root, store, database, manifest, calls = fixture
    before = database.read_bytes()
    installer = guest.run
    monkeypatch.setattr(guest, "run", Mock(side_effect=RuntimeError("Synthetic dpkg failure")))
    with pytest.raises(RuntimeError, match="dpkg"):
        apply()
    assert database.read_bytes() == before and json.loads(manifest.read_text()) == receipt(1)
    assert json.loads((store / "pending.json").read_text())["target"] == receipt(2)
    assert guest.PENDING_MARKER.is_file()
    monkeypatch.setattr(desktop, "WSL_UPDATE_PENDING", guest.PENDING_MARKER)
    with pytest.raises(RuntimeError, match="pending Windows"):
        desktop.require_completed_guest_update()
    assert len(list(store.glob("*.sqlite"))) == 1 and not list(store.glob("*.part"))
    old_backup = list(store.glob("*.sqlite"))[0].read_bytes()
    monkeypatch.setattr(guest, "run", installer)
    assert apply()["status"] == "updated"
    desktop.require_completed_guest_update()
    assert list(store.glob("*.sqlite"))[0].read_bytes() == old_backup


def test_foreign_installed_receipt_stops_before_package_transfer(fixture):
    root, store, database, manifest, calls = fixture
    manifest.write_text(json.dumps(receipt(3)))
    with pytest.raises(ValueError, match="identity changed"):
        apply()
    assert calls == [] and not list(store.glob("*.part"))


def test_duplicate_metadata_fields_are_never_silently_overwritten():
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads('{"package_bytes":1,"package_bytes":2}', object_pairs_hook=guest.strict_object)


@pytest.mark.parametrize("kind", ["file", "broken-link", "directory"])
def test_pending_update_blocks_start_before_any_app_or_machine_work(tmp_path, monkeypatch, kind):
    pending = tmp_path / "pending"
    if kind == "file":
        pending.write_text("Synthetic pending update")
    elif kind == "broken-link":
        pending.symlink_to(tmp_path / "missing")
    else:
        pending.mkdir()
    monkeypatch.setattr(desktop, "WSL_UPDATE_PENDING", pending)
    monkeypatch.setattr(desktop.sys, "argv", ["station", "--console", "--background"])
    manifest, prerequisites = Mock(), Mock()
    monkeypatch.setattr(desktop, "manifest", manifest)
    monkeypatch.setattr(desktop, "prerequisites", prerequisites)
    with pytest.raises(RuntimeError, match="pending Windows"):
        desktop.main()
    manifest.assert_not_called()
    prerequisites.assert_not_called()


@pytest.mark.parametrize("action", ["--status", "--stop"])
def test_pending_update_still_allows_existing_status_and_stop(tmp_path, monkeypatch, action, capsys):
    marker = tmp_path / "marker"
    marker.write_text("pending")
    monkeypatch.setattr(desktop, "WSL_UPDATE_PENDING", marker)
    monkeypatch.setattr(desktop.sys, "argv", ["station", action])
    monkeypatch.setattr(desktop, "manifest", lambda _: {})
    monkeypatch.setattr(desktop, "state_root", lambda: tmp_path)
    monkeypatch.setattr(desktop, "unowned_supervisor_active", lambda _: False)
    desktop.main()
    assert json.loads(capsys.readouterr().out) == {"running": False}


def test_existing_launcher_owner_is_never_bypassed(fixture):
    root, store, database, manifest, calls = fixture
    runtime = root / "data/runtime"
    runtime.mkdir(mode=0o700)
    with guest.locked(runtime / "launcher.lock", os.getuid(), create=True):
        with pytest.raises(RuntimeError, match="still active"):
            apply()
    assert calls == [] and json.loads(manifest.read_text()) == receipt(1)


def test_foreign_state_parent_link_is_rejected_before_any_transfer(fixture):
    root, store, database, manifest, calls = fixture
    real = root.parent
    moved = real.with_name("moved-state")
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="directory"):
        apply()
    assert calls == [] and not list(store.glob("*.part"))


def test_corrupt_original_backup_is_preserved_for_inspection(fixture):
    root, store, database, manifest, calls = fixture
    assert apply()["status"] == "updated"
    backup = next(store.glob("*.sqlite"))
    backup.write_bytes(b"Corrupt original evidence; preserve me")
    with pytest.raises(sqlite3.DatabaseError):
        apply()
    assert backup.read_bytes() == b"Corrupt original evidence; preserve me"
    assert calls.count("installed") == 1


@pytest.mark.parametrize("version,protocol", [(2, "2"), (0, "2"), (2, "99")])
def test_actual_debian_metadata_and_version_order_before_install(tmp_path, version, protocol):
    import subprocess

    package = tmp_path / "payload"
    control = package / "DEBIAN"
    control.mkdir(parents=True)
    control.chmod(0o755)
    candidate = receipt(version)
    (control / "control").write_text(
        "Package: ai-station\nVersion: " + candidate["package"]["Version"] + "\n"
        "Architecture: amd64\nX-AI-Station-Desktop-Protocol: " + protocol + "\n"
        "Maintainer: Synthetic Test <test@example.invalid>\nDescription: Not installed\n"
    )
    (control / "control").chmod(0o644)
    output = tmp_path / "candidate.deb"
    built = subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(package), str(output)],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    if version == 2 and protocol == "2":
        guest.check_package(output, candidate, receipt(1))
    else:
        with pytest.raises(ValueError, match="downgrades|metadata"):
            guest.check_package(output, candidate, receipt(1))


def test_lost_ack_after_target_receipt_reconciles_without_second_install(fixture, monkeypatch):
    root, store, database, manifest, calls = fixture
    original = guest.atomic_json

    def lost_ack(path, value, **options):
        original(path, value, **options)
        if path == manifest:
            raise InterruptedError("Synthetic lost client after completed guest receipt")

    monkeypatch.setattr(guest, "atomic_json", lost_ack)
    with pytest.raises(InterruptedError):
        apply()
    assert json.loads(manifest.read_text()) == receipt(2)
    assert (store / "pending.json").exists() and guest.PENDING_MARKER.exists()
    backup = next(store.glob("*.sqlite")).read_bytes()
    monkeypatch.setattr(guest, "atomic_json", original)
    assert apply()["status"] == "updated"
    assert calls.count("installed") == 1
    assert next(store.glob("*.sqlite")).read_bytes() == backup
    assert not guest.PENDING_MARKER.exists()


@pytest.fixture(autouse=True)
def restore_process_state_after_desktop_cli_tests():
    import signal

    old_mask = os.umask(0o077)
    os.umask(old_mask)
    old_handler = signal.getsignal(signal.SIGTERM)
    yield
    os.umask(old_mask)
    signal.signal(signal.SIGTERM, old_handler)


def test_installer_timeout_reaps_only_its_owned_process_group(monkeypatch):
    import signal
    import subprocess

    child = Mock(pid=12345)
    child.communicate.side_effect = [
        subprocess.TimeoutExpired("fixed package step", 600),
        subprocess.TimeoutExpired("owned group stopping", 5),
        ("", ""),
    ]
    started = Mock(return_value=child)
    signaled = Mock()
    monkeypatch.setattr(guest.subprocess, "Popen", started)
    monkeypatch.setattr(guest.os, "killpg", signaled)
    monkeypatch.setenv("AI_STATION_TEST_PRIVATE", "synthetic secret")
    with pytest.raises(subprocess.TimeoutExpired):
        guest.run("/usr/bin/dpkg", "--install", "/fixed-owned-stage")
    assert started.call_args.args == (("/usr/bin/dpkg", "--install", "/fixed-owned-stage"),)
    options = started.call_args.kwargs
    assert options["start_new_session"] is True and "AI_STATION_TEST_PRIVATE" not in options["env"]
    assert signaled.call_args_list == [((12345, signal.SIGTERM),), ((12345, signal.SIGKILL),)]
    assert [c.kwargs["timeout"] for c in child.communicate.call_args_list] == [600, 5, 5]


def test_private_entry_reads_bounded_header_and_handles_owned_termination(fixture, monkeypatch, capsys):
    import signal
    from types import SimpleNamespace

    header = (
        json.dumps({"previous": receipt(1), "target": receipt(2), "package_bytes": len(BYTES)}).encode()
        + b"\n"
    )
    monkeypatch.setattr(guest.sys, "argv", ["guest-update", "AIStation-" + "a" * 32])
    monkeypatch.setattr(guest.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(header + BYTES)))
    monkeypatch.setattr(guest, "assert_host", lambda _: os.getuid())
    handler = Mock()
    monkeypatch.setattr(guest.signal, "signal", handler)
    guest.main()
    assert json.loads(capsys.readouterr().out)["status"] == "updated"
    handler.assert_called_once()
    assert handler.call_args.args[0] == signal.SIGTERM
    with pytest.raises(KeyboardInterrupt):
        handler.call_args.args[1](signal.SIGTERM, None)


def test_matching_operation_hash_never_adopts_different_pending_target(fixture):
    root, store, database, manifest, calls = fixture
    accepted = guest.plan(receipt(1), receipt(2))
    operation = hashlib.sha256(guest.canonical_json(accepted)).hexdigest()
    store.mkdir(mode=0o700)
    guest.atomic_json(
        store / "pending.json",
        {"operation": operation, "phase": "installing", "previous": receipt(1), "target": receipt(3)},
    )
    with pytest.raises(ValueError, match="different update"):
        apply()
    assert calls == [] and json.loads(manifest.read_text()) == receipt(1)
