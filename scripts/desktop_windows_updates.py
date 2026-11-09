"""Finite Windows-owner update journal inside the dedicated WSL guest.

Windows installation remains behind platform qualification. No Windows command,
host path, distro name or arbitrary URL can be supplied through this component.
"""

import argparse
import hashlib
import json
import os
import platform
import pwd
import re
import stat
import sys
import time
from pathlib import Path
from uuid import UUID

# The independently launched -I helper cannot inherit its script directory.
# Match the desktop launcher: import only siblings of this verified package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop  # noqa: E402
import desktop_auto_update as owner  # noqa: E402
import desktop_versions as versions  # noqa: E402
from ai_station_runner.desktop_update_channel import command  # noqa: E402
from ai_station_runner.station_release_metadata import update_package, version_number  # noqa: E402
from desktop_update_authority import authority  # noqa: E402
from desktop_upgrade_image import write  # noqa: E402

ATTACHMENT = "windows-update-channel.json"
PENDING = "windows-update-pending.json"


def guest():
    if (
        platform.system() != "Linux"
        or "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower()
    ):
        return False
    account = pwd.getpwuid(os.geteuid())
    return os.getuid() == os.geteuid() and account.pw_name == "station" and account.pw_dir == "/home/station"


def compatible(value):
    if (
        not guest()
        or value.get("platform") != "Linux"
        or value.get("architecture") != "x86_64"
        or value.get("desktop_protocol") != desktop.DESKTOP_PROTOCOL
        or value.get("release_version") != value.get("version")
        or value.get("source_dirty") is not False
    ):
        raise ValueError("Automatic Windows updates require the dedicated stable desktop guest")
    versions.package_identity(value)
    version_number(value["version"])


def enabled(root, current):
    if not guest():
        return False
    try:
        compatible(current)
        # Retained bundle verification/copying can outlast interactive presence.
        # Keep lifecycle/readiness wired to this exact installation; capability
        # and prepare/apply handlers separately require fresh native permission.
        channel(root, current, fresh=False)
    except (OSError, ValueError):
        return False
    return True


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Use a canonical native update identity")
    return value


