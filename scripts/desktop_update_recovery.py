"""Native activation marker and proof: never infer completion from a vanished PID."""

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from uuid import UUID

import desktop_versions as versions
from desktop_update_owner import handoff, lock_file, require_lock
from desktop_upgrade_image import FENCE, write

MARKER = "desktop-auto-update-pending.json"


@contextmanager
def cold_owner(root):
    held = []
    try:
        for name in ("desktop-update.lock", "desktop.lock"):
            descriptor = lock_file(root, name, create=name == "desktop-update.lock")
            held.append((name, descriptor))
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(
                    "The station or another updater is still active; no process was stopped"
                ) from None
            require_lock(root, name, descriptor)
        yield
        for name, descriptor in held:
            require_lock(root, name, descriptor)
    finally:
        for _, descriptor in reversed(held):
            os.close(descriptor)


def desktop_live(root):
    descriptor = lock_file(root, "desktop.lock")
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(descriptor)


def identity(saved):
    return {
        "schema": 1,
        "run_id": saved["run_id"],
        "request_sha256": hashlib.sha256(
            json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def begin(root, run_id):
    from desktop_auto_update import read, request, state

    saved = request(root, run_id)
    stage = state(root, run_id)
    if (
        stage["phase"] != "apply_requested"
        or not isinstance(stage.get("engine"), list)
        or len(stage["engine"]) != 2
    ):
        raise ValueError("The native update has no frozen local activation request")
    expected = identity(saved)
    path = root / MARKER
    if path.exists() or path.is_symlink():
        if read(path) != expected:
            raise ValueError("An earlier native update needs inspection first")
    else:
        write(path, expected)


def pending(root):
    from desktop_auto_update import folder, read, request, state

    path = root / MARKER
    if not path.exists() and not path.is_symlink():
        return None
    marker = read(path)
    if type(marker.get("schema")) is not int:
        raise ValueError("The pending native update marker schema is invalid")
    run_id = marker.get("run_id")
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("The pending native update identity changed")
    saved = request(root, run_id)
    if marker != identity(saved):
        raise ValueError("The native activation marker no longer matches its approved request")
    stage = state(root, run_id)
    target = versions.package_identity(stage.get("target"))
    engine = stage.get("engine")
    if not isinstance(engine, list) or len(engine) != 2 or not all(isinstance(v, str) for v in engine):
        raise ValueError("The pending native update lost its local Docker identity")
    descriptor = lock_file(folder(root, run_id), "helper.lock")
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            active = True
        else:
            active = False
    finally:
        os.close(descriptor)
    return {
        "run_id": run_id,
        "saved": saved,
        "state": stage,
        "target": target,
        "engine": tuple(engine),
        "active": active,
    }


def operation(root, run_id):
    from desktop_auto_update import request, state

    saved = request(root, run_id)
    stage = state(root, run_id)
    target = versions.package_identity(stage.get("target"))
    engine = stage.get("engine")
    if not isinstance(engine, list) or len(engine) != 2 or not all(isinstance(v, str) for v in engine):
        raise ValueError("The native update lost its original local Docker connection")
    return {"run_id": run_id, "saved": saved, "state": stage, "target": target, "engine": tuple(engine)}


def outcome(root, item):
    """Require the original coordinator's durable final result and version receipt."""
    from desktop_auto_update import read

    data, namespace = versions.namespace(root / "desktop.env")
    if namespace != item["saved"]["namespace_sha256"]:
        raise ValueError("The pending update's data namespace changed")
    for name in (FENCE, "desktop-upgrade-pending.json"):
        marker = data / "runtime" / name
        if marker.exists() or marker.is_symlink():
            return None
    folder = root / "image-upgrades" / item["run_id"]
    try:
        request = read(folder / "request.json")
        state = read(folder / "state.json")
    except FileNotFoundError:
        return None
    if (
        request.get("operation_id") != item["run_id"]
        or request.get("previous") != item["saved"]["previous"]
        or request.get("target") != item["target"]
        or request.get("namespace_sha256") != namespace
        or request.get("engine") != list(item["engine"])
    ):
        raise ValueError("The native update coordinator belongs to different input")
    final = state.get("final")
    if (
        state.get("current") is not None
        or not isinstance(final, dict)
        or final.get("phase") not in {"applied", "aborted"}
    ):
        return None
    # Reuse the coordinator's actual six-field receipt contract. The immutable
    # request above binds previous/target bundles; the result binds operation,
    # backup and schema. Do not invent a second, incompatible result schema.
    from desktop_upgrade_image import transaction_result

    final = transaction_result(json.dumps(final), "status", item["run_id"])
    if final["phase"] == "applied" and not final["backup_verified"]:
        raise ValueError("The applied native update has no verified backup")
    receipt = versions.load(root)
    expected = item["target"] if final["phase"] == "applied" else item["saved"]["previous"]
    return (
        final["phase"]
        if receipt["namespace_sha256"] == namespace and receipt["package"] == expected
        else None
    )


def completed(root, item):
    return outcome(root, item) == "applied"


def acknowledge_ready(root, current):
    from desktop_auto_update import publish

    item = pending(root)
    if item is None:
        return False
    if (
        versions.package_identity(current) != item["target"]
        or versions.load(root)["phase"] != "ready"
        or not completed(root, item)
    ):
        raise ValueError("The running version does not confirm completion of the native update")
    publish(root, item["run_id"], "applied")
    (root / MARKER).unlink()
    from desktop_upgrade_image import sync

    sync(root)
    return True


def resume(root, *, console, approved=False):
    """Explicit local recovery, never a Runner/agent action or an installer replay."""
    import desktop
    import desktop_linux_update as linux
    from desktop_auto_update import folder, publish
    from desktop_update_authority import authority
    from desktop_upgrade_image import UpgradeImage

    item = pending(root)
    if item is None:
        raise ValueError("No interrupted native update was found")
    if item["active"]:
        raise RuntimeError("The native updater is still running; it was not started again")
    installed, value = linux.retained(root, item["target"])
    if completed(root, item):
        publish(root, item["run_id"], "applied")
        return installed
    if not approved:
        if console:
            raise RuntimeError(
                "Reopen AI Station controls or use --resume-update to finish this interrupted update"
            )
        if (
            desktop.dialog(
                "--question",
                "--text=Finish the interrupted update to AI Station "
                + value["version"]
                + "?\n\nYour saved data and the previous application have been retained.",
                "--ok-label=Continue update",
                "--cancel-label=Later",
            )
            != 0
        ):
            return None
    helper = lock_file(folder(root, item["run_id"]), "helper.lock")
    try:
        try:
            fcntl.flock(helper, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("The original native updater is still active") from None
        fresh = pending(root)
        if fresh is None or fresh["saved"] != item["saved"] or fresh["target"] != item["target"]:
            raise ValueError("The interrupted update changed during local approval")
        if versions.load(root)["package"] not in (item["saved"]["previous"], item["target"]):
            raise ValueError("A different application version is now active; inspect it before continuing")
        engine = linux.attested_engine(root, desktop.ROOT)
        if engine.identity != item["engine"]:
            raise RuntimeError("Select the original local Docker connection before continuing this update")
        progress = desktop.Preparation(console, heading="Finishing your local update")
        try:
            config = root / "desktop.env"
            authority(root, item["run_id"], expected=item["saved"]["request"], idle=True, native_resume=True)
            publish(
                root,
                item["run_id"],
                "applying",
                native_resume_at=int(time.time()),
                native_resume_uid=os.geteuid(),
            )

            def finish():
                client = UpgradeImage(root, config, engine, item["saved"]["previous"], value, item["run_id"])
                state = client.state()
                if state["current"] is not None:
                    result = client.resume()  # Inspect the same durable command identity.
                elif not state["commands"]:
                    result = client.run("prepare")
                else:
                    result = client.run("status")
                if result["phase"] == "prepared":
                    progress.stage("Applying the verified update…")
                    client.run("publish")
                    result = client.finish(activate=True)
                elif result["phase"] == "applied":
                    result = client.finish(activate=True)
                elif result["phase"] == "aborted":
                    client.finish(activate=False)
                    if outcome(root, item) != "aborted":
                        raise ValueError(
                            "The previous application was not confirmed after aborting the update"
                        )
                    selected, _ = linux.retained(root, item["saved"]["previous"])
                    publish(
                        root,
                        item["run_id"],
                        "failed",
                        error="The update was aborted. Your previous application and saved data were retained.",
                    )
                    (root / MARKER).unlink()
                    from desktop_upgrade_image import sync

                    sync(root)
                    return selected
                else:
                    raise RuntimeError("The interrupted update still needs inspection; saved data was kept")
                publish(root, item["run_id"], "applied")
                return installed

            if desktop_live(root):

                def consent(previous, target):
                    if previous != item["saved"]["previous"] or target != item["target"]:
                        raise ValueError("The running desktop changed before native recovery")
                    authority(
                        root, item["run_id"], expected=item["saved"]["request"], idle=True, native_resume=True
                    )
                    return True

                with handoff(root, config, desktop.control_directory(root), value, consent):
                    return finish()
            with cold_owner(root):
                return finish()
        finally:
            progress.close()
    finally:
        os.close(helper)
