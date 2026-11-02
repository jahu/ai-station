"""Full files/DB coordinator with a fake daemon and actual filesystem journals."""

import json
from uuid import uuid4

import desktop_restoration as restoration
import desktop_restore_files as retained
import desktop_snapshots as snapshots
import macos_database_storage as storage
import pytest
from test_desktop_database_storage import factory  # noqa: F401
from test_desktop_snapshots import station  # noqa: F401
from test_desktop_versions import installation  # noqa: F401


@pytest.fixture
def setup(station, monkeypatch):  # noqa: F811
    create, daemon, root, data, rows = station
    backup_id = str(uuid4())
    owner = create()
    snapshots.Snapshot(owner, backup_id).export()
    backup = owner.export_path(backup_id)
    (data / "artifacts/private.txt").write_text("newer live artifact")
    (data / "secrets/current-MFA").write_text("current MFA key")
    before = retained.inventory(data)
    command = storage.command
    state = {"main": "e" * 64, "restores": {}}

    def call(argv, **kwargs):
        args = argv[5:]
        row = daemon.containers.get(args[-1]) if args else None
        cmd = row["Config"]["Cmd"] if row is not None else []
        if args[:2] == ["container", "logs"] and "fingerprint" in cmd:
            value = {
                "storage": owner.binding(),
                "database": {"main": state["main"], "-wal": None, "-journal": None},
            }
            return 0, json.dumps(value)
        if args[:2] == ["container", "logs"] and "app.desktop_restore" in cmd:
            operation = cmd[cmd.index("--operation-id") + 1]
            action = cmd[3]
            previous = state["restores"].get(operation)
            if previous is None and action == "status":
                return 0, json.dumps(
                    {
                        "schema": 1,
                        "operation_id": operation,
                        "image_id": owner.package["image_id"],
                        "storage": owner.binding(),
                        "phase": "not_started",
                        "source": {"main": state["main"], "-wal": None, "-journal": None},
                    }
                )
            if previous is None:
                assert action == "prepare"
                previous = {
                    "schema": 1,
                    "operation_id": operation,
                    "backup_id": backup_id,
                    "snapshot_identity": json.loads((backup / "snapshot.json").read_text())["identity"],
                    "image_id": owner.package["image_id"],
                    "storage": owner.binding(),
                    "source": {"main": state["main"], "-wal": None, "-journal": None},
                    "phase": "prepared",
                    "database_revision": "0042",
                    "database_sha256": "b" * 64,
                    "actions": {"automatic_replay": False},
                }
            if action == "publish":
                previous = {**previous, "phase": "applied"}
                state["main"] = previous["database_sha256"]
            elif action == "abort":
                previous = {**previous, "phase": "aborted"}
            state["restores"][operation] = previous
            return 0, json.dumps(previous)
        return command(argv, **kwargs)

    monkeypatch.setattr(storage, "command", call)
    return create, daemon, root, data, backup, before, state, rows


def test_full_restore_publishes_files_and_database_then_preserves_receipts_and_current_MFA(setup):
    create, _, root, data, backup, _, state, _ = setup
    version = (root / "desktop-version.json").read_bytes()
    config = (root / "desktop.env").read_bytes()
    operation = str(uuid4())
    result = restoration.Restoration(create(), operation, backup).apply()
    assert result["status"] == "applied" and state["main"] == "b" * 64
    assert (data / "artifacts/private.txt").read_text() == "synthetic artifacts"
    assert (data / "secrets/current-MFA").read_text() == "current MFA key"
    assert (
        data / "recovery" / ("desktop-" + operation) / "originals/artifacts/private.txt"
    ).read_text() == "newer live artifact"
    assert (root / "desktop-version.json").read_bytes() == version and (
        root / "desktop.env"
    ).read_bytes() == config
    snapshots.assert_finished(root, data)


