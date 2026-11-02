"""Fixed native restore dispatch/ownership/Stop, no SQL, models or real Docker."""

import json
from uuid import uuid4

import macos_database_storage as storage
import pytest
from test_desktop_database_storage import factory  # noqa: F401
from test_desktop_versions import installation  # noqa: F401


@pytest.fixture
def setup(factory, monkeypatch):  # noqa: F811
    create, daemon, root, _ = factory
    owner = create()
    owner.prepare()
    backup = str(uuid4())
    snapshot = owner.export_database(backup)
    request = {
        "operation_id": str(uuid4()),
        "backup_id": backup,
        "snapshot_identity": "a" * 64,
        "database_sha256": snapshot["database_sha256"],
        "backup_path": str(owner.export_path(backup)),
        "recover_admin": False,
    }
    pending = {}
    hang = [False]

    def command(argv, **kwargs):
        args = argv[5:]
        row = daemon.containers.get(args[-1]) if args else None
        restoring = row is not None and "app.desktop_restore" in row["Config"]["Cmd"]
        if restoring and args[:2] == ["container", "start"] and hang[0]:
            daemon.calls.append(args)
            row["State"].update(Status="running", Running=True)
            if daemon.lose == ("container", "start"):
                daemon.lose = None
                raise RuntimeError("fixture lost acknowledgement")
            return 0, row["Id"]
        if restoring and args[:2] == ["container", "logs"]:
            daemon.calls.append(args)
            cmd = row["Config"]["Cmd"]
            action = cmd[3]
            operation = cmd[cmd.index("--operation-id") + 1]
            phase = pending.get(operation, "preparing")
            phase = {"prepare": "prepared", "publish": "applied", "abort": "aborted", "status": phase}[action]
            pending[operation] = phase
            result = {
                "schema": 1,
                "operation_id": operation,
                "backup_id": request["backup_id"],
                "snapshot_identity": request["snapshot_identity"],
                "image_id": owner.package["image_id"],
                "storage": owner.binding(),
                "source": {"main": "e" * 64, "-wal": None, "-journal": None},
                "phase": phase,
                "database_revision": "0042",
                "database_sha256": "b" * 64 if phase != "preparing" else None,
                "actions": {"automatic_replay": False} if phase != "preparing" else None,
            }
            return 0, json.dumps(daemon.output(result))
        return daemon(argv, **kwargs)

    monkeypatch.setattr(storage, "command", command)
    return create, daemon, root, request, hang


def test_fixed_restore_uses_owned_rw_volume_and_ro_input_without_ambient_authority(setup):
    create, daemon, _, request, _ = setup
    result = create().restore_database("prepare", request)
    assert result["phase"] == "prepared"
    args = next(args for args in reversed(daemon.calls) if args[:2] == ["container", "create"])
    assert args[args.index("--memory") + 1] == str(storage.RESTORE_MEMORY)
    assert args[args.index("--network") + 1] == "none" and "--privileged" not in args
    mounts = [args[i + 1] for i, v in enumerate(args) if v == "--mount"]
    assert len(mounts) == 2 and "readonly" not in mounts[0]
    assert "target=/restore" in mounts[1] and mounts[1].endswith(",readonly")
    assert create().restore_database("publish", request)["phase"] == "applied"
    args = next(args for args in reversed(daemon.calls) if args[:2] == ["container", "create"])
    assert sum(v == "--mount" for v in args) == 1
    assert not daemon.containers and len(daemon.volumes) == 1


@pytest.mark.parametrize("pair", [("container", "create"), ("container", "start"), ("container", "rm")])
def test_lost_restore_helper_ack_reuses_owned_command_and_cached_result(setup, pair):
    create, daemon, _, request, _ = setup
    daemon.lose = pair
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        create().restore_database("prepare", request)
    assert create().restore_database("prepare", request)["phase"] == "prepared"
    commands = [
        args for args in daemon.calls if args[:2] == ["container", "create"] and "app.desktop_restore" in args
    ]
    assert len(commands) == 1 and not daemon.containers


@pytest.mark.parametrize("field", ["operation_id", "storage", "image_id", "phase", "actions"])
def test_changed_restore_ack_never_becomes_a_completed_receipt(setup, field):
    create, daemon, _, request, _ = setup
    daemon.output = lambda value: {
        **value,
        field: {"automatic_replay": True} if field == "actions" else "changed",
    }
    with pytest.raises(ValueError, match="acknowledgement changed"):
        create().restore_database("prepare", request)
    assert create().record["command"]["phase"] == "starting"
    assert not any(args[:2] == ["container", "stop"] for args in daemon.calls)


def test_foreign_volume_client_blocks_restore_before_dispatch(setup):
    create, daemon, _, request, _ = setup
    daemon.foreign = True
    before = len(daemon.calls)
    with pytest.raises(ValueError, match="Another container"):
        create().restore_database("prepare", request)
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[before:])


