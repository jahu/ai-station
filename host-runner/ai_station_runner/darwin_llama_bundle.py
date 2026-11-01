"""Offline assembly of fixed native llama.cpp bytes; never inference readiness.

The existing native preparation Run must own cancellation/deadline/reservation.
This assembler downloads/executes nothing and is portable to package builders.
"""

import hashlib
import json
import os
import re
import stat
import struct
import tarfile
from collections import Counter
from pathlib import Path
from uuid import UUID

from ai_station_runner.speech_environment import directory, fingerprint, verified_object

RELEASE = "b12032"
SOURCE = "dde879bc4f954b809892fd0d660515f42536394a"
RECIPES = Path(__file__).with_name("recipes")
MAX_BYTES = 256 * 1024**2


def recipe(architecture):
    if architecture not in {"arm64", "x86_64"}:
        raise ValueError("Select a reviewed native Mac architecture")
    profile = f"llamacpp-native-darwin-{architecture}-{RELEASE}-v2"
    value = json.loads((RECIPES / (profile + ".json")).read_text())
    if (
        value["profile"] != profile
        or value["platform"] != "darwin/" + architecture
        or value["source_revision"] != SOURCE
        or value["inference_qualified"] is not False
        or value["minimum_os"] != [13, 3, 0]
        or len(value["inputs"]) != 1
        or value["file_identity_policy"] != "in-tree-hardlinks-v1"
    ):
        raise ValueError("The built-in native Mac recipe changed")
    return value


def _macho(path, architecture, names, *, executable):
    with path.open("rb") as source:
        header = source.read(32)
        if len(header) != 32 or header[:4] != b"\xcf\xfa\xed\xfe":
            raise ValueError("Expected a thin 64-bit native Mach-O file")
        _, cpu, _, kind, count, size, _, _ = struct.unpack("<IiiIIIII", header)
        if (
            cpu != {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
            or kind != (2 if executable else 6)
            or not 0 < count <= 1024
            or not 0 < size <= 1024**2
        ):
            raise ValueError("Native Mach-O architecture/type/commands differ")
        commands = source.read(size)
    if len(commands) != size:
        raise ValueError("Truncated native Mach-O commands")
    offset = 0
    minimum = None
    for _ in range(count):
        if offset + 8 > size:
            raise ValueError("Truncated native Mach-O command")
        command, length = struct.unpack_from("<II", commands, offset)
        if length < 8 or offset + length > size:
            raise ValueError("Invalid native Mach-O command length")
        data = commands[offset : offset + length]
        if command == 0x32:
            if length < 24 or struct.unpack_from("<I", data, 8)[0] != 1 or minimum is not None:
                raise ValueError("The native binary is not a single macOS build")
            version = struct.unpack_from("<I", data, 12)[0]
            minimum = [version >> 16, version >> 8 & 255, version & 255]
        if command in {0xC, 0x80000018, 0x8000001F, 0x80000023, 0x8000001C}:
            if length < 12:
                raise ValueError("Truncated native library command")
            at = struct.unpack_from("<I", data, 8)[0]
            if not 12 <= at < length or b"\0" not in data[at:]:
                raise ValueError("Invalid native library string")
            name = data[at:].split(b"\0", 1)[0].decode("utf-8")
            if command == 0x8000001C:
                allowed = name == "@loader_path"
            else:
                allowed = (name.startswith("@rpath/") and name[7:] in names) or (
                    name.startswith(("/usr/lib/", "/System/Library/Frameworks/"))
                    and ".." not in Path(name).parts
                )
            if not allowed:
                raise ValueError("Native runtime needs an unreviewed external library/search path")
        offset += length
    if offset != size or minimum != [13, 3, 0]:
        raise ValueError("The native minimum OS or command inventory differs")


def _members(archive, frozen):
    values = archive.getmembers()
    if len(values) > 128 or sum(v.size for v in values) > MAX_BYTES:
        raise ValueError("Native archive exceeds its bound")
    result = {}
    prefix = frozen["archive_root"] + "/"
    for item in values:
        if item.isdir() and item.name.rstrip("/") == frozen["archive_root"]:
            continue
        leaf = item.name.removeprefix(prefix)
        if (
            not item.name.startswith(prefix)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", leaf)
            or leaf in {".", ".."}
            or leaf in result
            or item.mode & 0o7000
            or item.size < 0
            or item.size > MAX_BYTES
            or item.sparse is not None
            or not (item.isfile() or item.issym())
        ):
            raise ValueError("Native archive has an unsafe or duplicate member")
        if item.issym() and (
            not re.fullmatch(r"[A-Za-z0-9_.-]+", item.linkname) or item.linkname in {".", ".."}
        ):
            raise ValueError("Native library links must stay in the same immutable bundle")
        result[leaf] = item
    return result


def _resolve(members, name):
    seen = set()
    while True:
        if name not in members or name in seen:
            raise ValueError("Native archive has a missing/cyclic library target")
        seen.add(name)
        value = members[name]
        if value.isfile():
            return value
        name = value.linkname


def _private_file(path, expected, check, *, links=1):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != links
            or before.st_mode & 0o222
            or before.st_size != expected["size_bytes"]
        ):
            raise ValueError("Native bundle files must remain immutable owned regular files")
        digest = hashlib.sha256()
        while chunk := source.read(1024**2):
            check()
            digest.update(chunk)
        after = os.fstat(source.fileno())

        def coordinate(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_mode,
                info.st_uid,
                info.st_nlink,
            )

        if coordinate(before) != coordinate(after) or digest.hexdigest() != expected["sha256"]:
            raise ValueError("The native runtime inventory changed")