def test_interrupted_file_publication_resumes_same_transaction(setup):
    create, _, root, data, backup, _, _, _ = setup
    operation = str(uuid4())

    def crash(stage, done, total):
        if stage == "publishing_files" and done == 1:
            raise RuntimeError("synthetic process exit")

    with pytest.raises(RuntimeError, match="process exit"):
        restoration.Restoration(create(), operation, backup).apply(progress=crash)
    with pytest.raises(ValueError, match="pending private restore"):
        snapshots.assert_finished(root, data)
    assert restoration.Restoration(create(), operation).apply()["status"] == "applied"
    snapshots.assert_finished(root, data)


def test_cancel_after_file_publication_restores_originals_and_aborts_prepared_db(setup):
    create, _, root, data, backup, before, state, _ = setup
    canceled = False

    def progress(stage, done, total):
        nonlocal canceled
        if stage == "publishing_files" and done == 1:
            canceled = True

    result = restoration.Restoration(create(), str(uuid4()), backup).apply(
        canceled=lambda: canceled, progress=progress
    )
    assert result["status"] == "aborted" and state["main"] == "e" * 64
    assert retained.inventory(data) == before
    snapshots.assert_finished(root, data)


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_lost_database_preparation_ack_is_reconciled_before_full_restore(setup, pair):
    create, daemon, root, data, backup, _, _, _ = setup
    operation = str(uuid4())

    def lose(stage, done, total):
        if stage == "database" and done == 0:
            daemon.lose = pair

    with pytest.raises(RuntimeError):
        restoration.Restoration(create(), operation, backup).apply(progress=lose)
    assert restoration.Restoration(create(), operation).apply()["status"] == "applied"
    created = [
        args
        for args in daemon.calls
        if args[:2] == ["container", "create"] and "app.desktop_restore" in args and "prepare" in args
    ]
    assert len(created) == 1
    snapshots.assert_finished(root, data)


def test_lost_database_publication_ack_cannot_trigger_blind_file_rollback(setup):
    create, daemon, root, data, backup, _, state, _ = setup
    operation = str(uuid4())

    def lose(stage, done, total):
        if stage == "publishing_database":
            daemon.lose = ("container", "rm")

    with pytest.raises(RuntimeError):
        restoration.Restoration(create(), operation, backup).apply(progress=lose)
    assert state["main"] == "b" * 64
    with pytest.raises(ValueError, match="publication may have started"):
        restoration.Restoration(create(), operation).abort()
    assert restoration.Restoration(create(), operation).apply()["status"] == "applied"
    snapshots.assert_finished(root, data)


def test_explicit_abort_of_prepared_restore_keeps_live_files_and_database(setup):
    create, _, root, data, backup, before, state, _ = setup
    operation = str(uuid4())
    owner = restoration.Restoration(create(), operation, backup)
    assert owner.prepare()["status"] == "prepared"
    assert owner.abort()["status"] == "aborted"
    assert retained.inventory(data) == before and state["main"] == "e" * 64
    snapshots.assert_finished(root, data)


def test_request_before_initial_state_write_can_resume(setup):
    create, _, _, data, backup, before, _, _ = setup
    operation = str(uuid4())
    owner = restoration.Restoration(create(), operation, backup)
    (owner.folder / "state.json").unlink()
    assert restoration.Restoration(create(), operation).apply()["status"] == "applied"
    assert retained.inventory(data) != before


@pytest.mark.parametrize("published", [False, True])
def test_missing_coordinator_state_after_preparation_requires_inspection(setup, published):
    create, daemon, _, data, backup, _, state, _ = setup
    operation = str(uuid4())
    owner = restoration.Restoration(create(), operation, backup)
    if published:

        def lose(stage, done, total):
            if stage == "publishing_database":
                daemon.lose = ("container", "rm")

        with pytest.raises(RuntimeError):
            owner.apply(progress=lose)
        assert state["main"] == "b" * 64
    else:
        owner.prepare()
    (owner.folder / "state.json").unlink()
    before, calls = retained.inventory(data), len(daemon.calls)
    with pytest.raises(ValueError, match="state is missing"):
        restoration.Restoration(create(), operation)
    assert retained.inventory(data) == before
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[calls:])
    assert not (owner.folder / "state.json").exists()


