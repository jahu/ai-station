"""Actual owned Linux process/UDS lifecycle, with an offline synthetic daemon."""

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import tailnet_service as mod

FAKE = """#!/usr/bin/python3
import sys,os,json,socketserver,http.server
from pathlib import Path
args=dict(x.removeprefix('--').split('=',1) for x in sys.argv[1:] if '=' in x)
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  root=Path(args['socket']).parent
  file=root/('node.json' if self.path=='/localapi/v0/status' else 'config.json')
  data=json.loads(file.read_text()) if file.exists() else {'BackendState':'NeedsLogin','AuthURL':'SECRET-LOGIN-URL','Peer':{'sensitive':'peer'}} if self.path=='/localapi/v0/status' else {}
  raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
server=socketserver.UnixStreamServer(args['socket'],Handler)
os.chmod(args['socket'],0o600)
open(args['state'],'w').write('SECRET-NODE-KEY');os.chmod(args['state'],0o600)
print('SECRET-LOGIN-URL',flush=True)
server.serve_forever()
"""


@pytest.fixture
def manager(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="ait-") as root:
        base = Path(root)
        binaries = base / "bin"
        binaries.mkdir(mode=0o700)
        (binaries / "tailscaled").write_text(FAKE)
        (binaries / "tailscaled").chmod(0o700)
        monkeypatch.setattr(mod, "verified_install", lambda *args: {})
        service = mod.TailnetManager(base / "private", binaries, base / "app-data")
        yield service
        try:
            service.stop()
        except (ValueError, OSError):
            pass
        if service._manager is not None:
            service._manager.shutdown()


def test_readonly_status_does_not_create_private_keys_or_directories(manager):
    assert manager.status() == {"state": "stopped", "owned": False, "node_online": False, "serving": False}
    assert not manager.root.exists()


def test_registry_validation_serializes_with_managed_process_updates(manager, monkeypatch):
    import threading

    manager.start(str(uuid4()))
    processes = manager._processes()
    original = mod.read_private
    checked = []

    def read(path, *, limit):
        if path == manager.root / "runtime/processes.json":
            acquired = []

            def writer():
                success = processes._lock.acquire(blocking=False)
                acquired.append(success)
                if success:
                    processes._lock.release()

            thread = threading.Thread(target=writer)
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive() and acquired == [False]
            checked.append(True)
        return original(path, limit=limit)

    monkeypatch.setattr(mod, "read_private", read)
    assert manager._processes() is processes and checked


def test_start_inspect_restart_recovery_and_owned_stop(manager):
    run_id = str(uuid4())
    state = manager.start(run_id)
    assert state["started"] and state["owned"] and state["state"] == "NeedsLogin"
    assert not state["node_online"] and not state["serving"]
    assert "SECRET" not in json.dumps(state)
    assert manager.socket.stat().st_mode & 0o777 == 0o600
    recovered = mod.TailnetManager(manager.root, manager.binary_dir, manager.data_root)
    assert recovered.status()["daemon_id"] == run_id
    assert recovered.start(str(uuid4()))["started"] is False
    assert manager.stop(only_start_run_id=str(uuid4())) == {"stopped": False}
    assert manager.status()["state"] == "NeedsLogin"
    assert manager.stop(only_start_run_id=run_id)["stopped"]
    assert not manager.socket.exists() and manager.status()["state"] == "stopped"
    assert (manager.root / "tailscaled.state").read_text() == "SECRET-NODE-KEY"
    with pytest.raises(ValueError, match="previous start"):
        manager.start(run_id)
    assert manager.start(str(uuid4()))["started"]


def test_secret_directory_inside_app_mount_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        mod.TailnetManager(tmp_path / "data/private", tmp_path / "bin", tmp_path / "data")
    with pytest.raises(ValueError):
        mod.TailnetManager(tmp_path, tmp_path / "bin", tmp_path / "data")


