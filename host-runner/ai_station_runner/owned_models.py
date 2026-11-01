"""Read-only inspection of a fixed app-owned verified-model namespace."""

import os
import re
import stat
from pathlib import Path

from fastapi import HTTPException

from ai_station_runner.config import get_settings

SHA = re.compile(r"[a-f0-9]{64}\Z")


def owned_model(relative, digest):
    return verify_owned_model(get_settings().host_data_dir(), relative, digest)


def verify_owned_model(root, relative, digest):
    """The same immutable-model boundary for an explicitly owned native data root."""
    if not isinstance(digest, str) or not SHA.fullmatch(digest) or relative != "models/store/" + digest:
        raise HTTPException(422, "Choose a verified app-owned model reference")
    root = Path(root).resolve()
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise HTTPException(422, "App-owned models cannot cross symlinks")
    try:
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o222
        ):
            raise ValueError("The model is not an immutable owned regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if source.read(4) != b"GGUF":
                raise ValueError("The model does not have a GGUF header")
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "The verified app-owned GGUF is unavailable or changed") from exc
    return path


def validate_reference(path, digest, app_owned):
    if app_owned:
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or path != "models/store/" + digest:
            raise ValueError("Choose a verified app-owned model reference")
    elif digest is not None:
        raise ValueError("A model checksum requires an explicit app-owned source")