def bind(root, current, value):
    """Called only by the fixed native guest control, never by the Runner API."""
    compatible(current)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "channel_id", "host_manifest_sha256", "version"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["version"] != current["version"]
        or not isinstance(value["host_manifest_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["host_manifest_sha256"])
    ):
        raise ValueError("The Windows owner does not match the installed guest")
    uuid(value["channel_id"])
    if desktop.WSL_UPDATE_PENDING.exists() or desktop.WSL_UPDATE_PENDING.is_symlink():
        raise ValueError("Finish the original preserving guest update before binding its new owner")
    path = root / ATTACHMENT
    if path.exists() or path.is_symlink():
        previous = owner.read(path)
        if previous.get("channel_id") != value["channel_id"]:
            raise ValueError("The Windows installation identity changed; inspect it before continuing")
    write(path, {**value, "updated_at": time.time()})
    return {"channel_id": value["channel_id"], "version": current["version"]}


def channel(root, current, *, fresh=True):
    value = owner.read(root / ATTACHMENT)
    if (
        set(value) != {"schema", "channel_id", "host_manifest_sha256", "version", "updated_at"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["version"] != current["version"]
        or not isinstance(value["host_manifest_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["host_manifest_sha256"])
        or type(value["updated_at"]) not in (int, float)
        or fresh
        and not -5 <= time.time() - value["updated_at"] <= 60
    ):
        raise ValueError("Reopen the Windows desktop controls before updating")
    uuid(value["channel_id"])
    return value


def ready(root, current, config, instance_id):
    """After actual guest health, and only for its verified native host binding."""
    compatible(current)
    # Cold startup can outlast the short interactive-update presence lease.
    # Recording actual health is not update permission; new operations still
    # require a fresh native channel in capabilities/prepare/apply.
    channel(root, current, fresh=False)
    if not isinstance(instance_id, str) or not re.fullmatch(r"[a-f0-9]{32}", instance_id):
        raise ValueError("The Windows guest supervisor identity is invalid")
    namespace = versions.namespace(config)[1]
    marker = root / versions.RECEIPT
    if marker.exists() or marker.is_symlink():
        previous = versions.load(root)
        if previous["namespace_sha256"] != namespace:
            raise ValueError("The Windows guest data namespace changed")
    # Only the native Windows owner can bind a newly installed guest version.
    # That binding follows the preserving root-owned guest update, not an API
    # caller's claimed target or a model-written artifact.
    versions.save(
        root,
        {
            "schema": 1,
            "phase": "ready",
            "package": versions.package_identity(current),
            "namespace_sha256": namespace,
            "owner_instance_id": instance_id,
            "last_ready_at": int(time.time()),
        },
    )


def target(snapshot):
    package = snapshot["packages"]["windows-x64"]
    return {
        "version": snapshot["version"],
        "asset_id": package["id"],
        "installer_sha256": package["sha256"],
        "installer_bytes": package["size_bytes"],
    }


class WindowsUpdates(owner.DesktopUpdates):
    platform = "windows-x64"
    helper = "desktop_windows_updates.py"
    helper_phases = {"queued", "downloading", "preparing"}

    def validate(self, value):
        compatible(value)

    def handle(self, value):
        value = command(value)
        if value == {"action": "updates.capabilities"}:
            try:
                channel(self.root, self.value)
            except (OSError, ValueError):
                return {"installed": False, "platform": self.platform, "version": self.value["version"]}
        elif value.get("action") in {"updates.prepare", "updates.apply"}:
            try:
                channel(self.root, self.value)
            except (OSError, ValueError):
                if value["action"] != "updates.prepare":
                    raise
                return self.refuse(
                    value["run_id"],
                    value["request"],
                    "Reopen the Windows desktop controls before updating. Your app was kept.",
                )
            if value["action"] == "updates.prepare":
                pending = self.root / PENDING
                if pending.exists() or pending.is_symlink():
                    previous = owner.read(pending)
                    old_id = uuid(previous.get("run_id"))
                    if old_id != value["run_id"] and self.inspect(old_id)["phase"] not in {
                        "succeeded",
                        "failed",
                        "canceled",
                    }:
                        return self.refuse(
                            value["run_id"],
                            value["request"],
                            "Another Windows update is still being inspected. Your app was not changed.",
                        )
        result = super().handle(value)
        if value["action"] == "updates.prepare" and result["phase"] not in {
            "failed",
            "canceled",
            "succeeded",
        }:
            saved = owner.request(self.root, value["run_id"])
            attachment = channel(self.root, self.value)
            write(self.root / PENDING, pending_identity(saved, attachment["channel_id"]))
        return result

    def inspect(self, run_id):
        saved, stage = owner.request(self.root, run_id), owner.state(self.root, run_id)
        phase = stage["phase"]
        if phase == "applied":
            attachment = channel(self.root, self.value, fresh=False)
            receipt = versions.load(self.root)
            proof = stage.get("host_completion")
            if (
                isinstance(proof, dict)
                and proof.get("channel_id") == attachment["channel_id"]
                and proof.get("host_manifest_sha256") == attachment["host_manifest_sha256"]
                and proof.get("data_preserved") is True
                and type(proof.get("backup_available")) is bool
                and proof.get("version") == self.value["version"]
                and proof.get("installer_sha256") == stage.get("target", {}).get("installer_sha256")
                and self.value["version"] == stage.get("target", {}).get("version")
                and receipt["phase"] == "ready"
                and receipt["package"] == versions.package_identity(self.value)
                and receipt["namespace_sha256"] == saved["namespace_sha256"]
                and not desktop.WSL_UPDATE_PENDING.exists()
                and not desktop.WSL_UPDATE_PENDING.is_symlink()
            ):
                phase = "succeeded"
        phase = self.orphaned_phase(run_id, saved, stage, phase)
        pending = self.root / PENDING
        if phase in {"failed", "canceled", "succeeded"} and (pending.exists() or pending.is_symlink()):
            value = owner.read(pending)
            if value.get("run_id") == run_id:
                # Finalization removes only this operation's verified pointer.
                if value != pending_identity(saved, value.get("channel_id")):
                    raise ValueError("The Windows update pointer changed before finalization")
                pending.unlink()
        return {
            "run_id": run_id,
            "request": saved["request"],
            "phase": phase,
            **{
                key: stage[key]
                for key in ("target", "error", "size_bytes", "downloaded_bytes")
                if key in stage
            },
        }


def pending_identity(saved, channel_id):
    return {
        "schema": 1,
        "run_id": saved["run_id"],
        "channel_id": uuid(channel_id),
        "request_sha256": hashlib.sha256(
            json.dumps(saved, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def bound(root, channel_id):
    value = owner.read(root / ATTACHMENT)
    if value.get("channel_id") != uuid(channel_id):
        raise ValueError("This request belongs to another Windows installation")
    return value


def pending_operation(root, channel_id):
    bound(root, channel_id)
    path = root / PENDING
    if not path.exists() and not path.is_symlink():
        return None
    marker = owner.read(path)
    saved = owner.request(root, uuid(marker.get("run_id")))
    if saved["request"]["platform"] != "windows-x64" or marker != pending_identity(saved, channel_id):
        raise ValueError("The pending Windows update no longer matches its original request")
    return saved


def poll(root, current, value):
    if not isinstance(value, dict) or set(value) != {"channel_id"}:
        raise ValueError("Windows update polling accepts only its installation identity")
    attachment = bound(root, value["channel_id"])
    # Native polling renews presence; the installer may legitimately be moving
    # between guest versions. It grants no new installation authority.
    write(root / ATTACHMENT, {**attachment, "updated_at": time.time()})
    saved = pending_operation(root, value["channel_id"])
    if saved is None:
        return {"pending": None}
    result = WindowsUpdates(root, desktop.ROOT, current).inspect(saved["run_id"])
    return {"pending": result, "channel_id": value["channel_id"]}


def authorize_guest_update(root, value):
    """Read-only continuation proof for the fixed privileged WSL updater."""
    if not isinstance(value, dict) or set(value) != {"channel_id", "run_id", "fingerprint"}:
        raise ValueError("Invalid original Windows update continuation")
    saved = pending_operation(root, value["channel_id"])
    if (
        saved is None
        or saved["run_id"] != uuid(value["run_id"])
        or saved["request"]["fingerprint"] != value["fingerprint"]
        or owner.state(root, saved["run_id"])["phase"] not in {"applying", "inspection_required"}
    ):
        raise ValueError("The Windows owner has not started this exact approved update")
    proof = authority(root, saved["run_id"], expected=saved["request"], idle=True, native_resume=True)
    return {
        "run_id": saved["run_id"],
        "namespace_sha256": proof["namespace_sha256"],
        "data_root": str(versions.namespace(root / "desktop.env")[0]),
        "target_version": owner.state(root, saved["run_id"])["target"]["version"],
    }


def host_result(root, current, value):
    fields = {"channel_id", "run_id", "fingerprint", "phase", "proof"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid native Windows update result")
    saved = pending_operation(root, value["channel_id"])
    if saved is None and value["phase"] == "applied":
        previous = owner.request(root, uuid(value["run_id"]))
        completed = owner.state(root, previous["run_id"])
        if (
            previous["request"]["fingerprint"] == value["fingerprint"]
            and completed["phase"] == "applied"
            and isinstance(value["proof"], dict)
            and completed.get("host_completion") == {**value["proof"], "channel_id": value["channel_id"]}
        ):
            return WindowsUpdates(root, desktop.ROOT, current).inspect(previous["run_id"])
    if (
        saved is None
        or saved["run_id"] != uuid(value["run_id"])
        or saved["request"]["fingerprint"] != value["fingerprint"]
    ):
        raise ValueError("The native result belongs to another approved update")
    stage = owner.state(root, saved["run_id"])
    phase = value["phase"]
    if phase == "applying":
        if value["proof"] is not None or stage["phase"] not in {"apply_requested", "applying"}:
            raise ValueError("The Windows package was not approved for activation")
        authority(
            root,
            saved["run_id"],
            expected=saved["request"],
            idle=True,
            **({"native_resume": True} if stage["phase"] == "applying" else {}),
        )
        if stage["phase"] != "applying":
            owner.publish(root, saved["run_id"], "applying", native_host_started_at=time.time())
    elif phase == "applied":
        proof = value["proof"]
        if (
            stage["phase"] not in {"applying", "applied", "inspection_required"}
            or not isinstance(proof, dict)
            or set(proof)
            != {"host_manifest_sha256", "version", "installer_sha256", "data_preserved", "backup_available"}
            or proof["version"] != stage.get("target", {}).get("version")
            or proof["version"] != current["version"]
            or proof["installer_sha256"] != stage.get("target", {}).get("installer_sha256")
            or proof["data_preserved"] is not True
            or type(proof["backup_available"]) is not bool
            or not isinstance(proof["host_manifest_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", proof["host_manifest_sha256"])
        ):
            raise ValueError("The native Windows owner has not confirmed the exact preserving update")
        attachment = channel(root, current)
        if attachment["host_manifest_sha256"] != proof["host_manifest_sha256"]:
            raise ValueError("The completed update belongs to another native Windows payload")
        owner.publish(
            root, saved["run_id"], "applied", host_completion={**proof, "channel_id": value["channel_id"]}
        )
    elif phase in {"failed", "inspection_required"}:
        if value["proof"] is not None or stage["phase"] in {"applied", "canceled", "failed"}:
            raise ValueError("The native Windows result cannot replace a completed operation")
        if stage["phase"] == "applying":
            phase = "inspection_required"  # Unknown installation acknowledgement is never replayed.
        owner.publish(
            root,
            saved["run_id"],
            phase,
            error="The native Windows update needs attention. Your saved files were retained.",
        )
    else:
        raise ValueError("Unsupported native Windows update result")
    return WindowsUpdates(root, desktop.ROOT, current).inspect(saved["run_id"])


def export_package(root, current, value, *, output):
    if not isinstance(value, dict) or set(value) != {"channel_id", "run_id"}:
        raise ValueError("Package export accepts only its approved native update identity")
    saved = pending_operation(root, value["channel_id"])
    if saved is None or saved["run_id"] != uuid(value["run_id"]):
        raise ValueError("This Windows package was not prepared for the native owner")
    stage = owner.state(root, saved["run_id"])
    if stage["phase"] not in {"ready", "apply_requested"}:
        raise ValueError("The Windows update is not ready to transfer")
    target = stage.get("target", {})
    version_number(target.get("version"))
    expected_name = "AI-Station-" + str(target.get("version")) + "-windows-x64-Setup.exe"
    if stage.get("package_name") != expected_name:
        raise ValueError("The Windows package name no longer matches its approved target")
    package = root / "update-downloads" / expected_name
    last = 0.0

    def check():
        nonlocal last
        if time.monotonic() - last >= 1:
            proof = authority(
                root, saved["run_id"], expected=saved["request"], idle=stage["phase"] == "apply_requested"
            )
            if proof["canceled"]:
                raise InterruptedError("The Windows update transfer was canceled")
            attachment = bound(root, value["channel_id"])
            write(root / ATTACHMENT, {**attachment, "updated_at": time.time()})
            last = time.monotonic()

    versions.directory(package.parent)
    versions.canonical(package)
    header = {
        "run_id": saved["run_id"],
        "channel_id": value["channel_id"],
        "request": saved["request"],
        "target": target,
    }
    frame = json.dumps(header, separators=(",", ":")).encode() + b"\n"
    if len(frame) > 8192:
        raise ValueError("The native package frame exceeds its bound")
    descriptor = os.open(package, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or before.st_size != target.get("installer_bytes")
        ):
            raise ValueError("The Windows package is no longer an owned verified file")
        digest = hashlib.sha256()
        hashed = 0
        while chunk := source.read(65536):
            check()
            hashed += len(chunk)
            if hashed > before.st_size:
                raise ValueError("The Windows package changed during verification")
            digest.update(chunk)
        if digest.hexdigest() != target.get("installer_sha256"):
            raise ValueError("The Windows package no longer matches the approved bytes")
        source.seek(0)
        output.write(frame)
        count = 0
        while chunk := source.read(65536):
            check()
            count += len(chunk)
            if count > before.st_size:
                raise ValueError("The Windows package changed during transfer")
            output.write(chunk)
        after = os.fstat(source.fileno())
        if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("The Windows package changed during transfer")
    output.flush()


def prepare(root, run_id):
    """Only stage verified publisher bytes. The native Windows owner applies them."""
    import fcntl

    from desktop_release_download import download
    from desktop_update_owner import lock_file

    saved = owner.request(root, run_id)
    if saved["request"]["platform"] != "windows-x64":
        raise ValueError("This update belongs to a different native platform")
    descriptor = lock_file(owner.folder(root, run_id), "helper.lock", create=True)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if owner.state(root, run_id)["phase"] != "queued":
            return

        def check():
            if (
                authority(root, run_id, expected=saved["request"])["canceled"]
                or owner.state(root, run_id)["phase"] == "canceled"
            ):
                raise InterruptedError("The Windows update was canceled before activation")

        last = 0.0

        def progress(done, total):
            nonlocal last
            if time.monotonic() - last > 1 or done == total:
                owner.publish(root, run_id, "downloading", downloaded_bytes=done, size_bytes=total)
                last = time.monotonic()

        try:
            owner.verify_source(root, run_id, saved, check, validate=compatible)
            owner.publish(root, run_id, "downloading")
            coordinates = saved["request"]
            _, snapshot = download(
                root,
                coordinates["release_id"],
                coordinates["fingerprint"],
                coordinates["current_version"],
                "windows-x64",
                check=check,
                progress=progress,
            )
            check()
            package = update_package(snapshot, coordinates["current_version"], "windows-x64")
            owner.publish(root, run_id, "ready", target=target(snapshot), package_name=package["name"])
        except InterruptedError:
            owner.publish(root, run_id, "canceled")
        except Exception:
            owner.publish(
                root,
                run_id,
                "failed",
                error="The Windows update could not be prepared. Your current app was kept.",
            )
            raise
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    compatible(desktop.manifest(desktop.ROOT))
    prepare(desktop.state_root(), uuid(args.run_id))
