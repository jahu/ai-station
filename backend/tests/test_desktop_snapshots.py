"""Whole private backup transaction, using disposable storage and a fake daemon."""

import json
import os
from uuid import uuid4

import desktop_snapshot_files as files
import desktop_snapshots as snapshots
import desktop_versions as versions
import macos_database_storage as storage
import pytest
from test_desktop_database_storage import PACKAGE, factory  # noqa: F401
from test_desktop_versions import OWNER, installation  # noqa: F401


@pytest.fixture
def station(factory, monkeypatch):  # noqa: F811
    create, daemon, root, data = factory
    owner = create()
    owner.prepare()
    versions.begin(root, PACKAGE, owner.config, OWNER, storage=owner)
    versions.ready(root, PACKAGE, owner.config, OWNER)
    (root / "desktop.lock").touch(mode=0o600)
    (data / "runtime").mkdir(mode=0o700)
    for name in ("artifacts", "uploads", "secrets"):
        (data / name).mkdir(mode=0o700)
        (data / name / "private.txt").write_text("synthetic " + name)
    rows = []

    def command(argv, **kwargs):
        args = argv[5:]
        if args == ["container", "ls", "--all", "--quiet", "--no-trunc"]:
            return 0, "\n".join(row["Id"] for row in [*rows, *daemon.containers.values()])
        if args[:3] == ["container", "inspect", "--format"]:
            return 0, "\n".join(
                json.dumps(
                    {
                        "Id": row["Id"],
                        "State": {
                            key: row["State"].get(key, False) for key in ("Running", "Paused", "Restarting")
                        },
                        "Mounts": row["Mounts"],
                    }
                )
                for row in [*rows, *daemon.containers.values()]
            )
        return daemon(argv, **kwargs)

    monkeypatch.setattr(storage, "command", command)
    return create, daemon, root, data, rows


def test_full_backup_binds_database_retained_files_and_private_configuration(station):
    create, _, root, data, _ = station
    operation = str(uuid4())
    backup = snapshots.Snapshot(create(), operation)
    progress = []
    result = backup.export(progress=lambda *args: progress.append(args))
    output = root / "database-exports" / operation
    assert result == snapshots.verify(output)
    assert result["file_count"] == 3
    assert progress[0] == ("database", 0, 1) and progress[-1] == ("files", 6, 6)
    assert (output / "files/secrets/private.txt").read_text() == "synthetic secrets"
    assert (output / "desktop.env").read_bytes() == (root / "desktop.env").read_bytes()
    assert (output / "desktop.env").stat().st_mode & 0o777 == 0o600
    assert not (output / "files/runtime").exists() and not (output / "files/db").exists()
    assert not (root / snapshots.FENCE).exists()
    assert not (data / "runtime" / snapshots.FENCE).exists()
    before = (output / "database.sqlite").stat().st_mtime_ns
    assert snapshots.Snapshot(create(), operation).export() == result
    assert (output / "database.sqlite").stat().st_mtime_ns == before
    # A completed export can be inspected after source data changes or disappears.
    (data / "artifacts/private.txt").unlink()
    assert snapshots.verify(output) == result


def test_interrupted_file_export_stays_fenced_and_resumes_without_rewriting(station):
    create, _, root, data, _ = station
    operation = str(uuid4())

    def interrupt(stage, done, total):
        if stage == "files" and done == 2:
            raise RuntimeError("synthetic parent exit")

    with pytest.raises(RuntimeError, match="parent exit"):
        snapshots.Snapshot(create(), operation).export(progress=interrupt)
    with pytest.raises(ValueError, match="pending private backup"):
        snapshots.assert_finished(root, data)
    output = root / "database-exports" / operation
    stamp = (output / "files/artifacts/private.txt").stat().st_mtime_ns
    result = snapshots.Snapshot(create(), operation).export()
    assert result == snapshots.verify(output)
    assert (output / "files/artifacts/private.txt").stat().st_mtime_ns == stamp
    snapshots.assert_finished(root, data)


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_database_lost_ack_resumes_same_full_backup(station, pair):
    create, daemon, root, _, _ = station
    operation = str(uuid4())
    daemon.lose = pair
    with pytest.raises(RuntimeError):
        snapshots.Snapshot(create(), operation).export()
    assert snapshots.pending(root)["operation_id"] == operation
    result = snapshots.Snapshot(create(), operation).export()
    assert result == snapshots.verify(root / "database-exports" / operation)
    assert (
        len([args for args in daemon.calls if args[:2] == ["container", "create"] and "export" in args]) == 1
    )


