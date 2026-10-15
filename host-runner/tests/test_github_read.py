import os
import sys
import time
from uuid import uuid4

import pytest
from ai_station_runner import github_read as github
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.processes import ProcessManager
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("AI_STATION_ALLOWED_ROOTS", str(tmp_path))
    clear_settings_cache()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cli = bindir / "gh"
    cli.write_text(
        f"#!{sys.executable}\nimport json,sys,time\np=sys.argv[-1]\nif p.endswith('/pulls?state=open&per_page=30') or p.endswith('/issues?state=open&per_page=30'):print('[]')\nelse:print(json.dumps({{'name':'owner/repo','url':'https://github.com/owner/repo','private':True,'default_branch':'develop','description':''}}))\n"
    )
    cli.chmod(0o700)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    yield tmp_path, cli
    clear_settings_cache()


def request():
    return github.GithubReadRequest(
        run_id=uuid4(), repository="owner/repo", permissions=sorted(github.PERMISSIONS)
    )


def wait(manager, run_id):
    deadline = time.monotonic() + 15
    while True:
        result = manager.inspect(run_id)
        if not result["alive"] and not result.get("completion_pending"):
            return result
        assert time.monotonic() < deadline
        time.sleep(0.05)


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "-owner/repo",
        "owner/..",
        "owner/.",
        "https://github.com/a/b",
        "owner/repo?x=1",
        "owner/repo.git",
        "owner/repo/extra",
    ],
)
def test_repository_boundary(name):
    with pytest.raises(ValidationError):
        github.GithubReadRequest(run_id=uuid4(), repository=name, permissions=[])


def test_native_permissions_and_no_arbitrary_operation(configured):
    from ai_station_runner.app import app

    body = request().model_dump(mode="json")
    with TestClient(app) as client:
        assert (
            client.post("/v1/runs/github-read", json={**body, "permissions": ["network_read"]}).status_code
            == 403
        )
        assert client.post("/v1/runs/github-read", json={**body, "operation": "delete"}).status_code == 422
        assert (
            client.post("/v1/runs/github-read", json={**body, "command": "gh issue close 1"}).status_code
            == 422
        )


def test_owned_dispatch_replay_and_report(configured):
    manager = ProcessManager(configured[0] / "data")
    body = request()
    rid = str(body.run_id)
    process = github.start(manager, body)
    assert github.start(manager, body)["pid"] == process["pid"]
    assert wait(manager, rid)["exit_code"] == 0
    report = github.report(manager, rid)
    assert report["repository"] == "owner/repo" and report["issues"] == []
    assert (github.directory(rid) / "request.json").stat().st_mode & 0o777 == 0o600
    changed = body.model_copy(update={"repository": "other/repo"})
    with pytest.raises(ValueError):
        github.start(manager, changed)


def test_cancellation_owns_only_job_group_and_never_adopts_report(configured):
    _, cli = configured
    cli.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    manager = ProcessManager(configured[0] / "data", grace_seconds=0.1)
    body = request()
    rid = str(body.run_id)
    record = github.start(manager, body)
    assert record["pid"] == record["process_group_id"]
    time.sleep(0.2)
    manager.cancel(rid)
    assert not wait(manager, rid)["alive"]
    with pytest.raises((ValueError, FileNotFoundError)):
        github.report(manager, rid)


def test_credential_errors_are_not_exposed(configured):
    _, cli = configured
    cli.write_text(
        f'#!{sys.executable}\nimport sys\nprint("ghp_privatecredential",file=sys.stderr)\nsys.exit(1)\n'
    )
    manager = ProcessManager(configured[0] / "data")
    body = request()
    rid = str(body.run_id)
    github.start(manager, body)
    assert wait(manager, rid)["exit_code"] != 0
    logs = (configured[0] / f"data/runs/{rid}/stderr.log").read_text()
    assert "privatecredential" not in logs and "GitHub snapshot failed" in logs
