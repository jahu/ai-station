import pytest
from ai_station_runner.dependency_manifest import load_specifiers
from ai_station_runner.gitops import GitError
from ai_station_runner.project_manifests import manifest_snapshot, verify_manifests
from ai_station_runner.project_plan import plan_workspace
from ai_station_runner.validation_environment import ValidationEnvironment, component_directory
from pydantic import ValidationError


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/etc",
        "front/../back",
        "front//end",
        "./frontend",
        "front\\end",
        "front\nend",
        "foo:bar",
    ],
)
def test_environment_rejects_noncanonical_component_and_source_paths(path):
    with pytest.raises(ValidationError):
        ValidationEnvironment(node_directory=path)
    with pytest.raises(ValidationError):
        ValidationEnvironment(python_source_roots=[path])


def test_component_paths_reject_inside_and_outside_symlink_aliases(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "actual").mkdir()
    (root / "alias").symlink_to(root / "actual", target_is_directory=True)
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    for name in ("alias", "escape"):
        with pytest.raises(GitError, match="symlinks"):
            component_directory(root, name)
    assert component_directory(root, ".") == root


def test_locked_python_and_nested_node_plan_is_frozen_without_changing_legacy_shape(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths=["backend/tests", "host-runner/tests"]\n'
    )
    for name in ("backend", "host-runner"):
        tests = tmp_path / name / "tests"
        tests.mkdir(parents=True)
        (tests / "test_example.py").write_text("def test_ok(): assert True\n")
    lock = tmp_path / "requirements-dev.lock"
    lock.write_text("pytest==8.3.5\nruff==0.8.0\n")
    front = tmp_path / "frontend"
    front.mkdir()
    (front / "package.json").write_text(
        '{"scripts":{"test":"vitest run","lint":"eslint .","build":"vite build"}}'
    )
    legacy = manifest_snapshot(tmp_path)
    assert set(legacy) == {"requirements.txt", "pyproject.toml", "package.json"}
    assert not plan_workspace(tmp_path)["commands"]
    environment = ValidationEnvironment(
        python_manifest="requirements-dev.lock",
        node_directory="frontend",
        python_source_roots=["backend", "host-runner"],
    )
    plan = plan_workspace(tmp_path, install_dependencies=True, validation_environment=environment)
    assert plan["ecosystems"] == ["python", "node"]
    assert {tuple(command["argv"]) for command in plan["commands"]} == {
        (".venv/bin/python", "-m", "pytest", "-q"),
        *(("npm", "--prefix=frontend", "run", kind) for kind in ("test", "lint", "build")),
    }
    assert load_specifiers(tmp_path, manifest="requirements-dev.lock") == (
        "requirements-dev.lock",
        ["pytest==8.3.5", "ruff==0.8.0"],
    )
    verify_manifests(tmp_path, plan["manifest_snapshot"], python_manifest="requirements-dev.lock")
    lock.write_text("pytest==8.4.0\n")
    with pytest.raises(GitError, match="changed"):
        verify_manifests(tmp_path, plan["manifest_snapshot"], python_manifest="requirements-dev.lock")
    verify_manifests(tmp_path, legacy)


def test_named_manifest_cannot_select_paths_or_pip_flags(tmp_path):
    for name in ("../requirements.txt", "/etc/passwd", "--index-url"):
        with pytest.raises(GitError, match="Unsupported"):
            load_specifiers(tmp_path, manifest=name)


def test_component_manifest_changes_cannot_reuse_frozen_node_snapshot(tmp_path):
    front = tmp_path / "frontend"
    front.mkdir()
    (front / "package.json").write_text("{}")
    plan = plan_workspace(tmp_path, validation_environment={"node_directory": "frontend"})
    (front / "package.json").write_text('{"scripts":{"build":"changed"}}')
    with pytest.raises(GitError, match="changed"):
        verify_manifests(front, plan["node_manifest_snapshot"])


def test_configured_node_component_cannot_silently_skip_missing_manifest(tmp_path):
    (tmp_path / "frontend").mkdir()
    with pytest.raises(GitError, match="requires package.json"):
        plan_workspace(tmp_path, validation_environment={"node_directory": "frontend"})


def test_all_configured_pytest_directories_are_validated_even_after_a_test_is_found(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_ok.py").write_text("def test_ok(): assert True\n")
    (tmp_path / "requirements-dev.lock").write_text("pytest==8.3.5\n")
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["tests", "../outside"]\n')
    with pytest.raises(ValueError, match="canonical relative"):
        plan_workspace(tmp_path, validation_environment={"python_manifest": "requirements-dev.lock"})


def test_dependency_os_metadata_grant_is_bounded_and_available_offline(tmp_path):
    from pathlib import Path

    from ai_station_runner.coding_sandbox import dependency_policy, validation_policy

    root = tmp_path / "worktree"
    root.mkdir()
    common = tmp_path / "metadata"
    common.mkdir()
    ordinary = validation_policy(root, common)["sandbox"]
    offline = dependency_policy(root, common, network=False)["sandbox"]
    assert offline["networkAccess"] is False
    assert set(offline["hardcodedReadPaths"]) - set(ordinary["hardcodedReadPaths"]) == {
        path for path in ("/etc/os-release", "/etc/debian_version", "/etc/mime.types") if Path(path).is_file()
    }
    assert not {"/etc", "/proc", "/home", "/tmp"}.intersection(offline["hardcodedReadPaths"])