def test_start_never_adopts_unrelated_private_files(manager):
    manager.root.mkdir(mode=0o700)
    original = manager.root / "other.keys"
    original.write_text("preserve")
    with pytest.raises(ValueError, match="not owned"):
        manager.start(str(uuid4()))
    assert original.read_text() == "preserve" and {p.name for p in manager.root.iterdir()} == {"other.keys"}


def test_recovery_rejects_a_different_control_plane_data_root(manager):
    manager.start(str(uuid4()))
    different = mod.TailnetManager(manager.root, manager.binary_dir, manager.data_root.with_name("other-app"))
    with pytest.raises(ValueError, match="another data"):
        different.status()
    with pytest.raises(ValueError):
        different.stop()
    assert manager.status()["state"] == "NeedsLogin"


def test_symlinked_journal_never_authorizes_process_signaling(manager, monkeypatch):
    run_id = str(uuid4())
    manager.start(run_id)
    journal = manager.root / "service.json"
    original = journal.read_bytes()
    outside = manager.root.parent / "outside"
    outside.write_bytes(original)
    journal.unlink()
    journal.symlink_to(outside)
    signals = []
    monkeypatch.setattr(mod.ProcessManager, "_signal", lambda *args: signals.append(args))
    with pytest.raises(OSError):
        manager.stop()
    assert not signals
    journal.unlink()
    journal.write_bytes(original)
    journal.chmod(0o600)
    monkeypatch.undo()


def test_reused_process_identity_is_not_signaled(manager, monkeypatch):
    run_id = str(uuid4())
    manager.start(run_id)
    process = manager._processes()
    records = process._load()
    original = dict(records[run_id])
    records[run_id]["start_ticks"] += 1
    process._dump(records)
    signals = []
    monkeypatch.setattr(mod.ProcessManager, "_signal", lambda *args: signals.append(args))
    assert manager.status()["state"] == "inspection_required"
    with pytest.raises(ValueError, match="still has a listener"):
        manager.stop()
    assert not signals
    records = process._load()
    records[run_id] = original
    process._dump(records)
    monkeypatch.undo()


def test_missing_launch_record_requires_inspection_without_reexecution(manager):
    manager._validate_owner(create=True)
    manager._write({"run_id": str(uuid4()), "phase": "preparing"})
    assert manager.status()["state"] == "inspection_required"
    assert not (manager.root / "runtime").exists()
    with pytest.raises(ValueError, match="journal"):
        manager.start(str(uuid4()))
    assert not manager.socket.exists()


def test_existing_temporary_journal_cannot_truncate_other_files(manager):
    manager._validate_owner(create=True)
    outside = manager.root.parent / "important"
    outside.write_bytes(b"preserve existing data")
    os.link(outside, manager.root / "service.tmp")
    with pytest.raises(FileExistsError):
        manager.start(str(uuid4()))
    assert outside.read_bytes() == b"preserve existing data"
    assert not manager.socket.exists()


def test_private_socket_replacement_is_not_followed(manager):
    manager.start(str(uuid4()))
    target = manager.root.parent / "outside"
    target.write_bytes(b"preserve existing data")
    manager.socket.unlink()
    manager.socket.symlink_to(target)
    with pytest.raises(ValueError, match="socket"):
        manager.status()
    with pytest.raises(ValueError):
        manager.stop()
    assert target.read_bytes() == b"preserve existing data"


def test_cancel_before_service_dispatch_never_launches(manager):
    rid = str(uuid4())
    manager.request_cancel(rid, "start")
    state = manager.start(rid)
    assert state["canceled"] and not state["started"]
    assert not (manager.root / "service.json").exists()


@pytest.mark.parametrize("folder", ["runtime", "runs", "cancellations"])
def test_private_subdirectory_symlinks_cannot_escape_service_storage(manager, folder):
    manager._validate_owner(create=True)
    outside = manager.root.parent / "outside"
    outside.mkdir(mode=0o700)
    (manager.root / folder).symlink_to(outside, target_is_directory=True)
    rid = str(uuid4())
    with pytest.raises(ValueError):
        if folder == "cancellations":
            manager.request_cancel(rid, "start")
        else:
            manager.start(rid)
    assert list(outside.iterdir()) == []
