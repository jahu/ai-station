"""Bounded read-only planning inside a verified owned worktree."""

import fcntl
import json
import os
import re
from itertools import islice
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ai_station_runner.dependency_manifest import _regular_file, parse_pyproject, parse_requirements
from ai_station_runner.gitops import GitError
from ai_station_runner.project_manifests import manifest_snapshot
from ai_station_runner.worktrees import inspect_worktree, owned_path


class ProjectPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    worktree_run_id: UUID
    install_dependencies: StrictBool = False
    permissions: list[str] = Field(max_length=2)


def _tests(directory):
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise GitError("Automatic tests must use a real directory inside the worktree")
    entries = list(islice(directory.iterdir(), 257))
    if len(entries) > 256:
        raise GitError("Automatic test discovery exceeds its directory limit; configure explicit commands")
    return [p for p in entries if re.fullmatch(r"test.*\.py", p.name) and _regular_file(directory, p)]


def plan_workspace(workspace, *, install_dependencies=False):
    snapshot = manifest_snapshot(workspace)
    commands, warnings = [], []
    ecosystems = []
    requirements = []
    python = snapshot["requirements.txt"] is not None or snapshot["pyproject.toml"] is not None
    if python:
        requirements = (
            parse_requirements((workspace / "requirements.txt").read_text())
            if snapshot["requirements.txt"]
            else parse_pyproject((workspace / "pyproject.toml").read_text())
        )
        if requirements:
            ecosystems.append("python")
    if snapshot["package.json"] is not None:
        package = json.loads((workspace / "package.json").read_bytes())
        if not isinstance(package, dict):
            raise GitError("package.json must be an object")
        scripts = package.get("scripts", {})
        if not isinstance(scripts, dict):
            raise GitError("Node scripts must be an object")
        ecosystems.append("node")
        for kind in ("test", "lint", "build"):
            script = scripts.get(kind)
            if script is not None and (not isinstance(script, str) or len(script) > 10000 or "\0" in script):
                raise GitError("Invalid Node project check script")
            if script and script.strip():
                commands.append({"kind": kind, "argv": ["npm", "run", kind]})
        if "test" not in {c["kind"] for c in commands}:
            warnings.append("No test script was detected; a successful build is not test coverage.")
    if python or snapshot["package.json"] is None:
        location = "tests" if _tests(workspace / "tests") else "." if _tests(workspace) else None
        if location:
            executable = (
                ".venv/bin/python"
                if "python" in ecosystems
                and (install_dependencies or (workspace / ".venv/bin/python").is_file())
                else "python3"
            )
            pytest = python and any(
                re.match(r"^pytest(?:[<>=!~;\s\[]|$)", item, re.I) for item in requirements
            )
            argv = (
                [executable, "-m", "pytest", "-q"]
                if pytest
                else [executable, "-m", "unittest", "discover", "-s", location, "-v"]
            )
            commands.append({"kind": "test", "argv": argv})
        else:
            warnings.append(
                "No Python tests were detected."
                if snapshot["package.json"] is not None
                else "No tests or build checks were detected; configure project commands to verify this code."
            )
    return {
        "manifest_snapshot": snapshot,
        "ecosystems": ecosystems,
        "commands": commands,
        "warnings": warnings,
    }


def inspect_project_plan(manager, body):
    if set(body.permissions) != {"filesystem_read", "git_read"}:
        raise PermissionError("Read-only project planning permissions are required")
    record = inspect_worktree(manager, str(body.worktree_run_id))
    if record["state"] != "ready" or record["project_id"] != str(body.project_id):
        raise GitError("Project planning requires this project's ready owned worktree")
    workspace = owned_path(record["relative_path"])
    lock_path = owned_path(f"runtime/validation-worktrees/{body.worktree_run_id}.lock")
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with lock_path.open("a") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return {
            "project_id": str(body.project_id),
            "worktree_run_id": str(body.worktree_run_id),
            **plan_workspace(workspace, install_dependencies=body.install_dependencies),
        }
