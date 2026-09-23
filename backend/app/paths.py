"""Relative path handling for AI Station-owned files."""

from __future__ import annotations

import re
from pathlib import Path

_RELATIVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]*$")


class PathBoundaryError(ValueError):
    pass


def validate_relative(relative: str) -> str:
    if not relative or relative.startswith(("/", "\\")):
        raise PathBoundaryError("Absolute paths are not stored for app-owned files")
    if "\x00" in relative:
        raise PathBoundaryError("Null byte in path")
    parts = Path(relative).parts
    if any(part in ("..", "") for part in parts):
        raise PathBoundaryError("Path traversal rejected")
    normalized = "/".join(parts)
    if not _RELATIVE.match(normalized):
        raise PathBoundaryError("Relative path contains unsupported characters")
    return normalized


def safe_join(root: Path, relative: str) -> Path:
    relative = validate_relative(relative)
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathBoundaryError("Resolved path escapes the data root")
    return candidate


def artifact_relative(artifact_id: str, suffix: str) -> str:
    clean = artifact_id.replace("-", "")
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return validate_relative(f"artifacts/{clean[:2]}/{clean[2:4]}/{artifact_id}{suffix}")


def strip_data_prefix(path: str, roots: list[Path]) -> str | None:
    """Return a data-root-relative path when `path` is inside a known root."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return validate_relative(path)
    resolved = candidate.resolve()
    for root in roots:
        root_resolved = root.resolve()
        if resolved == root_resolved:
            return ""
        if root_resolved in resolved.parents:
            return validate_relative(resolved.relative_to(root_resolved).as_posix())
    return None
