"""Native backup presentation over the existing trusted offline coordinators."""

import json
import subprocess
from uuid import uuid4

import desktop
import desktop_snapshots as snapshots
import desktop_versions as versions
import macos_desktop_ui as ui
from desktop_restoration import FENCE, Restoration
from desktop_restore_files import SecretConflict
from desktop_update import retained
from desktop_update_owner import handoff
from macos_database_storage import DatabaseStorage


def pending(root, data):
    found = []
    for kind, name in (("backup", snapshots.FENCE), ("restore", FENCE)):
        values = [snapshots.pending(folder, name) for folder in (root, data / "runtime")]
        values = [value for value in values if value is not None]
        if not values:
            continue
        if any(value != values[0] for value in values):
            raise ValueError("The private backup/restore markers differ; saved data needs inspection")
        operation = values[0]["operation_id"]
        phase = None
        if kind == "restore":
            phase = json.loads(versions.read_private(root / "restores" / operation / "state.json", 32768))[
                "phase"
            ]
        found.append({"kind": kind, "operation": operation, "phase": phase})
    if len(found) > 1:
        raise ValueError("Conflicting backup and restore operations need inspection")
    return found[0] if found else None


def confirm(resources, *, restore=False, resume=False, cancel=False):
    text = (
        "Restore this backup?\n\n"
        "Saved conversations and files will return to the backup's state. "
        "Your current passwords and MFA keys are kept. Original files remain available for recovery. "
        "Agents and unfinished jobs will stay paused; sessions will be signed out."
        if restore
        else "Create a complete private backup?\n\n"
        "It includes every account's conversations, files, owned models and credential files. "
        "Keep it somewhere private. Allow enough free space for those files."
    )
    if resume:
        text = (
            "Continue the interrupted operation?\n\nYour original files and recovery records have been kept."
        )
    if cancel:
        text = (
            "Cancel the interrupted operation safely?\n\n"
            "Your original saved data will be kept. Partial backup and recovery files remain available."
        )
    return (
        ui.dialog(
            resources,
            "--question",
            "--text=" + text + "\n\nAI Station will stop briefly. Running jobs may be interrupted.",
            "--ok-label="
            + (
                "Cancel operation"
                if cancel
                else "Continue"
                if resume
                else "Restore backup"
                if restore
                else "Create backup"
            ),
            "--cancel-label=" + ("Keep pending" if cancel else "Cancel"),
        )
        == 0
    )


def execute(storage, resources, action, selected, existing, *, owner_lock=None):
    """Caller retains desktop ownership; coordinators inspect actual workload quiescence."""
    operation = existing["operation"] if existing else str(uuid4())
    restoring = existing["kind"] == "restore" if existing else action == "restore"
    progress = ui.Preparation(
        resources,
        heading="Restoring your AI Station" if restoring else "Backing up your AI Station",
        cancelable=True,
    )

    def report(stage, done, total):
        names = {
            "database": "Preparing your saved history…",
            "files": "Copying and checking your files…",
            "publishing_files": "Restoring your files…",
            "publishing_database": "Finishing your restored history safely…",
            "complete": "Your restore is complete.",
        }
        progress.update(
            names.get(stage, "Preparing your private backup…"),
            done=done,
            total=total,
            cancelable=stage not in {"publishing_database", "complete"},
        )

    try:
        if restoring:
            owner = Restoration(storage, operation, selected if existing is None else None)
            if action == "abort":
                progress.update("Canceling the interrupted restore safely…", cancelable=False)
                return owner.abort(owner_lock=owner_lock)
            try:
                return owner.apply(canceled=progress.canceled, progress=report, owner_lock=owner_lock)
            except SecretConflict:
                owner.abort(owner_lock=owner_lock)
                progress.close()
                approved = (
                    ui.dialog(
                        resources,
                        "--question",
                        "--text=Some saved connection credentials differ.\n\nKeep the credentials currently used on this Mac and restore the other data? Your current passwords and MFA keys are preserved either way.",
                        "--ok-label=Keep current credentials and restore",
                        "--cancel-label=Cancel restore",
                    )
                    == 0
                )
                if not approved:
                    return owner.result()
                progress = ui.Preparation(resources, heading="Restoring your AI Station", cancelable=True)
                source = versions.canonical(owner.request["backup_path"])
                owner = Restoration(storage, str(uuid4()), source, secrets_policy="keep_current")
                return owner.apply(canceled=progress.canceled, progress=report, owner_lock=owner_lock)
        owner = snapshots.Snapshot(storage, operation)
        if action == "abort":
            progress.update("Canceling the interrupted backup safely…", cancelable=False)
            return owner.cancel(owner_lock=owner_lock)
        try:
            result = owner.export(canceled=progress.canceled, progress=report, owner_lock=owner_lock)
        except InterruptedError:
            progress.update("Canceling the backup safely…", cancelable=False)
            return owner.cancel(owner_lock=owner_lock)
        return {"status": "completed", "snapshot": result}
    finally:
        progress.close()


