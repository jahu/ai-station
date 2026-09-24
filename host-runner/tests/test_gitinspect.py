import subprocess
import sys

import pytest
from ai_station_runner.app import app
from ai_station_runner.config import clear_settings_cache
from ai_station_runner.gitinspect import diff, status, validate_repo
from ai_station_runner.gitops import GitError
from fastapi.testclient import TestClient


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repo = tmp_path / "allowed/repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "develop")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "file.txt").write_text("before\n")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-m", "initial")
    monkeypatch.setenv("AI_STATION_ALLOWED_ROOTS", str(repo.parent))
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    yield repo
    clear_settings_cache()


def test_read_only_status_and_diff_never_invoke_repository_programs(repo):
    marker = repo / "helper-invoked"
    helper = repo / "helper.sh"
    helper.write_text(f'#!/bin/sh\ntouch "{marker}"\ncat\n')
    helper.chmod(0o700)
    for key in (
        "core.fsmonitor",
        "diff.external",
        "diff.custom.textconv",
        "filter.custom.clean",
        "filter.custom.process",
        "filter.custom.smudge",
    ):
        git(repo, "config", key, str(helper))
    git(repo, "config", "filter.custom.required", "true")
    (repo / ".gitattributes").write_text("*.txt filter=custom diff=custom\n")
    (repo / "file.txt").write_text("after\n")
    before = (repo / ".git/index").read_bytes()
    assert status(repo)["dirty"]
    assert "+after" in diff(repo, None)["diff"]
    assert not marker.exists()
    assert (repo / ".git/index").read_bytes() == before
    assert git(repo, "config", "filter.custom.clean") == str(helper)


def test_option_injection_rejected_at_api(repo):
    output = repo / "should-not-exist"
    with TestClient(app) as client:
        for base in [f"--output={output}", "--no-index", "develop..HEAD", "HEAD~1"]:
            response = client.post("/v1/git/diff", json={"repo_path": str(repo), "base": base})
            assert response.status_code == 422, response.text
        assert (
            client.post("/v1/git/status", json={"repo_path": str(repo), "command": "anything"}).status_code
            == 422
        )
    assert not output.exists()


def test_git_environment_cannot_redirect_repository(repo, tmp_path, monkeypatch):
    other = tmp_path / "unrelated"
    other.mkdir()
    git(other, "init", "-b", "other")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert validate_repo(repo)["repo_path"] == str(repo)
    assert status(repo)["branch"] == "develop"


def test_repository_metadata_must_stay_in_allowed_roots(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "metadata"
    (repo / ".git").rename(external)
    (repo / ".git").write_text(f"gitdir: {external}\n")
    with pytest.raises(GitError, match="outside"):
        validate_repo(repo)


def test_partial_clone_and_alternate_stores_fail_closed(repo):
    git(repo, "config", "remote.origin.promisor", "true")
    with pytest.raises(GitError, match="Partial clone"):
        status(repo)
    git(repo, "config", "--unset", "remote.origin.promisor")
    (repo / ".git/objects/info/alternates").write_text("/outside/objects\n")
    with pytest.raises(GitError, match="alternate"):
        validate_repo(repo)


def test_branch_comparison_and_empty_repository(repo):
    before = git(repo, "rev-parse", "HEAD")
    (repo / "file.txt").write_text("committed change\n")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-m", "second")
    assert "+committed change" in diff(repo, before)["diff"]
    empty = repo.parent / "empty"
    empty.mkdir()
    git(empty, "init", "-b", "develop")
    assert status(empty)["branch"] == "develop"
    assert diff(empty, None)["diff"] == ""


@pytest.mark.parametrize("failure", ["output", "timeout"])
def test_bounded_inspection_terminates_its_process(repo, monkeypatch, failure):
    from ai_station_runner import gitinspect

    original = subprocess.Popen
    processes = []
    script = "import time; time.sleep(30)" if failure == "timeout" else 'print("x"*10000)'

    def fake(*args, **kwargs):
        process = original([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(gitinspect.subprocess, "Popen", fake)
    monkeypatch.setattr(gitinspect, "TIMEOUT", 0.1 if failure == "timeout" else 5)
    monkeypatch.setattr(gitinspect, "MAX_OUTPUT", 100)
    with pytest.raises(GitError, match="limit"):
        gitinspect._read(repo, ["version"])
    assert processes[0].poll() is not None
