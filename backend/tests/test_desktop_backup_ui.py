"""Native backup flows with actual file journals and the fake owned DB daemon."""

import fcntl
import os
from contextlib import contextmanager
from uuid import uuid4

import desktop_backup_ui as ui
import pytest
from desktop_restoration import Restoration
from test_desktop_database_storage import factory  # noqa: F401
from test_desktop_restoration import setup  # noqa: F401
from test_desktop_snapshots import station  # noqa: F401
from test_desktop_versions import installation  # noqa: F401


class Progress:
    frames = None
    cancel_files = False

    def __init__(self, *args, **kwargs):
        self.frames = []
        self.stop = False
        Progress.frames = self.frames

    def update(self, text, **kwargs):
        self.frames.append((text, kwargs))
        if self.cancel_files and text == "Copying and checking your files…":
            self.stop = True

    def canceled(self):
        return self.stop

    def close(self):
        pass


@pytest.fixture
def presentation(setup, monkeypatch):  # noqa: F811
    create, daemon, root, data, backup, before, state, rows = setup
    choices, dialogs, finder = [], [], []
    owner = create()
    monkeypatch.setattr(ui, "retained", lambda *args: (root, owner.package))
    monkeypatch.setattr(ui.desktop, "select_engine", lambda *_: None)
    monkeypatch.setattr(ui, "DatabaseStorage", lambda *_: create())
    monkeypatch.setattr(ui.ui, "Preparation", Progress)
    monkeypatch.setattr(Progress, "cancel_files", False)
    monkeypatch.setattr(ui.ui, "backup_selection", lambda *a, **kw: choices.pop(0))
    monkeypatch.setattr(ui.ui, "backup_folder", lambda *_: {"path": str(backup)})

    def review(*_):
        dialogs.append(("native_restore_review",))
        return {"action": "restore"}

    monkeypatch.setattr(ui.ui, "restore_review", review)

    def dialog(*args):
        dialogs.append(args)
        return 0

    monkeypatch.setattr(ui.ui, "dialog", dialog)
    monkeypatch.setattr(ui.subprocess, "run", lambda argv, **kw: finder.append(argv))
    return create, daemon, root, data, backup, before, state, choices, dialogs, finder