def _verify_engine(engine, frozen, architecture, check):
    if {p.name for p in engine.iterdir()} != set(frozen["files"]):
        raise ValueError("Native bundle library inventory differs")
    counts = Counter(item["source"] for item in frozen["files"].values())
    identities = {}
    for name, item in frozen["files"].items():
        path = engine / name
        _private_file(path, item, check, links=counts[item["source"]])
        info = path.stat()
        coordinate = info.st_dev, info.st_ino
        previous = identities.setdefault(item["source"], coordinate)
        if previous != coordinate or len(set(identities.values())) != len(identities):
            raise ValueError("Native library aliases must retain their exact in-bundle file identity")
        if stat.S_IMODE(info.st_mode) != (0o555 if name == "llama-server" else 0o444):
            raise ValueError("Native executable/library permissions changed")
        if name != "LICENSE":
            _macho(path, architecture, frozen["files"], executable=name == "llama-server")


def inspect(root, operation_id, architecture, *, check=lambda: None):
    root = Path(root).resolve(strict=True)
    frozen = recipe(architecture)
    relative = "runtime/native-llama/" + fingerprint(frozen) + "/" + str(UUID(str(operation_id)))
    folder = root / relative
    if folder.resolve(strict=True) != folder or not folder.is_dir():
        raise ValueError("Native bundle storage cannot cross links")
    for current in (folder, folder / "engine"):
        if current.resolve(strict=True) != current:
            raise ValueError("Native bundle directories cannot cross links")
        info = current.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("Native bundle directories must remain private and owned")
    if {p.name for p in folder.iterdir()} != {"preparing.json", "bundle.json", "engine"}:
        raise ValueError("Native bundle publication is incomplete or changed")
    engine = folder / "engine"
    _verify_engine(engine, frozen, architecture, check)
    expected = {
        "schema": 1,
        "profile": frozen["profile"],
        "manifest_sha256": fingerprint(frozen),
        "relative_path": relative,
        "source_revision": SOURCE,
        "inference_qualified": False,
    }
    metadata = (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _private_file(
        folder / "bundle.json",
        {"size_bytes": len(metadata), "sha256": hashlib.sha256(metadata).hexdigest()},
        check,
    )
    if (folder / "bundle.json").read_bytes() != metadata:
        raise ValueError("Native bundle receipt differs")
    return expected


def prepare(root, operation_id, architecture, *, check=lambda: None, progress=lambda value: None):
    """Trusted offline preparation child; a partial operation is preserved for inspection."""
    check()
    root = Path(root).resolve(strict=True)
    frozen = recipe(architecture)
    identity = fingerprint(frozen)
    # Reuse the existing immutable store and private environment primitives.
    source = verified_object(root, frozen["inputs"][0], check)
    runtime = root / "runtime"
    if runtime.is_symlink():
        raise ValueError("Native runtime storage cannot cross links")
    runtime.mkdir(mode=0o700, exist_ok=True)
    info = runtime.stat()
    if not runtime.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o002:
        raise ValueError("Native runtime storage must remain owned")
    base = directory(runtime, "native-llama/" + identity)
    folder = base / str(UUID(str(operation_id)))
    if folder.exists() or folder.is_symlink():
        raise ValueError("Inspect the existing native preparation instead of overwriting it")
    folder.mkdir(mode=0o700)
    (folder / "preparing.json").write_text(json.dumps({"profile": frozen["profile"]}))
    engine = directory(folder, "engine")
    with tarfile.open(source) as archive:
        members = _members(archive, frozen)
        materialized = {}
        for index, (name, expected) in enumerate(frozen["files"].items()):
            check()
            item = _resolve(members, name)
            if (
                item.name != frozen["archive_root"] + "/" + expected["source"]
                or item.size != expected["size_bytes"]
            ):
                raise ValueError("Native archive source identity differs")
            # Preserve alias identity without installing archive-controlled links.
            # Only a verified in-bundle regular file can be the hardlink source.
            if item.name in materialized:
                os.link(materialized[item.name], engine / name, follow_symlinks=False)
            else:
                with archive.extractfile(item) as data, (engine / name).open("xb") as output:
                    while chunk := data.read(1024**2):
                        check()
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                    os.fchmod(output.fileno(), 0o555 if name == "llama-server" else 0o444)
                materialized[item.name] = engine / name
            progress(
                {
                    "phase": "assembling_native_engine",
                    "completed_files": index + 1,
                    "file_count": len(frozen["files"]),
                }
            )
    _verify_engine(engine, frozen, architecture, check)
    value = {
        "schema": 1,
        "profile": frozen["profile"],
        "manifest_sha256": identity,
        "relative_path": str(folder.relative_to(root)),
        "source_revision": SOURCE,
        "inference_qualified": False,
    }
    check()
    fd = os.open(engine, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    path = folder / "bundle.json"
    with path.open("xb") as output:
        output.write((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
        output.flush()
        os.fsync(output.fileno())
        os.fchmod(output.fileno(), 0o444)
    fd = os.open(folder, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return inspect(root, operation_id, architecture, check=check)
