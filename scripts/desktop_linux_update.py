"""Native Linux activation around the existing preserving offline image transaction."""

import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import desktop
import desktop_versions as versions
from ai_station_runner.station_release_metadata import version_number
from desktop_engine import DockerEngine


def supported(value):
    return (
        platform.system() == "Linux"
        and platform.machine().lower() in {"x86_64", "amd64"}
        and "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower()
        and value.get("platform") == "Linux"
        and value.get("architecture") == "x86_64"
        and value.get("desktop_protocol") == desktop.DESKTOP_PROTOCOL
    )


def compatible(value):
    if not supported(value):
        raise ValueError("This update needs the installed native Linux x86-64 desktop client")
    versions.package_identity(value)
    version_number(value["version"])
    if value.get("release_version") != value["version"] or value.get("source_dirty") is not False:
        raise ValueError("Automatic updates require a clean stable desktop release")


def enabled(value):
    if not supported(value) or "release_version" not in value:
        return False
    compatible(value)
    return True


def active_payload(root, current):
    marker = root / versions.RECEIPT
    if not marker.exists() and not marker.is_symlink():
        return None
    receipt = versions.load(root)
    config = root / "desktop.env"
    if receipt["namespace_sha256"] != versions.namespace(config)[1]:
        raise ValueError("The active desktop data changed; inspect it before starting")
    if receipt["package"] == versions.package_identity(current):
        return None
    source = root / "releases" / receipt["package"]["bundle_id"]
    versions.directory(source)
    value = desktop.manifest(source)
    compatible(value)
    if versions.package_identity(value) != receipt["package"]:
        raise ValueError("The active Linux desktop package no longer matches its receipt")
    desktop.verify(source, value)
    return source


def ready(root, package, config, owner):
    """The trusted supervisor calls only after its verified image becomes healthy.

    First supporting installs may already contain pre-updater data. Record this
    running version after normal startup, never adopt a version before starting
    its verified services or overwrite a different active version.
    """
    compatible(package)
    identity = versions.package_identity(package)
    if not isinstance(owner, str) or len(owner) != 32 or any(c not in "0123456789abcdef" for c in owner):
        raise ValueError("The Linux desktop owner identity is invalid")
    namespace = versions.namespace(config)[1]
    marker = root / versions.RECEIPT
    if marker.exists() or marker.is_symlink():
        previous = versions.load(root)
        if previous["package"] != identity or previous["namespace_sha256"] != namespace:
            raise ValueError("A different active version requires its preserving update transaction")
    versions.save(
        root,
        {
            "schema": 1,
            "phase": "ready",
            "package": identity,
            "namespace_sha256": namespace,
            "owner_instance_id": owner,
            "last_ready_at": int(time.time()),
        },
    )


def local_engine(environment):
    """Pin the installed local Docker context before importing or stopping anything."""
    binary = shutil.which("docker", path=environment.get("PATH"))
    if not binary:
        raise RuntimeError("The installed local Docker connection is unavailable")
    binary = str(Path(binary).resolve(strict=True))
    context = environment.get("DOCKER_CONTEXT")
    endpoint = environment.get("DOCKER_HOST") if not context else None
    if not endpoint:
        result = subprocess.run(
            [
                binary,
                "context",
                "inspect",
                *([context] if context else []),
                "--format",
                '{{(index .Endpoints "docker").Host}}',
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        endpoint = result.stdout.strip()
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "unix"
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise ValueError("Updates require the existing local Unix Docker connection")
    socket = Path(parsed.path)
    if socket.resolve(strict=True) != socket:
        raise ValueError("The local Docker connection must not be redirected")
    clean = {
        key: value
        for key, value in environment.items()
        if not key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_"))
    }
    clean["DOCKER_HOST"] = endpoint
    return DockerEngine((binary, "--host", endpoint), clean, (binary, endpoint))


def retain_package(root, package, snapshot, *, check=lambda: None):
    """Extract only verified official Debian bytes, without root or package scripts."""
    from desktop_release_download import digest

    spec = snapshot["packages"]["linux-amd64"]
    if digest(package, check) != (spec["size_bytes"], spec["sha256"]):
        raise ValueError("The official update package changed before extraction")
    compatible_version = snapshot["version"]
    folder = root / "update-staging"
    folder.mkdir(mode=0o700, exist_ok=True)
    if versions.directory(folder).st_mode & 0o077:
        raise ValueError("Update extraction requires private native storage")
    with tempfile.TemporaryDirectory(prefix="package-", dir=folder) as temporary:
        target = Path(temporary)
        dpkg = shutil.which("dpkg-deb", path=os.defpath)
        if not dpkg:
            raise RuntimeError("The installed Debian package reader is unavailable")
        with subprocess.Popen(
            [dpkg, "--fsys-tarfile", str(package)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ) as proc:
            try:
                total, entries = 0, 0
                with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                    for member in archive:
                        check()
                        entries += 1
                        total += max(member.size, 0)
                        if entries > 60000 or total > 12 * 1024**3:
                            raise ValueError("The update extraction exceeded its size bound")
                        if shutil.disk_usage(target).free < max(member.size, 0) + 512 * 1024**2:
                            raise ValueError("Not enough free space to prepare the update safely")
                        archive.extract(member, target, filter="data")
                if proc.wait(timeout=15):
                    raise ValueError("The official update package could not be extracted")
            finally:
                if proc.poll() is None:
                    proc.terminate()  # Only our immediate, unreaped package reader.
                    proc.wait(timeout=15)
        source = target / "usr/lib/ai-station"
        if source.resolve(strict=True) != source:
            raise ValueError("The update application directory is redirected")
        value = desktop.manifest(source)
        compatible(value)
        if value["version"] != compatible_version:
            raise ValueError("The downloaded package contains a different release version")
        check()
        retained = desktop.install_copy(root, source, value)
        return retained, value


def apply(root, installed, target, operation_id, *, consent):
    """Called by an independent native owner after its Run's idle fence is ready."""
    from desktop_update_owner import handoff
    from desktop_upgrade_image import UpgradeImage, data_info

    compatible(target)
    if desktop.manifest(installed) != target:
        raise ValueError("The retained update manifest changed before activation")
    desktop.verify(installed, target)
    config = root / "desktop.env"
    engine = local_engine(desktop.launch_environment())
    log_path = root / "desktop.log"
    descriptor = os.open(
        log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    with os.fdopen(descriptor, "a") as log:
        data_info(log_path)
        desktop.import_image(installed, target, log, engine=engine)
        with handoff(root, config, desktop.control_directory(root), target, consent) as owner:
            if owner is None:
                return False
            client = UpgradeImage(root, config, engine, owner["previous"], target, operation_id)
            client.run("prepare")
            client.run("publish")
            client.finish(activate=True)
    return True
