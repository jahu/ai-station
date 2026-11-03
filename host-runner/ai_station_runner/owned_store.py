"""Finalize native write bits for explicit app-owned downloads; verify bytes separately."""

import os
import re
import stat
from pathlib import Path


def make_download_readonly(root, digest, size, *, check=lambda: None):
    """Never accept an external path, alias, foreign owner or different length.

    Docker Desktop may expose a worker's chmod only in its Linux view. The
    native owner finalizes the same app-owned cache object before the existing
    SDK checksum or downloaded-model observation checks. This is not adoption
    or a checksum claim, and does not authorize changing external model files.
    """
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Use the exact app-owned download hash")
    if type(size) is not int or size < 0:
        raise ValueError("Use the exact downloaded object length")
    root = Path(root).resolve(strict=True)
    path = root / "models/store" / digest
    if path.parent.resolve(strict=True) != root / "models/store":
        raise ValueError("Downloaded objects cannot cross a parent symlink")
    check()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size != size
            or before.st_mode & 0o7111
        ):
            raise ValueError("Downloaded objects require their owned regular data-file identity")
        check()
        if before.st_mode & 0o222:
            os.fchmod(source.fileno(), stat.S_IMODE(before.st_mode) & ~0o222)
            os.fsync(source.fileno())
        after = os.fstat(source.fileno())
        named = path.stat(follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_uid", "st_nlink", "st_size", "st_mtime_ns")
        if (
            any(getattr(before, key) != getattr(after, key) for key in fields)
            or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
            or after.st_mode & 0o222
        ):
            raise ValueError("The downloaded object changed during native permission finalization")
        check()
    return path
