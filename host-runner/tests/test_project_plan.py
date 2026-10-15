import json

import pytest
from ai_station_runner.gitops import GitError
from ai_station_runner.project_manifests import manifest_snapshot, verify_manifests
from ai_station_runner.project_plan import plan_workspace


def test_node_plan_uses_only_known_scripts_and_warns_about_absent_tests(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "deploy": "not an automatic command"}})
    )
    plan = plan_workspace(tmp_path, install_dependencies=True)
    assert plan["ecosystems"] == ["node"]
    assert plan["commands"] == [{"kind": "build", "argv": ["npm", "run", "build"]}]
    assert "No test script" in plan["warnings"][0]
    assert set(plan["manifest_snapshot"]) == {"requirements.txt", "pyproject.toml", "package.json"}
    assert len(plan["manifest_snapshot"]["package.json"]) == 64


def test_python_and_node_root_dependencies_are_not_silently_skipped(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest==8.3.0\n")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text("def test_example(): pass\n")
    plan = plan_workspace(tmp_path, install_dependencies=True)
    assert plan["ecosystems"] == ["python", "node"]
    assert {"kind": "test", "argv": [".venv/bin/python", "-m", "pytest", "-q"]} in plan["commands"]
    assert {"kind": "build", "argv": ["npm", "run", "build"]} in plan["commands"]


def test_stdlib_project_runs_real_test_discovery_without_requiring_dependencies(tmp_path):
    (tmp_path / "test_example.py").write_text("import unittest\n")
    plan = plan_workspace(tmp_path, install_dependencies=True)
    assert plan["ecosystems"] == []
    assert plan["commands"] == [
        {"kind": "test", "argv": ["python3", "-m", "unittest", "discover", "-s", ".", "-v"]}
    ]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not plan_workspace(empty)["commands"]
    assert "No tests" in plan_workspace(empty)["warnings"][0]


@pytest.mark.parametrize("kind", ["symlink_manifest", "symlink_tests", "added_manifest", "changed_manifest"])
def test_planning_and_frozen_manifests_do_not_cross_boundaries(tmp_path, kind):
    (tmp_path / "package.json").write_text("{}")
    before = manifest_snapshot(tmp_path)
    if kind == "symlink_manifest":
        (tmp_path / "package.json").unlink()
        (tmp_path / "package.json").symlink_to(tmp_path.parent / "outside.json")
    elif kind == "symlink_tests":
        (tmp_path / "package.json").unlink()
        (tmp_path / "tests").symlink_to(tmp_path.parent)
    elif kind == "added_manifest":
        (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n")
    else:
        (tmp_path / "package.json").write_text('{"name":"changed"}')
    with pytest.raises(GitError):
        if kind.startswith("symlink"):
            plan_workspace(tmp_path)
        else:
            verify_manifests(tmp_path, before)