def test_conflicting_credentials_can_be_canceled_and_reviewed_as_new_restore(setup):
    create, _, root, data, backup, _, _, _ = setup
    (data / "secrets/private.txt").write_text("newer connector credential")
    operation = str(uuid4())
    with pytest.raises(retained.SecretConflict):
        restoration.Restoration(create(), operation, backup).apply()
    assert restoration.Restoration(create(), operation).abort()["status"] == "aborted"
    assert (
        restoration.Restoration(create(), str(uuid4()), backup, secrets_policy="keep_current").apply()[
            "status"
        ]
        == "applied"
    )
    assert (data / "secrets/private.txt").read_text() == "newer connector credential"
    snapshots.assert_finished(root, data)


def test_completed_restore_does_not_rewrite_later_application_data(setup):
    create, daemon, _, data, backup, _, _, _ = setup
    operation = str(uuid4())
    result = restoration.Restoration(create(), operation, backup).apply()
    (data / "artifacts/private.txt").write_text("legitimate later user edit")
    before = len(daemon.calls)
    assert restoration.Restoration(create(), operation).apply() == result
    assert (data / "artifacts/private.txt").read_text() == "legitimate later user edit"
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[before:])


def test_foreign_file_client_is_never_stopped_or_overwritten(setup):
    create, daemon, root, data, backup, before, _, rows = setup
    rows.append(
        {
            "Id": "f" * 64,
            "State": {"Running": True, "Paused": False, "Restarting": False},
            "Mounts": [{"Type": "bind", "Source": str(data)}],
        }
    )
    with pytest.raises(ValueError, match="containers using"):
        restoration.Restoration(create(), str(uuid4()), backup).apply()
    assert retained.inventory(data) == before and rows[0]["State"]["Running"]
    assert not any(args[:2] == ["container", "stop"] for args in daemon.calls)
    assert not (root / restoration.FENCE).exists()


def test_modified_published_file_is_not_hidden_by_database_publication(setup):
    create, _, root, data, backup, _, state, _ = setup

    def changed(stage, done, total):
        if stage == "publishing_database":
            (data / "artifacts/private.txt").write_text("unexpected later human edit")

    with pytest.raises(ValueError, match="changed"):
        restoration.Restoration(create(), str(uuid4()), backup).apply(progress=changed)
    assert state["main"] == "e" * 64
    assert (data / "artifacts/private.txt").read_text() == "unexpected later human edit"
    with pytest.raises(ValueError, match="pending private restore"):
        snapshots.assert_finished(root, data)


def test_restore_CLI_uses_existing_coordinator_and_returns_private_operation_status(
    setup, monkeypatch, capsys
):
    import desktop
    import desktop_backup
    import desktop_engine

    create, _, root, data, backup, _, _, _ = setup
    package = root / "installed-bundle"
    package.mkdir(mode=0o700)
    monkeypatch.setattr(desktop_backup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(desktop, "manifest", lambda _: {})
    monkeypatch.setattr(desktop, "verify", lambda *_: None)
    monkeypatch.setattr(desktop_engine, "select", lambda *_: None)
    existing_owner = create()
    monkeypatch.setattr(storage, "DatabaseStorage", lambda *_: existing_owner)
    operation = str(uuid4())
    result = desktop_backup.main(
        [
            "restore",
            "--package",
            str(package),
            "--config",
            str(root / "desktop.env"),
            "--backup",
            str(backup),
            "--operation",
            operation,
        ]
    )
    assert result["status"] == "applied"
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["operation_id"] == operation
    assert (data / "secrets/current-MFA").read_text() == "current MFA key"
