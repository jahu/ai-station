"""Strict Python dependency manifests. No URLs, VCS, indexes or arbitrary flags."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ai_station_runner.gitops import GitError
from ai_station_runner.public_http import public_addresses

MAX_MANIFEST = 64_000
MAX_REQUIREMENTS = 100
MAX_LINE = 500
VENDOR = "vendor"
PYPI_INDEX = "https://pypi.org/simple"
PYPI_HOSTS = ("pypi.org", "files.pythonhosted.org")
NAME = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9][A-Za-z0-9._,-]*\])?"
    r"(?P<spec>(?:\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[^,;]+(?:,\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[^,;]+)*)?)?"
    r"(?P<marker>\s*;\s*.+)?$"
)


def _regular_file(workspace: Path, path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise GitError("Dependency manifests must be regular files in the worktree")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(workspace.resolve(strict=True)):
        raise GitError("Dependency files must stay inside the owned worktree")
    return resolved


def _specifier(line: str) -> str:
    text = line.strip()
    if not text or text.startswith("#"):
        return ""
    if "\\" in text or any(ord(char) < 32 for char in text) or len(text) > MAX_LINE:
        raise GitError("Dependency lines must be readable and bounded")
    if text.startswith("-") or "://" in text or "@" in text:
        raise GitError("URLs, VCS refs and pip flags are not allowed in dependency files")
    if NAME.fullmatch(text):
        return text
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".whl":
        raise GitError("Only named Python requirements or relative wheel paths are allowed")
    return text


def parse_requirements(text: str) -> list[str]:
    if len(text) > MAX_MANIFEST:
        raise GitError("Dependency manifest exceeds its size limit")
    items = []
    for raw in text.splitlines():
        specifier = _specifier(raw.split("#", 1)[0])
        if specifier:
            items.append(specifier)
        if len(items) > MAX_REQUIREMENTS:
            raise GitError("At most 100 Python requirements are allowed")
    return items


def parse_pyproject(text: str) -> list[str]:
    if len(text) > MAX_MANIFEST:
        raise GitError("Dependency manifest exceeds its size limit")
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise GitError("pyproject.toml is not valid TOML") from exc
    project = document.get("project") if isinstance(document, dict) else None
    values = project.get("dependencies", []) if isinstance(project, dict) else []
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise GitError("pyproject.toml must declare project.dependencies as a list of strings")
    return parse_requirements("\n".join(values))


def load_specifiers(workspace: Path) -> tuple[str, list[str]]:
    workspace = workspace.resolve(strict=True)
    requirements = workspace / "requirements.txt"
    pyproject = workspace / "pyproject.toml"
    if requirements.exists():
        specifiers = parse_requirements(_regular_file(workspace, requirements).read_text())
        kind = "requirements.txt"
    elif pyproject.exists():
        specifiers = parse_pyproject(_regular_file(workspace, pyproject).read_text())
        kind = "pyproject.toml"
    else:
        raise GitError("Worktree needs requirements.txt or pyproject.toml with project.dependencies")
    if not specifiers:
        raise GitError("No installable Python dependencies are declared")
    return kind, specifiers


def vendor_dir(workspace: Path) -> Path | None:
    workspace = workspace.resolve(strict=True)
    path = workspace / VENDOR
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise GitError("vendor must be a regular directory of wheels inside the worktree")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(workspace):
        raise GitError("vendor must stay inside the owned worktree")
    return resolved


def pip_plan(workspace: Path, python: Path, specifiers: list[str]) -> dict:
    workspace = workspace.resolve(strict=True)
    packages = []
    for item in specifiers:
        if item.endswith(".whl"):
            wheel = workspace / item
            if wheel.is_symlink() or not wheel.is_file() or wheel.suffix != ".whl":
                raise GitError("Wheel requirements must be regular files inside the worktree")
            resolved = wheel.resolve(strict=True)
            if not resolved.is_relative_to(workspace):
                raise GitError("Wheel requirements must stay inside the owned worktree")
            packages.append(str(resolved.relative_to(workspace)))
        else:
            packages.append(item)
    vendor = vendor_dir(workspace)
    source = "vendor" if vendor is not None else "pypi"
    argv = [
        str(python),
        "-m",
        "pip",
        "install",
        "--isolated",
        "--require-virtualenv",
        "--no-input",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--only-binary",
        ":all:",
        "--progress-bar",
        "off",
    ]
    if source == "vendor":
        argv.extend(["--no-index", "--find-links", VENDOR])
    else:
        argv.extend(["--index-url", PYPI_INDEX])
    argv.extend(packages)
    return {"source": source, "specifiers": packages, "argv": argv, "network": source == "pypi"}


def confirm_public_indexes():
    for host in PYPI_HOSTS:
        public_addresses(host)
