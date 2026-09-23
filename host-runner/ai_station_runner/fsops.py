"""Worktree-scoped file tools."""

from __future__ import annotations

from pathlib import Path

from ai_station_runner.security import resolve_child


def read_file(root: Path, relative: str, limit: int = 200_000) -> dict:
    path = resolve_child(root, relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    data = path.read_bytes()[:limit]
    return {"path": relative, "content": data.decode("utf-8", errors="replace")}


def write_file(root: Path, relative: str, content: str) -> dict:
    path = resolve_child(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"ok": True, "path": relative, "bytes": len(content.encode())}


def list_dir(root: Path, relative: str) -> dict:
    path = resolve_child(root, relative or ".")
    if relative in ("", "."):
        path = root.resolve()
    if not path.is_dir():
        raise NotADirectoryError(relative)
    entries = []
    for child in sorted(path.iterdir()):
        if child.name == ".git":
            continue
        entries.append({"name": child.name, "is_dir": child.is_dir()})
    return {"entries": entries[:500]}


def search_files(root: Path, query: str, limit: int = 50) -> dict:
    if not query.strip():
        raise ValueError("Query is required")
    matches = []
    base = root.resolve()
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if query in text:
            matches.append(str(path.relative_to(base)))
        if len(matches) >= limit:
            break
    return {"matches": matches}