def manage(root, *, start, owner_lock=None):
    config = root / "desktop.env"
    data, _ = versions.namespace(config)
    current = versions.load(root)
    if current["phase"] != "ready":
        raise ValueError("Finish the desktop installation or update before managing backups")
    resources, value = retained(root, current["package"])
    storage = DatabaseStorage(root, config, desktop.select_engine(desktop.launch_environment()), value)
    existing = pending(root, data)
    reply = ui.backup_selection(
        resources,
        pending=existing["kind"] if existing else None,
        can_abort=not existing or existing["phase"] not in {"publishing_database", "applied"},
    )
    if set(reply) != {"action"}:
        raise ValueError("The native backup selection changed")
    action = reply["action"]
    if action == "cancel":
        return None
    if action not in ({"resume", "abort"} if existing else {"export", "restore"}):
        raise ValueError("Choose the operation offered for the current installation")
    selected = None
    if action == "restore":
        reply = ui.backup_folder(resources)
        if reply == {"action": "cancel"}:
            return None
        if set(reply) != {"path"} or not isinstance(reply["path"], str) or len(reply["path"]) > 8192:
            raise ValueError("Choose one complete backup folder")
        selected = versions.canonical(reply["path"])
        if selected.is_relative_to(data) or data.is_relative_to(selected):
            raise ValueError("Choose a complete backup outside application data")
        checking = ui.Preparation(resources, heading="Checking your backup", cancelable=True)
        try:
            checking.update("Checking the complete backup before changing saved data…")
            try:
                snapshots.verify(selected)  # Freeze and recheck again offline before publication.
            except (OSError, ValueError):
                raise ValueError(
                    "This backup could not be verified. Choose a complete exported backup folder with its database and files. Your saved data was not changed."
                ) from None
            if checking.canceled():
                return None
        finally:
            checking.close()

    def consent(*_):
        return confirm(
            resources,
            restore=action == "restore" or existing is not None and existing["kind"] == "restore",
            resume=existing is not None,
            cancel=action == "abort",
        )

    if owner_lock is not None or existing is not None:
        # Startup owns desktop.lock, or a prior fenced operation has already
        # stopped. Each coordinator acquires/rechecks its own cold locks.
        if not consent():
            return None
        result = execute(storage, resources, action, selected, existing, owner_lock=owner_lock)
    else:
        with handoff(
            root, config, desktop.control_directory(root), value, consent, maintenance=True
        ) as owner:
            if owner is None:
                return None
            result = execute(storage, resources, action, selected, existing, owner_lock=owner["owner_lock"])
    status = result.get("status")
    if status == "completed":
        path = storage.export_path(result["snapshot"]["operation_id"])
        if (
            ui.dialog(
                resources,
                "--question",
                "--text=Your complete backup is ready.\n\nKeep a private copy on another drive before removing this station's saved data.",
                "--ok-label=Show backup in Finder",
                "--cancel-label=Open AI Station",
            )
            == 0
        ):
            subprocess.run(["/usr/bin/open", str(path)], env=ui.environment(), check=False)
    elif status == "applied":
        ui.dialog(
            resources,
            "--text=Your backup has been restored.\n\nSign in with your current password. Agents and interrupted jobs remain paused so you can review them first.",
            "--ok-label=Open AI Station",
        )
    if status not in {"completed", "applied", "aborted", "canceled"}:
        raise ValueError("The operation needs inspection before AI Station can reopen")
    return start(resources)