def test_changed_database_cannot_be_combined_with_older_export(station):
    create, _, root, _, _ = station
    operation = str(uuid4())

    def interrupt(stage, done, total):
        if stage == "files":
            raise InterruptedError("synthetic exit")

    with pytest.raises(InterruptedError):
        snapshots.Snapshot(create(), operation).export(progress=interrupt)
    owner = create()
    original = owner.fingerprint()
    owner.fingerprint = lambda: original | {"main": {"sha256": "f" * 64}}
    with pytest.raises(ValueError, match="source database changed"):
        snapshots.Snapshot(owner, operation).export()
    assert snapshots.pending(root) is not None
    assert not (root / "database-exports" / operation / "snapshot.json").exists()


def test_changed_retained_file_preserves_partial_output_until_explicit_cancel(station):
    create, _, root, data, _ = station
    operation = str(uuid4())
    with pytest.raises(InterruptedError):
        snapshots.Snapshot(create(), operation).export(canceled=lambda: True)
    # Start files export before interrupting, so the source catalogue is durable.
    with pytest.raises(InterruptedError):
        snapshots.Snapshot(create(), operation).export(
            progress=lambda stage, done, total: None,
            canceled=lambda: (root / "database-exports" / operation / "files-request.json").exists(),
        )
    (data / "artifacts/private.txt").write_text("newer source")
    with pytest.raises(ValueError, match="changed since"):
        snapshots.Snapshot(create(), operation).export()
    assert snapshots.Snapshot(create(), operation).cancel()["status"] == "canceled"
    snapshots.assert_finished(root, data)
    with pytest.raises(ValueError, match="was canceled"):
        snapshots.Snapshot(create(), operation).export()
    assert (data / "artifacts/private.txt").read_text() == "newer source"


@pytest.mark.parametrize("suffix", ["", "/artifacts", "/../"])
def test_live_bind_container_prevents_full_backup_before_db_dispatch(station, suffix):
    create, daemon, root, data, rows = station
    rows.append(
        {
            "Id": "e" * 64,
            "State": {"Running": True, "Paused": False, "Restarting": False},
            "Mounts": [{"Type": "bind", "Source": str(data) + suffix}],
        }
    )
    before = len(daemon.calls)
    with pytest.raises(ValueError, match="containers using"):
        snapshots.Snapshot(create(), str(uuid4())).export()
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[before:])
    assert not (root / snapshots.FENCE).exists()


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_native_live_group_refuses_backup_without_signals(station, monkeypatch, system):
    from ai_station_runner import darwin_processes, processes

    create, _, root, data, _ = station
    files.write_json(
        data / "runtime/processes.json",
        {"owned": {"pid": 12345, "process_group_id": 12345, "boot_id": "fixture", "start_ticks": 9}},
    )
    inspected = []
    monkeypatch.setattr(snapshots.platform, "system", lambda: system)
    module, name = (darwin_processes, "group_alive") if system == "Darwin" else (processes, "_group_alive")
    monkeypatch.setattr(module, name, lambda record: inspected.append(record) or True)
    with pytest.raises(ValueError, match="native workload"):
        snapshots.Snapshot(create(), str(uuid4())).export()
    assert len(inspected) == 1 and not (root / snapshots.FENCE).exists()


@pytest.mark.parametrize(
    "filename",
    ["files/artifacts/private.txt", "database.sqlite", "desktop.env", "installation.json", "receipt.json"],
)
def test_completed_full_backup_rejects_tampering(station, filename):
    create, _, root, _, _ = station
    operation = str(uuid4())
    snapshots.Snapshot(create(), operation).export()
    output = root / "database-exports" / operation
    (output / filename).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        snapshots.verify(output)


