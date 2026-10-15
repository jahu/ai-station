# Imported fixtures intentionally share their pytest parameter names.
# ruff: noqa: F811
import json

import pytest
from ai_station_runner.validation_environment import ValidationEnvironment as NativeEnvironment
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.validation_environment import ValidationEnvironment
from fastapi.testclient import TestClient
from test_node_project_runs import fake_node, node_manifest  # noqa: F401
from test_projects import (  # noqa: F401
    enqueue_dependencies,
    enqueue_validation,
    owned_runner,
    prepared_validation,
    repository,
    validation_sandbox,
)


def configure(client, project, **environment):
    response = client.put(
        f"/api/projects/{project['id']}",
        json={
            **{
                key: project[key]
                for key in (
                    "name",
                    "default_branch",
                    "integration_branch",
                    "protected_branches",
                    "preferred_executor",
                    "test_commands",
                    "lint_commands",
                    "build_commands",
                    "agent_rules",
                    "pr_policy",
                )
            },
            "expected_updated_at": project["updated_at"],
            "validation_environment": environment,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_control_plane_and_runner_environment_schema_contract():
    assert ValidationEnvironment.model_json_schema() == NativeEnvironment.model_json_schema()
    for values in (
        {"python_manifest": "../private"},
        {"node_directory": "/etc"},
        {"python_source_roots": ["backend", "backend"]},
        {"timeout_seconds": True},
        {"timeout_seconds": 7201},
        {"private_tmp": True},
    ):
        for schema in (ValidationEnvironment, NativeEnvironment):
            with pytest.raises(ValueError):
                schema.model_validate(values)


def test_manual_checks_freeze_component_environment_and_import_owned_source(
    repository,
    owned_runner,
    validation_sandbox,
):
    original_index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, tree = prepared_validation(
            client,
            repository,
            [
                [
                    "/usr/bin/python3",
                    "-c",
                    "import owned_probe; from pathlib import Path; "
                    "assert owned_probe.VALUE == 'worktree'; "
                    "assert str(Path.cwd()/'backend') == str(Path(owned_probe.__file__).parent); "
                    "print(owned_probe.__file__)",
                ]
            ],
        )
        workspace = owned_runner.data_dir / tree["relative_path"]
        (workspace / "backend").mkdir()
        (workspace / "backend/owned_probe.py").write_text("VALUE = 'worktree'\n")
        (workspace / "frontend").mkdir()
        (workspace / "frontend/package.json").write_text('{"name":"component","version":"1.0.0"}')
        (workspace / "requirements-dev.lock").write_text("pytest==8.3.5\n")
        project = configure(
            client,
            project,
            python_manifest="requirements-dev.lock",
            node_directory="frontend",
            python_source_roots=["backend"],
            timeout_seconds=1800,
        )
        response = enqueue_validation(client, project, tree)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        # Subsequent project edits cannot silently alter this Run's recorded config.
        assert (
            client.put(
                f"/api/projects/{project['id']}",
                json={
                    "name": project["name"],
                    "expected_updated_at": project["updated_at"],
                    "validation_environment": {"timeout_seconds": 60},
                },
            ).status_code
            == 409
        )
        with session_factory()() as session:
            tick(session, "component-validation")
        result = client.get("/api/runs/" + run_id).json()
        assert result["status"] == "succeeded", result
        params = result["parameters"]
        assert params["validation_environment"]["timeout_seconds"] == 1800
        assert params["manifest_snapshot"]["requirements-dev.lock"]
        assert params["node_manifest_snapshot"]["package.json"]
        assert result["metadata"]["validation"]["commands"][0]["exit_code"] == 0
        request = json.loads((owned_runner.data_dir / f"runtime/validation/{run_id}.json").read_text())
        assert request["validation_environment"] == params["validation_environment"]
        assert request["node_manifest_snapshot"] == params["node_manifest_snapshot"]
    assert (repository / ".git/index").read_bytes() == original_index
    assert not (repository / "backend/owned_probe.py").exists()


def test_nested_node_dependency_run_uses_component_and_root_owned_scratch(
    repository,
    owned_runner,
    validation_sandbox,
    fake_node,
):
    # The shared fake checks all npm isolation arguments; allow root-owned scratch
    # for a nested component, matching the new production policy boundary.
    binary = fake_node / "bin/node"
    binary.write_text(
        binary.read_text().replace(
            "assert Path(os.environ['HOME']).is_relative_to(Path.cwd())",
            "assert Path(os.environ['HOME']).is_relative_to(Path.cwd().parent)",
        )
    )
    with TestClient(app) as client:
        project, tree = prepared_validation(client, repository, [])
        workspace = owned_runner.data_dir / tree["relative_path"]
        frontend = workspace / "frontend"
        frontend.mkdir()
        node_manifest(frontend)
        project = configure(client, project, node_directory="frontend")
        response = enqueue_dependencies(client, project, tree)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session_factory()() as session:
            tick(session, "component-dependencies")
        result = client.get("/api/runs/" + run_id).json()
        assert result["status"] == "succeeded", result
        report = result["metadata"]["dependencies"]
        assert report["environment"] == tree["relative_path"] + "/frontend/node_modules"
        assert report["directory"] == "frontend"
        assert "/" not in report["scratch_relative"]
        assert (frontend / "install-proof.json").is_file()
        assert not (workspace / "node_modules").exists()
