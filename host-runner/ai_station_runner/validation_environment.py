"""Bounded project environment configuration, never caller-provided shell/env."""

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from ai_station_runner.gitops import GitError

PythonManifest = Literal["requirements.txt", "pyproject.toml", "requirements.lock", "requirements-dev.lock"]


def relative_directory(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 300
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Use a canonical relative project directory")
    return value


class ValidationEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    python_manifest: PythonManifest | None = None
    node_directory: str | None = Field(default=None, max_length=300)
    python_source_roots: list[str] = Field(default_factory=list, max_length=10)
    timeout_seconds: StrictInt = Field(default=900, ge=60, le=7200)

    @field_validator("node_directory")
    @classmethod
    def node_path(cls, value):
        return relative_directory(value) if value is not None else None

    @field_validator("python_source_roots")
    @classmethod
    def source_paths(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Python source directories must be unique")
        return [relative_directory(value) for value in values]


def component_directory(workspace: Path, relative: str) -> Path:
    relative_directory(relative)
    root = workspace.resolve(strict=True)
    target = root
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise GitError("Project component directories must not contain symlinks")
    try:
        if not target.is_dir() or target.resolve(strict=True) != target or not target.is_relative_to(root):
            raise GitError("Project component must be a real directory inside its worktree")
    except OSError as exc:
        raise GitError("Project component directory is unavailable") from exc
    return target
