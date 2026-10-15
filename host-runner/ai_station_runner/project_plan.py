"""Bounded read-only planning inside a verified owned worktree."""

import fcntl
import json
import os
import re
import tomllib
from itertools import islice
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ai_station_runner.dependency_manifest import (
    _regular_file,
    load_specifiers,
    parse_pyproject,
    parse_requirements,
)
from ai_station_runner.gitops import GitError
from ai_station_runner.project_manifests import manifest_snapshot
from ai_station_runner.validation_environment import ValidationEnvironment, component_directory
from ai_station_runner.worktrees import inspect_worktree, owned_path


class ProjectPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    worktree_run_id: UUID
    install_dependencies: StrictBool = False
    validation_environment: ValidationEnvironment | None = None
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


def plan_workspace(workspace, *, install_dependencies=False, validation_environment=None):
    environment = ValidationEnvironment.model_validate(validation_environment or {})
    snapshot = manifest_snapshot(workspace, python_manifest=environment.python_manifest)
    commands, warnings = [], []
    ecosystems = []
    requirements = []
    python = (
        bool(environment.python_manifest)
        or snapshot["requirements.txt"] is not None
        or snapshot["pyproject.toml"] is not None
    )
    if python:
        requirements = (
            load_specifiers(workspace, manifest=environment.python_manifest)[1]
            if environment.python_manifest
            else parse_requirements((workspace / "requirements.txt").read_text())
            if snapshot["requirements.txt"]
            else parse_pyproject((workspace / "pyproject.toml").read_text())
        )
        if requirements:
            ecosystems.append("python")
    for relative in environment.python_source_roots:
        component_directory(workspace, relative)
    node_root = (
        component_directory(workspace, environment.node_directory)
        if environment.node_directory
        else workspace
    )
    node_snapshot = manifest_snapshot(node_root) if environment.node_directory else snapshot
    if environment.node_directory and node_snapshot["package.json"] is None:
        raise GitError("The configured Node directory requires package.json")
    if node_snapshot["package.json"] is not None:
        package = json.loads((node_root / "package.json").read_bytes())
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
                prefix = (
                    [f"--prefix={environment.node_directory}"]
                    if environment.node_directory not in {None, "."}
                    else []
                )
                commands.append({"kind": kind, "argv": ["npm", *prefix, "run", kind]})
        if "test" not in {c["kind"] for c in commands}:
            warnings.append("No test script was detected; a successful build is not test coverage.")
    if python or node_snapshot["package.json"] is None:
        location = "tests" if _tests(workspace / "tests") else "." if _tests(workspace) else None
        configured_pytest = False
        if environment.python_manifest and snapshot["pyproject.toml"]:
            config = tomllib.loads((workspace / "pyproject.toml").read_text())
            paths = config.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths", [])
            if (
                not isinstance(paths, list)
                or len(paths) > 10
                or any(not isinstance(path, str) for path in paths)
            ):
                raise GitError("Pytest testpaths must be bounded relative project directories")
            test_directories = [component_directory(workspace, path) for path in paths]
            configured_pytest = any(_tests(directory) for directory in test_directories)
            if configured_pytest:
                location = "."
        if location:
            executable = (
                ".venv/bin/python"
                if "python" in ecosystems
                and (install_dependencies or (workspace / ".venv/bin/python").is_file())
                else "python3"
            )
            pytest = (
                configured_pytest
                or python
                and any(re.match(r"^pytest(?:[<>=!~;\s\[]|$)", item, re.I) for item in requirements)
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
    result = {
        "manifest_snapshot": snapshot,
        "ecosystems": ecosystems,
        "commands": commands,
        "warnings": warnings,
    }
    if environment.node_directory:
        result["node_manifest_snapshot"] = node_snapshot
    return result


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
            **plan_workspace(
                workspace,
                install_dependencies=body.install_dependencies,
                validation_environment=body.validation_environment,
            ),
        }
