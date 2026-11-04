"""Private native desktop receipts; no migration, process or network authority."""

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

RECEIPT = "desktop-version.json"
HEX = r"[a-f0-9]{64}"
OWNER = r"[a-f0-9]{32}"


def package_identity(value):
    """Project verified package metadata, excluding inventory and mutable settings."""
    if not isinstance(value, dict):
        raise ValueError("Desktop package identity is invalid")
    result = {key: value.get(key) for key in ("bundle_id", "image_id", "version", "source_epoch")}
    for key, pattern in (
        ("bundle_id", HEX),
        ("image_id", "sha256:" + HEX),
        ("version", r"[A-Za-z0-9][A-Za-z0-9.+-]{0,63}"),
    ):
        if not isinstance(result[key], str) or not re.fullmatch(pattern, result[key]):
            raise ValueError("Desktop package identity is invalid")
    if type(result["source_epoch"]) is not int or not 0 <= result["source_epoch"] < 2**63:
        raise ValueError("Desktop package source epoch is invalid")
    return result


def canonical(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("Desktop installation paths must be canonical and absolute")
    return path


def directory(path):
    path = canonical(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("Desktop installation directory must remain owned and non-shared")
    return info


def read_private(path, limit):
    canonical(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("Desktop receipt/configuration must remain a private owned file")
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Desktop receipt/configuration exceeded its bound")
    return value


def base_namespace(config):
    from dotenv import dotenv_values

    directory(config.parent)
    # No environment interpolation or dotenv search outside this exact config.
    from io import StringIO

    values = dotenv_values(stream=StringIO(read_private(config, 65536).decode()), interpolate=False)
    data = canonical(values.get("AI_STATION_DATA_HOST_PATH") or "")
    info = directory(data)
    socket = canonical(values.get("AI_STATION_RUNNER_SOCKET") or "")
    if socket.name != "runner.sock" or values.get("AI_STATION_ACCESS_PROFILE") != "accounts":
        raise ValueError("Desktop installation coordinates are invalid")
    # The private runtime directory can disappear across reboot. Validate its
    # nearest surviving ancestor without making an ephemeral inode its identity.
    parent = socket.parent
    while not parent.exists():
        parent = parent.parent
    directory(parent)
    project = values.get("COMPOSE_PROJECT_NAME") or ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise ValueError("Desktop Compose project is invalid")
    database = canonical(data / "db/ai-station.sqlite")
    if (data / "db").exists():
        directory(data / "db")
    if database.exists():
        db_info = database.lstat()
        if (
            not stat.S_ISREG(db_info.st_mode)
            or db_info.st_uid != os.geteuid()
            or db_info.st_nlink != 1
            or db_info.st_mode & 0o022
        ):
            raise ValueError("Desktop database must remain an owned regular file")
    frozen = {
        "data": str(data),
        "data_device": info.st_dev,
        "data_inode": info.st_ino,
        "uid": os.geteuid(),
        "project": project,
        "access": "accounts",
        "runner_socket": str(socket),
    }
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    return data, digest


def database_reference(root, base):
    folder = root / "database-storage"
    if not folder.exists() and not folder.is_symlink():
        return None  # Linux/WSL packages need no Mac-only helper imports.
    from macos_database_storage import reference

    return reference(root, base)


def namespace(config):
    data, base = base_namespace(config)
    storage = database_reference(config.parent, base)
    if storage is None:
        return data, base  # Preserve existing Linux/WSL identity byte for byte.
    return data, hashlib.sha256(
        json.dumps({"base": base, "database_storage": storage}, sort_keys=True).encode()
    ).hexdigest()


def load(root):
    directory(root)
    value = json.loads(read_private(root / RECEIPT, 8192))
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema", "phase", "package", "namespace_sha256", "owner_instance_id", "last_ready_at"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["phase"] not in ("starting", "ready")
        or package_identity(value["package"]) != value["package"]
        or not isinstance(value["namespace_sha256"], str)
        or not re.fullmatch(HEX, value["namespace_sha256"])
        or not isinstance(value["owner_instance_id"], str)
        or not re.fullmatch(OWNER, value["owner_instance_id"])
        or (
            value["last_ready_at"] is not None
            and (type(value["last_ready_at"]) is not int or not 0 <= value["last_ready_at"] < 2**63)
        )
        or value["phase"] == "ready"
        and value["last_ready_at"] is None
    ):
        raise ValueError("Desktop version receipt is invalid")
    return value


def save(root, value):
    # The desktop caller holds its native owner lock for this whole operation.
    directory(root)
    fd, temporary = tempfile.mkstemp(prefix=".desktop-version-", dir=root)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / RECEIPT)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def begin(root, package, config, owner, *, storage=None):
    package = package_identity(package)
    if not isinstance(owner, str) or not re.fullmatch(OWNER, owner):
        raise ValueError("Desktop owner identity is invalid")
    data, digest = namespace(config)
    try:
        previous = load(root)
    except FileNotFoundError:
        if (data / "db/ai-station.sqlite").exists():
            raise ValueError(
                "Existing desktop data needs a verified version receipt before updating"
            ) from None
        expected_storage = database_reference(root, base_namespace(config)[1])
        if expected_storage is not None:
            if storage is None or storage.identity(allow_pending_readonly=True) != expected_storage:
                raise ValueError("A new volume installation needs its attested empty-database check")
            storage.assert_empty()
            if namespace(config) != (data, digest):
                raise ValueError("Desktop storage changed before first-version publication")
        previous = {"last_ready_at": None}
    else:
        if previous["package"] != package or previous["namespace_sha256"] != digest:
            raise ValueError("Changed desktop version or storage needs an explicit verified upgrade")
    value = {
        "schema": 1,
        "phase": "starting",
        "package": package,
        "namespace_sha256": digest,
        "owner_instance_id": owner,
        "last_ready_at": previous["last_ready_at"],
    }
    save(root, value)
    return value


def ready(root, package, config, owner):
    value = load(root)
    _, digest = namespace(config)
    if (
        value["phase"] != "starting"
        or value["package"] != package_identity(package)
        or value["namespace_sha256"] != digest
        or value["owner_instance_id"] != owner
    ):
        raise ValueError("Desktop readiness belongs to another version, storage or owner")
    value.update(phase="ready", last_ready_at=int(time.time()))
    save(root, value)
    return value


def attest(root, config, status, identity):
    value = load(root)
    _, digest = namespace(config)
    if (
        not isinstance(status, dict)
        or set(status) != {"instance_id", "ready", "background", "stopping"}
        or status["ready"] is not True
        or status["stopping"] is not False
        or type(status["background"]) is not bool
        or not isinstance(identity, dict)
        or set(identity) != {"instance_id", "package"}
        or value["phase"] != "ready"
        or value["namespace_sha256"] != digest
        or value["owner_instance_id"] != status["instance_id"]
        or value["owner_instance_id"] != identity["instance_id"]
        or value["package"] != identity["package"]
    ):
        raise ValueError("The ready desktop version and live owner do not match")
    return value["package"].copy()