def test_restore_preparation_cancel_stops_only_owned_helper_then_requires_inspection(setup):
    create, daemon, _, request, hang = setup
    hang[0] = True
    daemon.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().restore_database("prepare", request)
    owned = next(iter(daemon.containers))
    result = create().interrupt_restore(request)
    assert result["status"] == "inspection_required"
    assert [args for args in daemon.calls if args[:2] == ["container", "stop"]] == [
        ["container", "stop", "--time", "5", owned]
    ]
    hang[0] = False
    assert create().restore_database("status", request)["phase"] == "preparing"
    assert create().restore_database("abort", request)["phase"] == "aborted"


@pytest.mark.parametrize("pair", [("container", "stop"), ("container", "rm")])
def test_interrupted_staging_lost_stop_or_removal_ack_never_signals_twice(setup, pair):
    create, daemon, _, request, hang = setup
    hang[0] = True
    daemon.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().restore_database("prepare", request)
    daemon.lose = pair
    with pytest.raises(RuntimeError):
        create().interrupt_restore(request)
    assert create().interrupt_restore(request)["status"] == "inspection_required"
    assert len([args for args in daemon.calls if args[:2] == ["container", "stop"]]) == 1
    assert not daemon.containers


def test_restore_publication_cannot_be_blindly_canceled(setup):
    create, daemon, _, request, _ = setup
    create().restore_database("prepare", request)
    daemon.lose = ("container", "create")
    with pytest.raises(RuntimeError):
        create().restore_database("publish", request)
    before = len(daemon.calls)
    with pytest.raises(ValueError, match="Only this owned restore preparation"):
        create().interrupt_restore(request)
    assert not any(args[:2] == ["container", "stop"] for args in daemon.calls[before:])
    assert create().restore_database("publish", request)["phase"] == "applied"


def test_restore_admin_password_uses_only_fixed_private_readonly_mount(setup):
    create, daemon, root, request, _ = setup
    request["recover_admin"] = True
    path = root / "restores" / request["operation_id"] / "authority"
    path.mkdir(mode=0o700, parents=True)
    storage.write(
        path / "administrator.json",
        {"username": "Owner", "password": "synthetic recovery password", "reset_mfa": True},
    )
    create().restore_database("prepare", request)
    args = next(args for args in reversed(daemon.calls) if args[:2] == ["container", "create"])
    assert "--recover-admin" in args and "synthetic recovery password" not in str(args)
    assert any("target=/recovery-authority" in arg and arg.endswith(",readonly") for arg in args)


@pytest.mark.parametrize("missing", ["backup", "authority"])
def test_owned_staging_can_stop_if_removable_source_or_password_file_disappears(setup, missing):
    from pathlib import Path

    create, daemon, root, request, hang = setup
    if missing == "authority":
        request["recover_admin"] = True
        path = root / "restores" / request["operation_id"] / "authority"
        path.mkdir(mode=0o700, parents=True)
        storage.write(
            path / "administrator.json",
            {"username": "Owner", "password": "synthetic recovery password", "reset_mfa": True},
        )
    else:
        path = Path(request["backup_path"])
    hang[0] = True
    daemon.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().restore_database("prepare", request)
    path.rename(path.with_name(path.name + "-removed"))
    assert create().interrupt_restore(request)["status"] == "inspection_required"
    assert not daemon.containers
    hang[0] = False
    assert create().restore_database("status", request)["phase"] == "preparing"


@pytest.mark.parametrize("action", ["status", "prepare"])
def test_confirmed_unstarted_reply_is_only_admitted_for_inspection(setup, action):
    create, daemon, _, request, _ = setup
    daemon.output = lambda value: {
        **{k: value[k] for k in ("schema", "operation_id", "image_id", "storage", "source")},
        "phase": "not_started",
    }
    if action == "status":
        assert create().restore_database(action, request)["phase"] == "not_started"
    else:
        with pytest.raises(ValueError, match="acknowledgement changed"):
            create().restore_database(action, request)


def test_dispatched_restore_ack_remains_recoverable_after_source_is_removed(setup):
    from pathlib import Path

    create, daemon, _, request, _ = setup
    daemon.lose = ("container", "start")
    with pytest.raises(RuntimeError):
        create().restore_database("prepare", request)
    path = Path(request["backup_path"])
    path.rename(path.with_name(path.name + "-removed"))
    assert create().restore_database("prepare", request)["phase"] == "prepared"
    assert not daemon.containers


def test_cooperative_cancellation_stops_running_staging_without_waiting_for_deadline(setup):
    create, daemon, _, request, hang = setup
    hang[0] = True
    calls = 0

    def canceled():
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(InterruptedError, match="stopped"):
        create().restore_database("prepare", request, canceled=canceled)
    assert not daemon.containers
    assert len([args for args in daemon.calls if args[:2] == ["container", "stop"]]) == 1
