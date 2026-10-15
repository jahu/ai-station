"""Canonical bounded manifest snapshots shared by owned project operations."""

import hashlib
from typing import Annotated, Literal

from pydantic import Field

from ai_station_runner.dependency_manifest import _regular_file
from ai_station_runner.gitops import GitError

MANIFESTS = ("requirements.txt", "pyproject.toml", "package.json")
ManifestName = Literal["requirements.txt", "pyproject.toml", "package.json"]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None
ManifestSnapshot = Annotated[dict[ManifestName, Digest], Field(min_length=3, max_length=3)]


def manifest_snapshot(workspace):
    snapshot = {}
    for name in MANIFESTS:
        path = workspace / name
        if not path.exists() and not path.is_symlink():
            snapshot[name] = None
            continue
        path = _regular_file(workspace, path)
        if path.stat().st_size > 256000:
            raise GitError("Project manifest exceeds its size limit")
        snapshot[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def verify_manifests(workspace, expected):
    if expected is not None and manifest_snapshot(workspace) != expected:
        raise GitError("Project manifests changed after preparation was planned; inspect before continuing")
