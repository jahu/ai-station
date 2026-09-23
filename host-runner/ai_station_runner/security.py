"""Filesystem allowlists. Canonical paths, no symlink escape."""

from __future__ import annotations

from pathlib import Path


class PathBoundaryError(ValueError):
    pass


def canonical(path: Path) -> Path:
    if "\x00" in str(path):
        raise PathBoundaryError("Null byte in path")
    return path.expanduser().resolve()


def ensure_within(path: Path, roots: list[Path]) -> Path:
    resolved = canonical(path)
    for root in roots:
        base = canonical(root)
        if resolved == base or base in resolved.parents:
            return resolved
    raise PathBoundaryError(f"Path is outside allowed roots: {path}")


def resolve_child(root: Path, relative: str) -> Path:
    if not relative or relative.startswith(("/", "\\")) or "\x00" in relative:
        raise PathBoundaryError("Relative path required")
    parts = Path(relative).parts
    if any(part in ("..", "") for part in parts):
        raise PathBoundaryError("Path traversal rejected")
    base = canonical(root)
    candidate = canonical(base / relative)
    if candidate != base and base not in candidate.parents:
        raise PathBoundaryError("Resolved path escapes the root")
    return candidate
