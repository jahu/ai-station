"""Native bundle selection/consent around the existing offline upgrade transaction."""

import fcntl
import hashlib
import json
import os
import platform
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import desktop
import desktop_versions as versions
from desktop_bridge import check as check_bridge
from desktop_bridge import private_directory, read_json
from desktop_update_owner import handoff, lock_file, require_lock
from desktop_upgrade_image import FENCE, UpgradeImage


def compatible(value):
    def version(text):
        components = tuple(map(int, text.split(".")))
        return components + (0,) * (3 - len(components))

    minimum = value.get("minimum_os")
    current = platform.mac_ver()[0]
    if (
        platform.system() != "Darwin"
        or value.get("platform") != "Darwin"
        or value.get("architecture") != platform.machine()
        or value.get("desktop_protocol") != desktop.DESKTOP_PROTOCOL
        or not isinstance(minimum, str)
        or not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?", minimum)
        or not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?", current)
        or version(current) < version(minimum)
    ):
        raise ValueError(
            "This update is incompatible with this Mac or its installed launcher. Choose the matching download."
        )
    versions.package_identity(value)


def chosen_resources(app):
    app = Path(app).resolve(strict=True)
    if app.suffix != ".app" or not app.is_dir():
        raise ValueError("Choose the downloaded AI Station application bundle")
    resources = app / "Contents/Resources"
    if resources.resolve(strict=True) != resources:
        raise ValueError("The selected application resources are redirected")
    return resources


def retained(root, package):
    path = root / "releases" / package["bundle_id"]
    versions.directory(path)
    value = desktop.manifest(path)
    compatible(value)
    if versions.package_identity(value) != package:
        raise ValueError("The retained application does not match the selected version")
    desktop.verify(path, value)
    return path, value


def active_payload(root, current):
    marker = root / versions.RECEIPT
    if not marker.exists() and not marker.is_symlink():
        return None
    receipt = versions.load(root)
    if receipt["package"] == versions.package_identity(current):
        return None
    config = root / "desktop.env"
    if versions.namespace(config)[1] != receipt["namespace_sha256"]:
        raise ValueError("The active application's storage changed; inspect it before starting")
    return retained(root, receipt["package"])[0]


def pending(root):
    config = root / "desktop.env"
    if not config.exists() and not config.is_symlink():
        return None
    data, namespace = versions.namespace(config)
    marker = data / "runtime" / FENCE
    if not marker.exists() and not marker.is_symlink():
        return None
    private_directory(marker.parent)
    fence = read_json(marker)
    identity = fence.get("operation_id")
    if not isinstance(identity, str) or str(UUID(identity)) != identity:
        raise ValueError("The pending update identity needs inspection")
    folder = root / "image-upgrades" / identity
    private_directory(folder.parent)
    private_directory(folder)
    request = read_json(folder / "request.json")
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    if (
        fence != {"operation_id": identity, "request_sha256": digest}
        or request.get("namespace_sha256") != namespace
    ):
        raise ValueError("The pending update belongs to changed input or storage")
    target = versions.package_identity(request.get("target"))
    previous = versions.package_identity(request.get("previous"))
    if request["target"] != target or request["previous"] != previous:
        raise ValueError("The pending version metadata is invalid")
    engine = request.get("engine")
    if not isinstance(engine, list) or len(engine) != 2 or not all(isinstance(v, str) for v in engine):
        raise ValueError("The pending local Docker connection needs inspection")
    installed, value = retained(root, target)
    return {
        "operation_id": identity,
        "installed": installed,
        "value": value,
        "previous": previous,
        "engine": tuple(engine),
    }