def test_cancel_pending_database_helper_keeps_original_data_and_disallows_replay(station):
    create, daemon, root, data, _ = station
    operation = str(uuid4())
    daemon.hang_export = True
    daemon.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        snapshots.Snapshot(create(), operation).export()
    assert snapshots.Snapshot(create(), operation).cancel()["status"] == "canceled"
    assert (data / "artifacts/private.txt").read_text() == "synthetic artifacts"
    assert not daemon.containers and len(daemon.volumes) == 1
    snapshots.assert_finished(root, data)
    with pytest.raises(ValueError, match="was canceled"):
        snapshots.Snapshot(create(), operation).export()


def test_desktop_and_launcher_locks_exclude_other_owners(station):
    import fcntl

    create, _, root, _, _ = station
    fd = os.open(root / "desktop.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="still stopping"):
            snapshots.Snapshot(create(), str(uuid4())).export()
    finally:
        os.close(fd)


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_fingerprint_lost_ack_is_reconciled_by_the_full_backup(station, pair):
    create, daemon, root, _, _ = station
    operation = str(uuid4())

    def lose_reader(stage, done, total):
        if stage == "database" and done == 1:
            daemon.lose = pair

    with pytest.raises(RuntimeError):
        snapshots.Snapshot(create(), operation).export(progress=lose_reader)
    result = snapshots.Snapshot(create(), operation).export()
    assert snapshots.verify(root / "database-exports" / operation) == result


def test_cancel_leaves_a_new_external_file_client_running(station):
    create, _, root, data, rows = station
    operation = str(uuid4())
    with pytest.raises(InterruptedError):
        snapshots.Snapshot(create(), operation).export(canceled=lambda: True)
    rows.append(
        {
            "Id": "e" * 64,
            "State": {"Running": True, "Paused": False, "Restarting": False},
            "Mounts": [{"Type": "bind", "Source": str(data)}],
        }
    )
    assert snapshots.Snapshot(create(), operation).cancel()["status"] == "canceled"
    assert rows[0]["State"]["Running"]
    snapshots.assert_finished(root, data)


def test_extra_database_sidecar_cannot_enter_a_verified_snapshot(station):
    create, _, root, _, _ = station
    operation = str(uuid4())
    snapshots.Snapshot(create(), operation).export()
    output = root / "database-exports" / operation
    (output / "database.sqlite-wal").write_bytes(b"unexpected database state")
    with pytest.raises(ValueError, match="inventory changed"):
        snapshots.verify(output)


def test_offline_verify_entry_needs_neither_source_nor_docker(station, capsys, monkeypatch):
    import desktop_backup

    create, _, root, _, _ = station
    operation = str(uuid4())
    result = snapshots.Snapshot(create(), operation).export()
    monkeypatch.setattr(storage, "command", lambda *_args, **_kwargs: pytest.fail("Unexpected Docker call"))
    assert desktop_backup.main(["verify", str(root / "database-exports" / operation)]) == result
    assert json.loads(capsys.readouterr().out) == result


def test_cancel_reconciles_only_its_pending_readonly_helper(station):
    create, daemon, root, data, _ = station
    operation = str(uuid4())

    def lose_reader(stage, done, total):
        if stage == "database" and done == 1:
            daemon.lose = ("container", "start")

    with pytest.raises(RuntimeError):
        snapshots.Snapshot(create(), operation).export(progress=lose_reader)
    assert snapshots.Snapshot(create(), operation).cancel()["status"] == "canceled"
    assert not daemon.containers and len(daemon.volumes) == 1
    snapshots.assert_finished(root, data)


def test_launcher_fence_is_enforced_independently_of_native_metadata(station):
    from launch import ensure_recovery_finished

    create, _, root, data, _ = station
    with pytest.raises(InterruptedError):
        snapshots.Snapshot(create(), str(uuid4())).export(canceled=lambda: True)
    with pytest.raises(RuntimeError, match="pending private backup"):
        ensure_recovery_finished(data / "runtime")
    (data / "runtime" / snapshots.FENCE).unlink()
    with pytest.raises(ValueError, match="pending private backup"):
        snapshots.assert_finished(root, data)