@contextmanager
def ownership(root):
    descriptor = os.open(root / "desktop.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield descriptor
    finally:
        os.close(descriptor)


def test_native_export_completes_then_reveals_only_its_verified_backup(presentation):
    _, _, root, _, _, _, _, choices, _, finder = presentation
    choices.append({"action": "export"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    assert len(finder) == 1 and finder[0][0] == "/usr/bin/open"
    source = ui.versions.canonical(finder[0][1])
    assert source.parent == root / "database-exports"
    assert ui.snapshots.verify(source)["file_count"] > 0


def test_native_restore_changes_files_only_after_review_and_disables_cancel_at_db_publication(presentation):
    _, _, root, data, _, _, state, choices, dialogs, _ = presentation
    choices.append({"action": "restore"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    assert state["main"] == "b" * 64
    assert (data / "artifacts/private.txt").read_text() == "synthetic artifacts"
    assert any(row[0] == "native_restore_review" for row in dialogs)
    assert any(not frame["cancelable"] for _, frame in Progress.frames)
    ui.snapshots.assert_finished(root, data)


def test_closing_selection_never_dispatches_a_helper_or_restarts_station(presentation):
    _, daemon, root, data, _, before, _, choices, _, _ = presentation
    choices.append({"action": "cancel"})
    calls = len(daemon.calls)
    assert ui.manage(root, start=lambda _: pytest.fail("Unselected restart")) is None
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[calls:])
    from desktop_restore_files import inventory

    assert inventory(data) == before


def test_incomplete_backup_is_explained_before_stopping_or_changing_station(
    presentation, monkeypatch, tmp_path
):
    _, daemon, root, _, _, _, _, choices, _, _ = presentation
    missing = tmp_path / "not-a-backup"
    missing.mkdir(mode=0o700)
    monkeypatch.setattr(ui.ui, "backup_folder", lambda *_: {"path": str(missing)})
    choices.append({"action": "restore"})
    calls = len(daemon.calls)
    with pytest.raises(ValueError, match="complete exported backup folder"):
        ui.manage(root, start=lambda _: pytest.fail("Unverified backup restart"))
    assert not any(
        args[:2] in (["container", "create"], ["container", "stop"]) for args in daemon.calls[calls:]
    )


def test_native_export_cancel_clears_only_its_fence_and_keeps_original_data(presentation, monkeypatch):
    _, _, root, data, _, before, state, choices, _, _ = presentation
    monkeypatch.setattr(Progress, "cancel_files", True)
    choices.append({"action": "export"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    from desktop_restore_files import inventory

    assert inventory(data) == before and state["main"] == "e" * 64
    ui.snapshots.assert_finished(root, data)


def test_cooperative_native_cancel_aborts_restore_and_preserves_originals(presentation, monkeypatch):
    _, _, root, data, _, before, state, choices, _, _ = presentation
    monkeypatch.setattr(Progress, "cancel_files", True)
    choices.append({"action": "restore"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    from desktop_restore_files import inventory

    assert inventory(data) == before and state["main"] == "e" * 64
    ui.snapshots.assert_finished(root, data)


def test_interrupted_file_publication_reopens_native_resume_selection(presentation):
    create, _, root, data, backup, _, _, choices, _, _ = presentation
    operation = str(uuid4())

    def exit_after_files(stage, done, total):
        if stage == "publishing_files" and done == 1:
            raise RuntimeError("synthetic parent exit")

    with pytest.raises(RuntimeError, match="parent exit"):
        Restoration(create(), operation, backup).apply(progress=exit_after_files)
    assert ui.pending(root, data) == {"kind": "restore", "operation": operation, "phase": "publishing_files"}
    choices.append({"action": "resume"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    ui.snapshots.assert_finished(root, data)


def test_credential_conflict_requires_explicit_review_before_a_new_preserving_restore(presentation):
    _, _, root, data, _, _, _, choices, dialogs, _ = presentation
    (data / "secrets/private.txt").write_text("newer connection credential")
    choices.append({"action": "restore"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    assert (data / "secrets/private.txt").read_text() == "newer connection credential"
    assert any("Some saved connection credentials differ" in " ".join(map(str, row)) for row in dialogs)
    ui.snapshots.assert_finished(root, data)


def test_explicit_administrator_recovery_uses_private_file_never_password_argv(presentation, monkeypatch):
    import json

    _, daemon, root, data, _, _, _, choices, _, _ = presentation
    secret = {
        "username": "Owner",
        "password": "synthetic recovered administrator password",
        "reset_mfa": True,
    }
    monkeypatch.setattr(ui.ui, "restore_review", lambda *_: {"action": "recover"})
    monkeypatch.setattr(ui.ui, "administrator_recovery", lambda *_: secret)
    choices.append({"action": "restore"})
    with ownership(root) as lock:
        assert ui.manage(root, start=lambda p: p, owner_lock=lock) == root
    payloads = list((root / "restores").glob("*/authority/administrator.json"))
    assert len(payloads) == 1 and json.loads(payloads[0].read_text()) == secret
    prepared = [
        args
        for args in daemon.calls
        if args[:2] == ["container", "create"] and "app.desktop_restore" in args and "prepare" in args
    ]
    assert len(prepared) == 1 and "--recover-admin" in prepared[0]
    assert secret["password"] not in repr(daemon.calls)
    ui.snapshots.assert_finished(root, data)


def test_canceling_recovery_form_never_changes_station_or_starts_helpers(presentation, monkeypatch):
    _, daemon, root, data, _, before, _, choices, _, _ = presentation
    monkeypatch.setattr(ui.ui, "restore_review", lambda *_: {"action": "recover"})
    monkeypatch.setattr(ui.ui, "administrator_recovery", lambda *_: None)
    choices.append({"action": "restore"})
    calls = len(daemon.calls)
    with ownership(root) as lock:
        assert (
            ui.manage(
                root, start=lambda _: pytest.fail("Canceled recovery restarted station"), owner_lock=lock
            )
            is None
        )
    assert not (root / "restores").exists()
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[calls:])
    from desktop_restore_files import inventory

    assert inventory(data) == before


def test_failed_start_exposes_restore_without_requiring_a_live_control_channel(presentation, monkeypatch):
    create, _, root, data, _, _, _, _, _, _ = presentation
    ui.versions.begin(root, create().package, root / "desktop.env", "d" * 32)
    with ownership(root):
        pass  # A failed supervisor released its original lock.

    def select(*args, **kwargs):
        assert kwargs["restore_only"] is True
        return {"action": "restore"}

    monkeypatch.setattr(ui.ui, "backup_selection", select)
    monkeypatch.setattr(ui, "handoff", lambda *a, **kw: pytest.fail("No live supervisor to Stop"))
    assert ui.manage(root, start=lambda p: p) == root
    assert ui.versions.load(root)["phase"] == "starting"  # Readiness requires the actual new API instance.
    ui.snapshots.assert_finished(root, data)


def test_recovery_never_takes_a_starting_supervisors_lock(presentation, monkeypatch):
    create, daemon, root, _, _, _, _, choices, _, _ = presentation
    ui.versions.begin(root, create().package, root / "desktop.env", "d" * 32)
    choices.append({"action": "restore"})
    before = len(daemon.calls)
    with ownership(root):
        with pytest.raises(ValueError, match="still starting or stopping"):
            ui.manage(root, start=lambda _: pytest.fail("Active supervisor replaced"))
    assert not any(args[:2] == ["container", "create"] for args in daemon.calls[before:])