@contextmanager
def cold_handoff(root, *, owner_lock=None):
    descriptors = []
    try:
        for name in ("desktop-update.lock", "desktop.lock"):
            borrowed = name == "desktop.lock" and owner_lock is not None
            descriptor = (
                owner_lock if borrowed else lock_file(root, name, create=name == "desktop-update.lock")
            )
            descriptors.append((name, descriptor, borrowed))
            require_lock(root, name, descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("AI Station is still stopping or another update is active") from None
        yield
        for name, descriptor, _ in descriptors:
            require_lock(root, name, descriptor)
    finally:
        for _, descriptor, borrowed in reversed(descriptors):
            if not borrowed:
                os.close(descriptor)


def consent(previous, target, *, resume=False):
    text = (
        "Continue the interrupted AI Station update?\n\nYour saved data has been kept. "
        "The application will reopen after the update finishes."
        if resume
        else f"Install AI Station {target['version']}?\n\n"
        "AI Station will stop briefly. Your accounts, conversations, models and files are kept. "
        "Running tasks may be interrupted."
    )
    return (
        desktop.dialog(
            "--question",
            "--text=" + text,
            "--ok-label=" + ("Continue update" if resume else "Install update"),
            "--cancel-label=Cancel",
        )
        == 0
    )


def apply(client, progress):
    state = client.state()
    if state["current"] is not None:
        progress.stage("Checking the interrupted update…")
        result = client.resume()
    else:
        result = client.run("status")
    phase = result["phase"]
    if phase == "prepared":
        progress.stage("Installing the update…")
        client.run("publish")
        return client.finish(activate=True)
    if phase == "applied":
        return client.finish(activate=True)
    if phase == "aborted":
        return client.finish(activate=False)
    raise RuntimeError("The interrupted update needs inspection; saved data was kept")


def install_update(root, app, *, console, start, owner_lock=None):
    """Native entry only; caller checks consumer prerequisites and trusted launcher."""
    config = root / "desktop.env"
    if not config.exists():
        raise ValueError("Finish opening AI Station before installing an update")
    versions.namespace(config)
    existing = pending(root)
    if app is None and existing is None:
        raise ValueError("No retained update needs continuation")
    progress = desktop.Preparation(console, heading="Preparing your local update")
    try:
        if app is not None:
            source = chosen_resources(app)
            value = desktop.manifest(source)
            compatible(value)
            progress.stage("Checking the downloaded application…")
            desktop.verify(source, value)
            if existing is not None and versions.package_identity(value) != versions.package_identity(
                existing["value"]
            ):
                raise ValueError("Continue the same retained update before selecting another version")
            installed = desktop.install_copy(root, source, value)
        else:
            installed, value = existing["installed"], existing["value"]
        engine = desktop.select_engine(desktop.launch_environment())
        if existing is not None and engine.identity != existing["engine"]:
            raise RuntimeError(
                "Docker Desktop changed during the interrupted update. Inspect the original local installation before continuing."
            )
        log_path = root / "desktop.log"
        descriptor = os.open(
            log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        with os.fdopen(descriptor, "a") as log:
            from desktop_upgrade_image import data_info

            data_info(log_path)
            progress.stage("Preparing the verified application image…")
            desktop.import_image(installed, value, log, engine=engine)
            progress.stage("Checking local connections and saved data storage…")
            control = SimpleNamespace(stop_requested=threading.Event())
            if not check_bridge(desktop.ROOT, root, config, value, engine, log, control):
                return None
            if existing is not None:
                with cold_handoff(root, owner_lock=owner_lock):
                    if not consent(existing["previous"], versions.package_identity(value), resume=True):
                        return None
                    client = UpgradeImage(
                        root, config, engine, existing["previous"], value, existing["operation_id"]
                    )
                    result = apply(client, progress)
                    selected = (
                        installed if result["phase"] == "applied" else retained(root, existing["previous"])[0]
                    )
                    progress.stage("Opening AI Station…")
                    progress.close()
                    return start(selected)
            with handoff(root, config, desktop.control_directory(root), value, consent) as owner:
                if owner is None:
                    return None
                progress.stage("Protecting your saved history…")
                client = UpgradeImage(root, config, engine, owner["previous"], value, str(uuid4()))
                client.run("prepare")
                progress.stage("Installing the update…")
                client.run("publish")
                client.finish(activate=True)
                progress.stage("Opening the updated AI Station…")
                progress.close()
                return start(installed)
    finally:
        progress.close()
