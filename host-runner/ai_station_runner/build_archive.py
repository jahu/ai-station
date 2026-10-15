"""Capture bounded untrusted build data; never follow links or execute output."""

import hashlib
import os
import stat
import time
import zipfile

MAX_FILES = 1000
MAX_BYTES = 32 * 1024 * 1024


def fingerprint(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def safe_name(name):
    return (
        bool(name)
        and len(name.encode()) <= 255
        and not name.startswith(".")
        and not any(ord(c) < 32 or c in "/\\:" for c in name)
        and not any(
            word in name.lower() for word in ("credential", "secret", "id_rsa", "id_ed25519", "node_modules")
        )
        and not name.lower().endswith((".pem", ".key", ".p12", ".pfx"))
    )


def create_archive(workspace, destination):
    """Caller holds the worktree lock. Output location is outside the sandbox."""
    temporary = destination.with_name(destination.name + ".partial")
    created = False
    files = total = entries = 0
    deadline = time.monotonic() + 30

    def unchanged(info, current):
        if fingerprint(info) != fingerprint(current):
            raise ValueError("Build output changed while packaging")

    def walk(directory, prefix, archive, depth=0):
        nonlocal files, total, entries
        if depth > 16 or time.monotonic() > deadline:
            raise ValueError("Build output exceeds packaging limits")
        before = os.fstat(directory)
        with os.scandir(directory) as scan:
            for entry in scan:
                entries += 1
                if entries > MAX_FILES or not safe_name(entry.name):
                    raise ValueError("Build output has unsupported entries")
                member = prefix + entry.name
                if len(member.encode()) > 500:
                    raise ValueError("Build output path exceeds its limit")
                info = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, flags | os.O_DIRECTORY, dir_fd=directory)
                    try:
                        unchanged(info, os.fstat(child))
                        walk(child, member + "/", archive, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    if total + info.st_size > MAX_BYTES:
                        raise ValueError("Build output exceeds 32 MiB")
                    descriptor = os.open(entry.name, flags, dir_fd=directory)
                    with os.fdopen(descriptor, "rb") as source:
                        unchanged(info, os.fstat(source.fileno()))
                        content = source.read(min(info.st_size + 1, MAX_BYTES + 1))
                        unchanged(info, os.fstat(source.fileno()))
                        if len(content) != info.st_size:
                            raise ValueError("Build output changed while reading")
                    archive.writestr(member, content)
                    files += 1
                    total += len(content)
                else:
                    raise ValueError("Build output must contain ordinary files and directories")
                unchanged(info, os.stat(entry.name, dir_fd=directory, follow_symlinks=False))
                if time.monotonic() > deadline:
                    raise ValueError("Build output packaging timed out")
        unchanged(before, os.fstat(directory))

    root = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.open("dist", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            original = os.fstat(directory)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as output:
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    walk(directory, "", archive)
                output.flush()
                os.fsync(output.fileno())
            if not files:
                raise ValueError("Build output is empty")
            unchanged(original, os.stat("dist", dir_fd=root, follow_symlinks=False))
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            size = temporary.stat().st_size
            os.link(temporary, destination, follow_symlinks=False)  # Exclusive publication, never overwrite.
            return {
                "status": "ready",
                "size_bytes": size,
                "sha256": digest,
                "file_count": files,
                "uncompressed_bytes": total,
            }
        finally:
            os.close(directory)
    finally:
        os.close(root)
        if created:
            temporary.unlink(missing_ok=True)


def capture_build(workspace, destination, results):
    if (
        not results
        or any(r["exit_code"] != 0 for r in results)
        or not any(r["kind"] == "build" for r in results)
    ):
        return None
    try:
        return create_archive(workspace, destination)
    except FileNotFoundError:
        return {"status": "unavailable", "reason": "No dist directory was produced by this build."}
    except (OSError, ValueError):
        return {
            "status": "unavailable",
            "reason": "Build output could not be exported safely within the file, size and path limits.",
        }
