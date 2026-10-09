from pathlib import Path

import pytest
from ai_station_runner.dependency_manifest import (
    PYPI_INDEX,
    confirm_public_indexes,
    load_specifiers,
    parse_pyproject,
    parse_requirements,
    pip_plan,
)
from ai_station_runner.gitops import GitError


def test_requirements_accept_pins_and_reject_urls_and_flags():
    assert parse_requirements("hello-dep==0.0.1\n# comment\n") == ["hello-dep==0.0.1"]
    assert parse_requirements("pkg[extra]>=1.0,<2; python_version>='3.12'\n") == [
        "pkg[extra]>=1.0,<2; python_version>='3.12'"
    ]
    for invalid in (
        "git+https://example.com/repo.git",
        "pkg @ https://example.com/pkg.whl",
        "--index-url https://example.com/simple",
        "-r other.txt",
        "-e .",
        "http://127.0.0.1/evil.whl",
        "../escape.whl",
        "/tmp/evil.whl",
    ):
        with pytest.raises(GitError):
            parse_requirements(invalid)


def test_pyproject_reads_project_dependencies_only():
    text = """
[project]
name = "demo"
dependencies = ["hello-dep==0.0.1"]
[project.optional-dependencies]
dev = ["pytest"]
"""
    assert parse_pyproject(text) == ["hello-dep==0.0.1"]
    with pytest.raises(GitError):
        parse_pyproject("[project]\ndependencies = ['pkg @ https://example.com/p.whl']\n")


def test_vendor_plan_is_offline_and_pypi_plan_uses_public_index(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirements.txt").write_text("hello-dep==0.0.1\n")
    python = Path(".venv/bin/python")
    kind, specifiers = load_specifiers(workspace)
    pypi = pip_plan(workspace, python, specifiers)
    assert kind == "requirements.txt"
    assert pypi["source"] == "pypi" and pypi["network"] is True
    assert "--index-url" in pypi["argv"] and PYPI_INDEX in pypi["argv"]
    assert "--no-index" not in pypi["argv"]
    vendor = workspace / "vendor"
    vendor.mkdir()
    (vendor / "hello_dep-0.0.1-py3-none-any.whl").write_bytes(b"PK")
    local = pip_plan(workspace, python, specifiers)
    assert local["source"] == "vendor" and local["network"] is False
    assert local["argv"][-1] == "hello-dep==0.0.1"
    assert "--no-index" in local["argv"] and "--find-links" in local["argv"]
    (workspace / "requirements.txt").write_text("vendor/hello_dep-0.0.1-py3-none-any.whl\n")
    _, wheels = load_specifiers(workspace)
    wheel_plan = pip_plan(workspace, python, wheels)
    assert "vendor/hello_dep-0.0.1-py3-none-any.whl" in wheel_plan["specifiers"]


def test_command_environment_omits_inherited_secrets_and_points_home_at_scratch(monkeypatch, tmp_path):
    from ai_station_runner.dependency_job import command_environment

    monkeypatch.setenv("AI_STATION_TEST_SECRET", "disposable-fixture")
    monkeypatch.setenv("PIP_INDEX_URL", "http://127.0.0.1/simple")
    env = command_environment(tmp_path / "scratch")
    assert "AI_STATION_TEST_SECRET" not in env
    assert "PIP_INDEX_URL" not in env
    assert env["HOME"] == env["TMPDIR"] == str(tmp_path / "scratch")
    assert env["PIP_CONFIG_FILE"] == "/dev/null"


def test_pypi_hosts_must_resolve_to_public_addresses(monkeypatch):
    monkeypatch.setattr(
        "ai_station_runner.dependency_manifest.public_addresses",
        lambda host: (_ for _ in ()).throw(ValueError("Refusing a non-public network address")),
    )
    with pytest.raises(ValueError, match="non-public"):
        confirm_public_indexes()
