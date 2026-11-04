"""Private native snapshot files. No native SQLite, host commands or web entry."""

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath

import desktop_versions as versions
from desktop_bridge import private_directory

# Reproducible caches and live execution/lock authority are never restored.
EXCLUDED = frozenset({"db", "runtime", "cache", "desktop-upgrades", "recovery"})
LIMIT = 64 * 1024**2


def relative(value):
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("Snapshot paths must be portable relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or ".." in path.parts or path.parts[0].casefold() in EXCLUDED:
        raise ValueError("Snapshot paths must stay inside retained application files")
    return path


def signature(info):
    return [
        getattr(info, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
            "st_mode",
            "st_uid",
            "st_nlink",
        )
    ]


def ordinary(info, *, directory=False):
    if (
        info.st_uid != os.geteuid()
        or info.st_mode & 0o022
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("Snapshot storage must remain ordinary owned non-shared-write files/directories")


def catalog(root, *, exclusions=True):
    root = versions.canonical(root)
    versions.directory(root)
    result = {}

    def walk(fd, path, prefix=""):
        try:
            opened = os.fstat(fd)
            ordinary(opened, directory=True)
            names = sorted(os.listdir(fd))
            for name in names:
                if exclusions and not prefix and name.casefold() in EXCLUDED:
                    continue
                key = name if not prefix else prefix + "/" + name
                relative(key)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if info.st_dev != opened.st_dev:
                    raise ValueError("A retained snapshot cannot cross an unexpected filesystem mount")
                entry = {"signature": signature(info)}
                if stat.S_ISDIR(info.st_mode):
                    ordinary(info, directory=True)
                    entry["kind"] = "directory"
                    result[key] = entry
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    if signature(os.fstat(child)) != signature(info):
                        os.close(child)
                        raise ValueError("Snapshot directory changed before opening")
                    walk(child, path / name, key)
                elif stat.S_ISLNK(info.st_mode):
                    text = os.readlink(name, dir_fd=fd)
                    candidate = Path(os.path.normpath(path / text))
                    inside = candidate.is_relative_to(root)
                    if inside:
                        resolved = candidate.resolve()
                        parts = resolved.relative_to(root).parts if resolved.is_relative_to(root) else ()
                        inside = resolved.is_relative_to(root) and (
                            not parts or parts[0].casefold() not in EXCLUDED
                        )
                    entry.update(
                        kind="symlink" if inside else "external_reference",
                        target=os.path.relpath(candidate, path) if inside else text,
                    )
                    result[key] = entry
                else:
                    ordinary(info)
                    entry["kind"] = "file"
                    result[key] = entry
            if sorted(os.listdir(fd)) != names or signature(os.fstat(fd)) != signature(opened):
                raise ValueError("Snapshot directory changed during inspection")
        finally:
            os.close(fd)

    walk(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW), root)
    return result


def write_json(path, value):
    write_bytes(path, json.dumps(value, sort_keys=True).encode())


def write_bytes(path, value):
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        versions.read_private(path, LIMIT)
    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        sync(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def file_hash(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        ordinary(info)
        result = hashlib.file_digest(source, "sha256").hexdigest()
        if signature(os.fstat(source.fileno())) != signature(info) or signature(path.lstat()) != signature(
            info
        ):
            raise ValueError("Snapshot file changed while reading")
        return result


def open_relative(root, key):
    parts = relative(key).parts
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        ordinary(os.fstat(fd), directory=True)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            ordinary(os.fstat(fd), directory=True)
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)


def source_hash(root, key, expected):
    with os.fdopen(open_relative(root, key), "rb") as source:
        if signature(os.fstat(source.fileno())) != expected:
            raise ValueError("Snapshot source changed before reading")
        result = hashlib.file_digest(source, "sha256").hexdigest()
        if signature(os.fstat(source.fileno())) != expected:
            raise ValueError("Snapshot source changed during reading")
        return result


def copy_file(root, key, target, expected, staging, *, canceled=lambda: False):
    if target.exists() or target.is_symlink():
        if source_hash(root, key, expected) != file_hash(target):
            raise ValueError("Existing snapshot output changed; partial bytes preserved")
        return file_hash(target)
    temporary = staging / (
        hashlib.sha256(str(target.relative_to(staging.parent)).encode()).hexdigest() + ".part"
    )
    if temporary.exists() or temporary.is_symlink():
        ordinary(temporary.lstat())
        temporary.unlink()  # Only the fixed unpublished scratch entry of this operation.
    opened = open_relative(root, key)
    with os.fdopen(opened, "rb") as reader:
        if signature(os.fstat(reader.fileno())) != expected:
            raise ValueError("Snapshot source changed before copying")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(1024 * 1024):
                if canceled():
                    raise InterruptedError("Backup canceled while copying; unpublished bytes kept")
                writer.write(chunk)
                digest.update(chunk)
            writer.flush()
            os.fchmod(writer.fileno(), 0o700 if expected[5] & 0o111 else 0o600)
            os.fsync(writer.fileno())
        if signature(os.fstat(reader.fileno())) != expected:
            raise ValueError("Snapshot source changed during copying")
    os.replace(temporary, target)
    sync(target.parent)
    return digest.hexdigest()


def export_files(data, output, identity, *, canceled=lambda: False, progress=lambda *_: None):
    """Caller holds native cold-handoff/quiescence for DB and retained files."""
    if (
        not isinstance(identity, str)
        or len(identity) != 64
        or any(c not in "0123456789abcdef" for c in identity)
    ):
        raise ValueError("Snapshot files require their frozen database/installation identity")
    data, output = versions.canonical(data), versions.canonical(output)
    if output.is_relative_to(data) or data.is_relative_to(output):
        raise ValueError("Snapshot output must stay separate from application data")
    private_directory(output)
    before = catalog(data)
    request = {"schema": 1, "identity": identity, "catalog": before}
    path = output / "files-request.json"
    if path.exists() or path.is_symlink():
        if json.loads(versions.read_private(path, LIMIT)) != request:
            raise ValueError("Retained files changed since this snapshot began")
    else:
        write_json(path, request)
    if (output / "files.json").exists() or (output / "files.json").is_symlink():
        return verify_files(output, identity)
    destination, staging = output / "files", output / "files-staging"
    for folder in (destination, staging):
        folder.mkdir(mode=0o700, exist_ok=True)
        private_directory(folder)
    entries = []
    for key, value in sorted(before.items()):
        if canceled():
            raise InterruptedError("Snapshot canceled; originals and partial output preserved")
        target = destination / key
        kind = value["kind"]
        entry = {"path": key, "kind": kind}
        if kind == "directory":
            target.mkdir(mode=0o700, exist_ok=True)
            private_directory(target)
        elif kind == "file":
            entry.update(
                sha256=copy_file(data, key, target, value["signature"], staging, canceled=canceled),
                size=value["signature"][2],
                executable=bool(value["signature"][5] & 0o111),
            )
        elif kind == "symlink":
            if target.exists() or target.is_symlink():
                if not target.is_symlink() or os.readlink(target) != value["target"]:
                    raise ValueError("Snapshot link output changed")
            else:
                target.symlink_to(value["target"])
                sync(target.parent)
            entry["target"] = value["target"]
        else:
            # External resources remain references, never copied or granted authority.
            entry["target"] = value["target"]
        entries.append(entry)
        progress(len(entries), len(before))
    if catalog(data) != before:
        raise ValueError("Retained files changed before snapshot publication")
    report = {"schema": 1, "identity": identity, "excluded": sorted(EXCLUDED), "entries": entries}
    write_json(output / "files.json", report)
    return verify_files(output, identity)


def verify_files(output, identity):
    private_directory(output)
    value = json.loads(versions.read_private(output / "files.json", LIMIT))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "identity", "excluded", "entries"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["identity"] != identity
        or value["excluded"] != sorted(EXCLUDED)
        or not isinstance(value["entries"], list)
    ):
        raise ValueError("The retained-file snapshot manifest changed")
    expected = {}
    for item in value["entries"]:
        if not isinstance(item, dict) or "path" not in item or "kind" not in item:
            raise ValueError("Invalid snapshot file entry")
        key = str(relative(item["path"]))
        if key in expected:
            raise ValueError("Duplicate snapshot file entry")
        kind = item["kind"]
        fields = {"path", "kind"} | (
            {"sha256", "size", "executable"}
            if kind == "file"
            else {"target"}
            if kind in ("symlink", "external_reference")
            else set()
        )
        if set(item) != fields or kind not in ("file", "directory", "symlink", "external_reference"):
            raise ValueError("Invalid snapshot file shape")
        if kind == "file" and (
            type(item["size"]) is not int
            or item["size"] < 0
            or type(item["executable"]) is not bool
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in item["sha256"])
        ):
            raise ValueError("Invalid snapshot file digest/size")
        if kind in ("symlink", "external_reference") and (
            not isinstance(item["target"], str) or "\x00" in item["target"]
        ):
            raise ValueError("Invalid snapshot link metadata")
        expected[key] = item
    root = output / "files"
    private_directory(root)
    actual = catalog(root, exclusions=False)
    if set(actual) != {key for key, value in expected.items() if value["kind"] != "external_reference"}:
        raise ValueError("The snapshot file inventory differs from its manifest")
    for key, found in actual.items():
        item = expected[key]
        if found["kind"] != item["kind"]:
            raise ValueError("The snapshot file type changed")
        if item["kind"] == "file":
            if (
                found["signature"][2] != item["size"]
                or file_hash(root / key) != item["sha256"]
                or bool(found["signature"][5] & 0o111) != item["executable"]
            ):
                raise ValueError("The snapshot file bytes changed")
        elif item["kind"] == "symlink" and found["target"] != item["target"]:
            raise ValueError("The snapshot link changed")
    return value
