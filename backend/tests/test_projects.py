import importlib
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from ai_station_runner.app import app as runner_app
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import reset_engine, session_factory
from app.engine import tick
from app.models import Project
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import create_run, create_task, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def repository(tmp_path, monkeypatch):
    repo = tmp_path / "repos/example"
    repo.mkdir(parents=True)
    for args in (
        ["init", "-b", "develop"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.invalid"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "README.md").write_text("Original repository\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Initial"], check=True, capture_output=True)
    monkeypatch.setenv("AI_STATION_ALLOWED_ROOTS", str(repo.parent))
    monkeypatch.setenv("AI_STATION_MODEL_ROOTS", "")
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path / "data"))
    clear_settings_cache()
    monkeypatch.setattr(RunnerClient, "_client", lambda _: TestClient(runner_app))
    yield repo
    clear_settings_cache()


def register(client, repo, **extra):
    response = client.post("/api/projects", json={"name": "Example", "repo_path": str(repo), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def settings(project, **extra):
    return {
        **{
            key: value
            for key, value in project.items()
            if key not in {"id", "repo_path", "created_at", "updated_at"}
        },
        "expected_updated_at": project["updated_at"],
        **extra,
    }


def test_project_roundtrip_real_git_status_and_restart(repository):
    before = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(client, repository, test_commands=[["pytest", "-q"]])
        path = f"/api/projects/{project['id']}"
        assert project["protected_branches"] == ["main", "master"]
        assert client.get(path + "/status").json()["dirty"] is False
        (repository / "README.md").write_text("Changed by the test, not the application\n")
        status = client.get(path + "/status").json()
        assert status["dirty"] is True
        assert status["branch"] == "develop"
        assert "README.md" in status["porcelain"]
        assert status["checked_at"]
        reset_engine()
        assert client.get(path).json() == project
        assert client.get("/api/projects").json() == [project]
        assert client.get("/api/projects?offset=1").json() == []
        assert client.get("/api/runs").json() == []
    assert (repository / ".git/index").read_bytes() == before


def test_canonical_duplicate_registration_and_path_boundary(repository, tmp_path):
    nested = repository / "nested"
    nested.mkdir()
    alias = repository.parent / "alias"
    alias.symlink_to(repository, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = repository.parent / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    with TestClient(app) as client:
        project = register(client, nested)
        assert project["repo_path"] == str(repository)
        assert (
            client.post("/api/projects", json={"name": "Duplicate", "repo_path": str(alias)}).status_code
            == 409
        )
        assert (
            client.post("/api/projects", json={"name": "Escape", "repo_path": str(escape)}).status_code == 422
        )
        assert len(client.get("/api/projects").json()) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"name": "  "},
        {"default_branch": "--output=bad"},
        {"integration_branch": "HEAD~1"},
        {"protected_branches": ["bad..branch"]},
        {"test_commands": ["pytest -q"]},
        {"build_commands": [["npm\u0000", "run"]]},
        {"test_commands": [[]]},
        {"pr_policy": {"force_push": True}},
        {"pr_policy": {"automatic_merge": True}},
        {"pr_policy": {"pr_to_production": True}},
        {"preferred_executor": "shell"},
        {"repo_path": "../repository"},
    ],
)
def test_invalid_configuration_is_rejected_without_host_access(invalid, monkeypatch):
    monkeypatch.setattr(
        RunnerClient, "validate_project", lambda *_: pytest.fail("Invalid request reached runner")
    )
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/projects", json={"name": "Example", "repo_path": "/unused", **invalid}
            ).status_code
            == 422
        )


def test_edit_preserves_protections_rejects_stale_and_active_run(repository):
    with TestClient(app) as client:
        project = register(client, repository)
        path = f"/api/projects/{project['id']}"
        updated = client.put(
            path,
            json=settings(
                project,
                default_branch="release",
                protected_branches=[],
                agent_rules="Keep public interfaces stable",
            ),
        )
        assert updated.status_code == 200, updated.text
        new = updated.json()
        assert new["protected_branches"] == ["main", "master", "release"]
        assert client.put(path, json=settings(project)).status_code == 409
        assert client.put(path, json=settings(new, repo_path="/different")).status_code == 422
        with session_factory()() as session:
            task = create_task(
                session, title="Queued", prompt="", capability="system.self_test", project_id=project["id"]
            )
            run = create_run(
                session, task, run_type="test", capability="system.self_test", executor_type="fake"
            )
            session.commit()
            assert client.put(path, json=settings(new)).status_code == 409
            request_cancel(session, run)
            session.commit()
        assert client.put(path, json=settings(new)).status_code == 200


def test_runner_outage_does_not_hide_or_overwrite_saved_project(repository, monkeypatch):
    with TestClient(app) as client:
        project = register(client, repository)

        def unavailable(*_):
            raise RunnerUnavailable("offline")

        monkeypatch.setattr(RunnerClient, "validate_project", unavailable)
        assert client.get(f"/api/projects/{project['id']}/status").status_code == 503
        assert client.get(f"/api/projects/{project['id']}").json() == project
        assert (
            client.post("/api/projects", json={"name": "Other", "repo_path": str(repository)}).status_code
            == 503
        )
        assert len(client.get("/api/projects").json()) == 1


def test_concurrent_alias_registration_is_atomic(repository, monkeypatch):
    original = RunnerClient.validate_project
    barrier = Barrier(2)

    def synchronized(self, path):
        result = original(self, path)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(RunnerClient, "validate_project", synchronized)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:

        def submit(_):
            return client.post(
                "/api/projects", json={"name": "Concurrent", "repo_path": str(repository)}
            ).status_code

        assert sorted(pool.map(submit, range(2))) == [201, 409]
    with session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 1


def test_host_inspection_never_holds_database_reservation(repository, monkeypatch):
    original = RunnerClient.validate_project

    def probe(self, path):
        # A separate writer must be able to commit while the runner call is in flight.
        with session_factory()() as session:
            create_task(session, title="Independent writer", prompt="", capability="system.self_test")
            session.commit()
        return original(self, path)

    monkeypatch.setattr(RunnerClient, "validate_project", probe)
    with TestClient(app) as client:
        project = register(client, repository)
        assert client.get(f"/api/projects/{project['id']}/status").status_code == 200


@pytest.fixture
def owned_runner(repository):
    module = importlib.import_module("ai_station_runner.app")
    module.reset_manager()
    yield module.manager()
    module.manager().shutdown()
    module.reset_manager()


def enqueue_worktree(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/worktrees", json={"expected_updated_at": project["updated_at"]}
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_owned_worktree_run_preserves_checkout_and_registers_report(repository, owned_runner):
    (repository / "README.md").write_text("User's uncommitted change\n")
    original_index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)
        assert run["status"] == "queued"
        assert "external_ai" not in run["effective_permissions"]
        with session_factory()() as session:
            tick(session, "worktree-test")
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == "succeeded", result
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert worktree["owned"] is True
        assert worktree["branch"] == f"ai/{run['id']}-workspace"
        assert worktree["run_status"] == "succeeded"
        destination = owned_runner.data_dir / worktree["relative_path"]
        assert (destination / "README.md").read_text() == "Original repository\n"
        (destination / "README.md").write_text("Future agent's isolated change\n")
        assert (repository / "README.md").read_text() == "User's uncommitted change\n"
        assert (repository / ".git/index").read_bytes() == original_index
        artifacts = client.get(f"/api/artifacts?run_id={run['id']}").json()
        assert artifacts[0]["type"] == "json"
        assert "git.worktree.created" in client.get(f"/api/runs/{run['id']}/stream").text
        reset_engine()
        assert client.get(f"/api/projects/{project['id']}/worktrees").json()[0] == worktree


def test_preparation_does_not_run_checkout_hooks_or_filters(repository, owned_runner):
    marker = repository / "hook-ran"
    helper = repository / ".git/hooks/post-checkout"
    helper.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    helper.chmod(0o700)
    # An attributes file in the committed tree exercises checkout filters too.
    (repository / ".gitattributes").write_text("README.md filter=danger\n")
    subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(repository), "add", ".gitattributes"], check=True
    )
    subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(repository), "commit", "-m", "Attributes"],
        check=True,
        capture_output=True,
    )
    for key in ("filter.danger.clean", "filter.danger.smudge", "core.fsmonitor"):
        subprocess.run(["git", "-C", str(repository), "config", key, str(helper)], check=True)
    assert not marker.exists()
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)
        with session_factory()() as session:
            tick(session, "worktree-test")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
    assert not marker.exists()


def test_worktree_dispatch_replay_and_conflicts(repository, owned_runner):
    from uuid import uuid4

    payload = {
        "run_id": str(uuid4()),
        "project_id": str(uuid4()),
        "repo_path": str(repository),
        "base_branch": "develop",
        "permissions": ["filesystem_read", "workspace_write", "git_read", "git_write"],
    }
    with TestClient(runner_app) as client:
        started = client.post("/v1/runs/worktree", json=payload)
        assert started.status_code == 200, started.text
        replay = client.post("/v1/runs/worktree", json=payload)
        assert replay.json()["pid"] == started.json()["pid"]
        assert client.post("/v1/runs/worktree", json={**payload, "base_branch": "main"}).status_code == 409
        assert client.post("/v1/runs/worktree", json={**payload, "branch": "main"}).status_code == 422
        assert client.post("/v1/runs/worktree", json={**payload, "permissions": []}).status_code == 403


def test_lost_worktree_dispatch_preserves_reservation_for_inspection(repository, owned_runner, monkeypatch):
    original = RunnerClient.prepare_worktree

    def lost(self, payload):
        original(self, payload)
        raise RunnerUnavailable("Response lost after native launch")

    monkeypatch.setattr(RunnerClient, "prepare_worktree", lost)
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)
        with session_factory()() as session:
            tick(session, "lost-worker")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "preparing"
        deadline = time.monotonic() + 10
        while owned_runner.inspect(run["id"])["alive"] and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not owned_runner.inspect(run["id"])["alive"]
        with session_factory()() as session:
            recover_stale(session)
            session.commit()
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "interrupted"
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert not worktree["owned"]
        assert (owned_runner.data_dir / worktree["relative_path"]).is_dir()


def test_worktree_cancellation_only_terminates_owned_group(repository, owned_runner, monkeypatch):
    import sys

    original_start = owned_runner.start

    def slow(**kwargs):
        kwargs["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        return original_start(**kwargs)

    monkeypatch.setattr(owned_runner, "start", slow)
    original = RunnerClient.prepare_worktree
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)

        def cancel_during_dispatch(self, payload):
            result = original(self, payload)
            assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
            return result

        monkeypatch.setattr(RunnerClient, "prepare_worktree", cancel_during_dispatch)
        with session_factory()() as session:
            tick(session, "cancel-worker")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert not owned_runner.inspect(run["id"])["alive"]
        assert not client.get(f"/api/projects/{project['id']}/worktrees").json()[0]["owned"]


def test_worktree_destination_symlink_and_missing_base_are_rejected(repository, owned_runner):
    with TestClient(app) as client:
        project = register(client, repository, integration_branch="missing")
        run = enqueue_worktree(client, project)
        with session_factory()() as session:
            tick(session, "invalid-base")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        current = client.put(f"/api/projects/{project['id']}", json=settings(project)).json()
        current = client.put(
            f"/api/projects/{project['id']}", json=settings(current, integration_branch="develop")
        ).json()
        run = enqueue_worktree(client, current)
        root = owned_runner.data_dir / "worktrees"
        root.mkdir(exist_ok=True)
        (root / project["id"]).symlink_to(repository, target_is_directory=True)
        with session_factory()() as session:
            tick(session, "invalid-path")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        assert not (repository / run["id"]).exists()


def test_preparation_timeout_terminates_its_group_and_preserves_manifest(
    repository, owned_runner, monkeypatch
):
    import sys

    original = owned_runner.start

    def expire(**kwargs):
        run_id = kwargs["run_id"]
        kwargs["argv"] = [
            sys.executable,
            "-c",
            f"from ai_station_runner import worktree_job as job; job.TIMEOUT=0; job.prepare({run_id!r})",
        ]
        return original(**kwargs)

    monkeypatch.setattr(owned_runner, "start", expire)
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)
        with session_factory()() as session:
            tick(session, "timeout-worker")
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == "failed", result
        assert "timed out" in result["error_message"]
        assert not owned_runner.inspect(run["id"])["alive"]
        assert (owned_runner.data_dir / f"runtime/worktree-requests/{run['id']}.json").exists()


def test_preparation_requires_permissions_before_dispatch(repository, owned_runner, monkeypatch):
    from app.models import Run

    monkeypatch.setattr(RunnerClient, "prepare_worktree", lambda *_: pytest.fail("Unauthorized dispatch"))
    with TestClient(app) as client:
        project = register(client, repository)
        run = enqueue_worktree(client, project)
        with session_factory()() as session:
            session.get(Run, run["id"]).effective_permissions = ["git_read"]
            session.commit()
            tick(session, "permission-worker")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "failed"
        assert not (owned_runner.data_dir / f"runtime/worktree-requests/{run['id']}.json").exists()


@pytest.fixture
def validation_sandbox(tmp_path, monkeypatch):
    """A disposable fake helper for CI; real isolation has a separate opt-in probe."""
    import os

    if os.environ.get("AI_STATION_REAL_SANDBOX_TESTS") == "1":
        return
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "cursor-agent").write_text("#!/bin/sh\nexit 0\n")
    helper = binaries / "cursorsandbox"
    helper.write_text(
        "#!/usr/bin/python3\nimport os,sys,pathlib\n"
        "policy=pathlib.Path(sys.argv[sys.argv.index('--policy')+1]); policy.read_text(); policy.unlink()\n"
        "argv=sys.argv[sys.argv.index('--')+1:]\nos.execvpe(argv[0],argv,os.environ)\n"
    )
    helper.chmod(0o700)
    (binaries / "cursor-agent").chmod(0o700)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")


def prepared_validation(client, repository, commands):
    project = register(client, repository, test_commands=commands)
    preparation = enqueue_worktree(client, project)
    with session_factory()() as session:
        tick(session, "prepare-validation")
    assert client.get(f"/api/runs/{preparation['id']}").json()["status"] == "succeeded"
    worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
    return project, worktree


def enqueue_validation(client, project, worktree, **extra):
    return client.post(
        f"/api/projects/{project['id']}/worktrees/{worktree['id']}/validate",
        json={"expected_updated_at": project["updated_at"], **extra},
    )


@pytest.mark.parametrize("exit_code", [0, 3])
def test_validation_reports_exit_codes_and_preserves_original_checkout(
    repository, owned_runner, validation_sandbox, exit_code
):
    original_index = (repository / ".git/index").read_bytes()
    commands = [
        [
            "/usr/bin/python3",
            "-c",
            f"from pathlib import Path; Path('result.txt').write_text('ok'); print('test output'); raise SystemExit({exit_code})",
        ],
        [
            "/usr/bin/python3",
            "-c",
            "from pathlib import Path; assert Path('result.txt').read_text() == 'ok'; print('second command passed')",
        ],
    ]
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, commands)
        response = enqueue_validation(client, project, worktree)
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["parameters"]["commands"] == [{"kind": "test", "argv": argv} for argv in commands]
        assert enqueue_validation(client, project, worktree).status_code == 409
        with session_factory()() as session:
            tick(session, "validation-test")
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == ("succeeded" if exit_code == 0 else "failed"), result
        assert [item["exit_code"] for item in result["metadata"]["validation"]["commands"]] == [exit_code, 0]
        assert result["parent_run_id"] == worktree["run_id"]
        stream = client.get(f"/api/runs/{run['id']}/stream").text
        assert "test output" in stream and "validation.completed" in stream and "artifact.created" in stream
        assert "second command passed" in stream
        assert (owned_runner.data_dir / f"runtime/validation/{run['id']}.policy.json").exists()
        assert (owned_runner.data_dir / worktree["relative_path"] / "result.txt").read_text() == "ok"
    assert (repository / ".git/index").read_bytes() == original_index
    assert not (repository / "result.txt").exists()


def test_validation_api_rejects_stale_unowned_injected_commands_and_missing_settings(
    repository, owned_runner
):
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [])
        assert enqueue_validation(client, project, worktree).status_code == 422
        assert enqueue_validation(client, project, worktree, commands=[["true"]]).status_code == 422
        assert (
            enqueue_validation(
                client, project, worktree, expected_updated_at="2000-01-01T00:00:00"
            ).status_code
            == 409
        )
        from app.models import Worktree

        with session_factory()() as session:
            session.get(Worktree, worktree["id"]).owned = False
            session.commit()
        assert enqueue_validation(client, project, worktree).status_code == 409


def test_validation_runner_idempotence_permissions_and_cancellation(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    from uuid import uuid4

    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [["/usr/bin/sleep", "30"]])
        payload = {
            "run_id": str(uuid4()),
            "project_id": project["id"],
            "worktree_run_id": worktree["run_id"],
            "commands": [{"kind": "test", "argv": ["/usr/bin/sleep", "30"]}],
            "permissions": ["filesystem_read", "workspace_write", "git_read", "shell_project_commands"],
        }
        with TestClient(runner_app) as native:
            assert native.post("/v1/runs/validation", json={**payload, "permissions": []}).status_code == 403
            assert (
                native.post(
                    "/v1/runs/validation",
                    json={**payload, "commands": [{"kind": "test", "argv": ["bash", "-c", "true"]}]},
                ).status_code
                == 422
            )
            started = native.post("/v1/runs/validation", json=payload)
            assert started.status_code == 200, started.text
            replay = native.post("/v1/runs/validation", json=payload)
            assert replay.json()["pid"] == started.json()["pid"]
            assert (
                native.post(
                    "/v1/runs/validation", json={**payload, "commands": [{"kind": "test", "argv": ["true"]}]}
                ).status_code
                == 409
            )
            # Allow the wrapper to dispatch a child before canceling its group.
            time.sleep(0.5)
            native.post("/v1/process/cancel", json={"run_id": payload["run_id"]})
            assert not owned_runner.inspect(payload["run_id"])["alive"]
            assert native.get(f"/v1/validation/{payload['run_id']}").status_code == 409
        original = RunnerClient.start_validation
        response = enqueue_validation(client, project, worktree)
        run = response.json()

        def cancel_on_dispatch(self, body):
            result = original(self, body)
            client.post(f"/api/runs/{run['id']}/cancel")
            return result

        monkeypatch.setattr(RunnerClient, "start_validation", cancel_on_dispatch)
        with session_factory()() as session:
            tick(session, "cancel-validation")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert not owned_runner.inspect(run["id"])["alive"]


def test_validation_limits_kill_owned_group_without_publishing_success(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    import sys

    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [["/usr/bin/sleep", "30"]])
        original = owned_runner.start

        def limited(**kwargs):
            run_id = kwargs["run_id"]
            kwargs["argv"] = [
                sys.executable,
                "-c",
                f"from ai_station_runner import validation_job as job; job.TIMEOUT=0; job.validate({run_id!r})",
            ]
            return original(**kwargs)

        monkeypatch.setattr(owned_runner, "start", limited)
        response = enqueue_validation(client, project, worktree)
        run = response.json()
        with session_factory()() as session:
            tick(session, "limited-validation")
        result = client.get(f"/api/runs/{run['id']}").json()
        assert result["status"] == "failed", result
        assert "time/output limit" in result["error_message"]
        assert "validation" not in result["metadata"]
        assert not owned_runner.inspect(run["id"])["alive"]


def test_validation_does_not_inherit_runner_credentials(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    monkeypatch.setenv("AI_STATION_TEST_SECRET", "disposable-fixture")
    command = [
        "/usr/bin/python3",
        "-c",
        "import os; from pathlib import Path; assert 'AI_STATION_TEST_SECRET' not in os.environ; assert Path(os.environ['HOME']).is_relative_to(Path.cwd()); assert os.environ['HOME']==os.environ['TMPDIR']",
    ]
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [command])
        response = enqueue_validation(client, project, worktree)
        run = response.json()
        with session_factory()() as session:
            tick(session, "environment-validation")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"


@pytest.fixture
def fake_cursor(validation_sandbox, tmp_path, monkeypatch):
    import os

    binary_dir = tmp_path / "cursor-bin"
    binary_dir.mkdir()
    binary = binary_dir / "cursor-agent"
    binary.write_text("""#!/usr/bin/python3
import json, os, pathlib, sys
args=sys.argv
assert args[args.index('--allowed-tools')+1] == ''
assert pathlib.Path.cwd() == pathlib.Path(args[args.index('--workspace')+1])
assert (pathlib.Path.cwd()/'.git/HEAD').read_text().strip() == 'ref: refs/heads/ai-proposal'
config=json.loads((pathlib.Path(os.environ['HOME'])/'.cursor/cli-config.json').read_text())
assert config['permissions']['deny'] == ['Shell(*)','Read(**)','Write(**)']
assert 'AI_STATION_TEST_SECRET' not in os.environ
print(json.dumps({'type':'system','subtype':'init','session_id':'fixture','model':'Fake'}))
result={'summary':'Updated selected source','files':[{'path':'README.md','content':'Updated by Cursor fixture\\n'},{'path':'new.py','content':'print(42)\\n'}]}
if 'SECOND_TURN' in args[-1]:result={'summary':'Second turn','files':[{'path':'more.py','content':'print(43)\\n'}]}
if args[-1].startswith('Select source files'):result={'tool':'finish','files':['more.py'] if 'SECOND_TURN' in args[-1] else ['README.md','new.py']}
print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':json.dumps(result),'session_id':'fixture'}))
""")
    binary.chmod(0o700)
    # Preserve the fake native helper by placing it next to this CLI too.
    import shutil

    helper = shutil.which("cursor-agent")
    (binary_dir / "cursorsandbox").symlink_to(__import__("pathlib").Path(helper).parent / "cursorsandbox")
    monkeypatch.setenv("PATH", f"{binary_dir}:{os.environ['PATH']}")
    return binary


def coding_request(project, **extra):
    return {
        "project_id": project["id"],
        "expected_updated_at": project["updated_at"],
        "prompt": "Update selected source files",
        "files": ["README.md", "new.py"],
        "external_ai": True,
        **extra,
    }


def test_cursor_task_prepares_applies_reviews_and_validates_without_touching_checkout(
    repository, owned_runner, fake_cursor, monkeypatch
):
    monkeypatch.setenv("AI_STATION_TEST_SECRET", "disposable")
    (repository / "README.md").write_text("Original human edit\n")
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(client, repository, test_commands=[["/usr/bin/python3", "new.py"]])
        response = client.post("/api/coding/cursor", json=coding_request(project))
        assert response.status_code == 202, response.text
        preparation = response.json()
        with session_factory()() as session:
            tick(session, "coding-prepare")
        prepared = client.get(f"/api/runs/{preparation['id']}").json()
        assert prepared["status"] == "succeeded", prepared
        cursor_id = prepared["metadata"]["coding_run_id"]
        with session_factory()() as session:
            tick(session, "coding-cursor")
        coded = client.get(f"/api/runs/{cursor_id}").json()
        assert coded["status"] == "succeeded", coded
        assert coded["metadata"]["review_status"] == "needs_review"
        assert len(coded["metadata"]["coding_review"]["files"]) == 2
        assert coded["metadata"]["coding_review"]["provider"]["session_id"] == "fixture"
        validation_id = coded["metadata"]["validation_run_id"]
        with session_factory()() as session:
            tick(session, "coding-validation")
        assert client.get(f"/api/runs/{validation_id}").json()["status"] == "succeeded"
        artifacts = client.get(f"/api/artifacts?run_id={cursor_id}").json()
        assert {item["type"] for item in artifacts} == {"git_diff", "json"}
        assert len(client.get(f"/api/projects/{project['id']}/worktrees").json()) == 1
    assert (repository / "README.md").read_text() == "Original human edit\n"
    assert (repository / ".git/index").read_bytes() == index
    assert not (repository / "new.py").exists()


def test_cursor_requires_external_consent_and_preserves_worktree_on_provider_failure(
    repository, owned_runner, fake_cursor
):
    fake_cursor.write_text("#!/usr/bin/python3\nraise SystemExit(3)\n")
    with TestClient(app) as client:
        project = register(client, repository)
        assert (
            client.post("/api/coding/cursor", json=coding_request(project, external_ai=False)).status_code
            == 422
        )
        missing = coding_request(project)
        missing.pop("external_ai")
        assert client.post("/api/coding/cursor", json=missing).status_code == 422
        preparation = client.post("/api/coding/cursor", json=coding_request(project)).json()
        with session_factory()() as session:
            tick(session, "coding-prepare")
        prepared = client.get(f"/api/runs/{preparation['id']}").json()
        cursor_id = prepared["metadata"]["coding_run_id"]
        with session_factory()() as session:
            tick(session, "coding-failure")
        coded = client.get(f"/api/runs/{cursor_id}").json()
        assert coded["status"] == "failed", coded
        assert "validation_run_id" not in coded["metadata"]
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert (
            owned_runner.data_dir / worktree["relative_path"] / "README.md"
        ).read_text() == "Original repository\n"


def test_cursor_cancellation_never_queues_validation_or_changes_source(
    repository, owned_runner, fake_cursor, monkeypatch
):
    fake_cursor.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(30)\n")
    with TestClient(app) as client:
        project = register(client, repository, test_commands=[["true"]])
        preparation = client.post("/api/coding/cursor", json=coding_request(project)).json()
        with session_factory()() as session:
            tick(session, "prepare-cancel")
        prepared = client.get(f"/api/runs/{preparation['id']}").json()
        cursor_id = prepared["metadata"]["coding_run_id"]
        original = RunnerClient.start_cursor_proposal

        def cancel_during_dispatch(self, body):
            result = original(self, body)
            time.sleep(0.5)
            client.post(f"/api/runs/{cursor_id}/cancel")
            return result

        monkeypatch.setattr(RunnerClient, "start_cursor_proposal", cancel_during_dispatch)
        with session_factory()() as session:
            tick(session, "cancel-cursor")
        result = client.get(f"/api/runs/{cursor_id}").json()
        assert result["status"] == "canceled", result
        assert "validation_run_id" not in result["metadata"]
        assert not owned_runner.inspect(cursor_id)["alive"]
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert (
            owned_runner.data_dir / worktree["relative_path"] / "README.md"
        ).read_text() == "Original repository\n"


def prepared_review(client, repository):
    project = register(client, repository, test_commands=[["true"]])
    preparation = client.post("/api/coding/cursor", json=coding_request(project)).json()
    with session_factory()() as session:
        tick(session, "commit-prepare")
        source_id = tick(session, "commit-proposal")
    return project, preparation, client.get(f"/api/runs/{source_id}").json()


def test_reviewed_commit_preserves_checkout_hooks_and_unreviewed_files(repository, owned_runner, fake_cursor):
    from ai_station_runner.worktrees import inspect_worktree

    original_index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, preparation, source = prepared_review(client, repository)
        route = f"/api/coding/runs/{source['id']}/commit"
        body = {"message": "Accept reviewed changes", "reviewed": True}
        assert client.post(route, json=body).status_code == 409
        with session_factory()() as session:
            tick(session, "commit-validation")
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        path = owned_runner.data_dir / worktree["relative_path"]
        (path / "unreviewed.txt").write_text("Do not commit this")
        hook = repository / ".git/hooks/pre-commit"
        hook.write_text(f'#!/bin/sh\ntouch "{repository}/hook-ran"\nexit 1\n')
        hook.chmod(0o700)
        response = client.post(route, json=body)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session_factory()() as session:
            tick(session, "commit-reviewed")
        result = client.get(f"/api/runs/{run_id}").json()
        assert result["status"] == "succeeded", result
        commit = result["metadata"]["git_commit"]["commit"]
        content = subprocess.run(
            ["git", "-C", str(path), "show", f"{commit}:new.py"], capture_output=True, text=True, check=True
        ).stdout
        assert content == "print(42)\n"
        status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
        assert "README.md" not in status and "new.py" not in status
        assert "unreviewed.txt" in status
        assert not (repository / "hook-ran").exists()
        assert (repository / ".git/index").read_bytes() == original_index
        assert (repository / "README.md").read_text() == "Original repository\n"
        assert inspect_worktree(owned_runner, preparation["id"])["head_commit"] == commit
        assert client.post(route, json=body).status_code == 409
        assert client.get(f"/api/runs/{source['id']}").json()["metadata"]["review_status"] == "committed"
        assert "git.commit.created" in client.get(f"/api/runs/{run_id}/stream").text
        payload = {
            "run_id": run_id,
            "project_id": project["id"],
            "permissions": ["filesystem_read", "git_read", "git_write"],
            **{
                key: result["parameters"][key]
                for key in ("source_run_id", "review_digest", "message", "protected_branches")
            },
        }
        with TestClient(runner_app) as host:
            assert host.post("/v1/runs/reviewed-commit", json=payload).status_code == 200
            assert (
                host.post("/v1/runs/reviewed-commit", json={**payload, "message": "changed"}).status_code
                == 422
            )
            assert (
                host.post("/v1/runs/reviewed-commit", json={**payload, "permissions": []}).status_code == 403
            )


@pytest.mark.parametrize("change", ["content", "mode", "staged"])
def test_reviewed_commit_rejects_changed_review(repository, owned_runner, fake_cursor, change):
    with TestClient(app) as client:
        project, _, source = prepared_review(client, repository)
        with session_factory()() as session:
            tick(session, "validate")
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        path = owned_runner.data_dir / worktree["relative_path"]
        if change == "content":
            (path / "README.md").write_text("Changed after review")
        elif change == "mode":
            (path / "README.md").chmod(0o755)
        else:
            subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
        response = client.post(
            f"/api/coding/runs/{source['id']}/commit", json={"message": "Reviewed", "reviewed": True}
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "commit-refused")
        result = client.get(f"/api/runs/{response.json()['id']}").json()
        assert result["status"] == "failed", result
        head = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        assert head == source["metadata"]["coding_review"]["base_commit"]


def test_commit_requires_review_confirmation_and_project_policy(repository, owned_runner, fake_cursor):
    with TestClient(app) as client:
        project, _, source = prepared_review(client, repository)
        route = f"/api/coding/runs/{source['id']}/commit"
        assert client.post(route, json={"message": "Not reviewed", "reviewed": False}).status_code == 422
        with session_factory()() as session:
            tick(session, "validate")
            row = session.get(Project, project["id"])
            row.pr_policy = {**row.pr_policy, "commit_task_branch": False}
            session.commit()
        assert client.post(route, json={"message": "Reviewed", "reviewed": True}).status_code == 403


@pytest.fixture
def local_coding_bridge(owned_runner, tmp_path, monkeypatch):
    """Fake inference by default; real forwarding requires explicit smoke-test opt-in."""
    import json
    import socketserver
    import threading
    from http.server import BaseHTTPRequestHandler

    control = {"mode": "success", "requests": [], "entered": threading.Event(), "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            control["requests"].append((self.path, request))
            control["entered"].set()
            if control["mode"] == "real":
                import httpx

                assert os.environ.get("AI_STATION_REAL_LOCAL_LLM_TESTS") == "1"
                instance = os.environ.get("AI_STATION_SMOKE_LLAMA_INSTANCE")
                model = instance or os.environ["AI_STATION_SMOKE_LOCAL_MODEL"]
                target = f"http://runner/v1/llama/{instance}" if instance else "http://runner/v1/llm"
                headers = (
                    {}
                    if instance
                    else {"X-AI-Station-Endpoint": os.environ["AI_STATION_SMOKE_LOCAL_ENDPOINT"]}
                )
                transport = httpx.HTTPTransport(uds=os.environ["AI_STATION_SMOKE_RUNNER_SOCKET"])
                with httpx.Client(transport=transport, timeout=300, trust_env=False) as upstream:
                    with upstream.stream(
                        "POST",
                        target + "/chat/completions",
                        headers=headers,
                        json={**request, "model": model},
                    ) as response:
                        self.send_response(response.status_code)
                        self.send_header("Content-Type", response.headers.get("content-type", ""))
                        self.end_headers()
                        for chunk in response.iter_bytes():
                            self.wfile.write(chunk)
                            self.wfile.flush()
                return
            if control["mode"] == "wait":
                control["release"].wait(5)
            proposal = json.dumps(
                {
                    "summary": "Local fixture edits",
                    "files": [
                        {"path": "README.md", "content": "Local edit\n"},
                        {"path": "new.py", "content": "print('validation passed')\n"},
                    ],
                }
            )
            if control["mode"] == "explore" and "Select source files" in request["messages"][0]["content"]:
                step = len(control["requests"])
                proposal = json.dumps(
                    [
                        {"tool": "list_files", "prefix": "", "offset": 0},
                        {"tool": "read_file", "path": "README.md"},
                        {"tool": "finish", "files": ["README.md", "new.py"]},
                    ][step - 1]
                )
            if control.get("proposal"):
                proposal = json.dumps(control["proposal"])
            delta = {"content": proposal}
            if control["mode"] == "tool":
                delta["tool_calls"] = [{"function": {"name": "shell"}}]
            events = [
                {"choices": [{"delta": delta, "finish_reason": None}]},
                {
                    "choices": [
                        {"delta": {}, "finish_reason": "length" if control["mode"] == "truncated" else "stop"}
                    ]
                },
            ]
            payload = (
                b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except BrokenPipeError:
                pass

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    socket = str(tmp_path / "local-model.sock")
    server = Server(socket, Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AI_STATION_RUNNER_SOCKET", socket)
    clear_settings_cache()
    yield control
    control["release"].set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    clear_settings_cache()


def local_coding_request(project, **extra):
    return {
        key: value
        for key, value in coding_request(project, model="fixture-local", **extra).items()
        if key != "external_ai"
    }


def prepare_local_coding(client, project, **extra):
    response = client.post("/api/coding/local", json=local_coding_request(project, **extra))
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "local-prepare")
    prepared = client.get(f"/api/runs/{response.json()['id']}").json()
    assert prepared["status"] == "succeeded", prepared
    return prepared["metadata"]["coding_run_id"]


def test_local_coding_applies_validates_and_commits_only_owned_worktree(
    repository, owned_runner, local_coding_bridge, validation_sandbox
):
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(
            client,
            repository,
            test_commands=[["/usr/bin/python3", "new.py"]],
            pr_policy={"commit_task_branch": True},
        )
        run_id = prepare_local_coding(client, project)
        with session_factory()() as session:
            tick(session, "local-inference")
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "succeeded", run
        assert "external_ai" not in run["effective_permissions"]
        assert run["metadata"]["execution_location"] == "local"
        assert run["metadata"]["coding_review"]["provider"]["model"] == "fixture-local"
        assert {a["type"] for a in client.get(f"/api/artifacts?run_id={run_id}").json()} == {
            "json",
            "git_diff",
        }
        with session_factory()() as session:
            tick(session, "local-validation")
        assert client.get(f"/api/runs/{run['metadata']['validation_run_id']}").json()["status"] == "succeeded"
        response = client.post(
            f"/api/coding/runs/{run_id}/commit", json={"reviewed": True, "message": "Accept local edits"}
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "local-commit")
        committed = client.get(f"/api/runs/{response.json()['id']}").json()
        assert committed["status"] == "succeeded", committed
        assert len(local_coding_bridge["requests"]) == 1
        target, payload = local_coding_bridge["requests"][0]
        assert target == "/v1/llm/chat/completions" and payload["model"] == "fixture-local"
        assert "tools" not in payload and "Original repository" in payload["messages"][0]["content"]
    assert (repository / "README.md").read_text() == "Original repository\n"
    assert not (repository / "new.py").exists()
    assert (repository / ".git/index").read_bytes() == index


@pytest.mark.parametrize("mode", ["truncated", "tool"])
def test_local_coding_refuses_unfinished_or_tool_responses(
    repository, owned_runner, local_coding_bridge, mode
):
    local_coding_bridge["mode"] = mode
    with TestClient(app) as client:
        project = register(client, repository)
        run_id = prepare_local_coding(client, project)
        with session_factory()() as session:
            tick(session, "local-invalid")
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "failed", run
        assert "coding_review" not in run["metadata"]
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert (
            owned_runner.data_dir / worktree["relative_path"] / "README.md"
        ).read_text() == "Original repository\n"
        assert client.get(f"/api/artifacts?run_id={run_id}").json() == []


@pytest.mark.parametrize("explore", [False, True])
def test_local_coding_boundary_and_cancellation(
    repository, owned_runner, local_coding_bridge, monkeypatch, explore
):
    local_coding_bridge["mode"] = "wait"
    with TestClient(app) as client:
        project = register(client, repository)
        body = local_coding_request(project)
        for extra in ({"external_ai": True}, {"endpoint": "https://example.com/v1"}, {"shell": "true"}):
            assert client.post("/api/coding/local", json={**body, **extra}).status_code == 422
        assert (
            client.post(
                "/api/coding/local", json={**body, "expected_updated_at": "2000-01-01T00:00:00Z"}
            ).status_code
            == 409
        )
        run_id = prepare_local_coding(client, project, **({"explore": True, "files": []} if explore else {}))
        assert client.post("/api/coding/local", json=body).status_code == 409
        original = RunnerClient.start_local_proposal

        def cancel_after_inference_starts(self, payload):
            with TestClient(runner_app) as native:
                route = "/v1/runs/local-coding-proposal"
                assert native.post(route, json={**payload, "permissions": []}).status_code == 403
                assert (
                    native.post(route, json={**payload, "endpoint": "https://example.com"}).status_code == 409
                )
            result = original(self, payload)
            assert local_coding_bridge["entered"].wait(5)
            assert original(self, payload)["pid"] == result["pid"]
            client.post(f"/api/runs/{run_id}/cancel")
            return result

        monkeypatch.setattr(RunnerClient, "start_local_proposal", cancel_after_inference_starts)
        with session_factory()() as session:
            tick(session, "local-cancel")
        result = client.get(f"/api/runs/{run_id}").json()
        assert result["status"] == "canceled", result
        assert not owned_runner.inspect(run_id)["alive"]
        assert "coding_review" not in result["metadata"]


@pytest.mark.skipif(
    os.environ.get("AI_STATION_REAL_LOCAL_LLM_TESTS") != "1",
    reason="Real local inference is explicitly opt-in",
)
@pytest.mark.parametrize("explore", [False, True])
def test_real_local_coding_proposal(repository, owned_runner, local_coding_bridge, explore):
    local_coding_bridge["mode"] = "real"
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(client, repository)
        body = local_coding_request(project)
        body.update(
            files=[] if explore else ["README.md"],
            explore=explore,
            prompt=(
                "Locate the repository introduction file: first list the files, then read the relevant file, then select it. Replace its entire content with exactly Local coding smoke passed followed by a newline. /no_think"
                if explore
                else "Replace README.md with exactly the text Local coding smoke passed followed by a newline. Return the required JSON proposal only."
            ),
        )
        response = client.post("/api/coding/local", json=body)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "real-local-prepare")
        prepared = client.get(f"/api/runs/{response.json()['id']}").json()
        with session_factory()() as session:
            tick(session, "real-local-inference")
        run = client.get(f"/api/runs/{prepared['metadata']['coding_run_id']}").json()
        assert run["status"] == "succeeded", run
        worktree = client.get(f"/api/projects/{project['id']}/worktrees").json()[0]
        assert (
            owned_runner.data_dir / worktree["relative_path"] / "README.md"
        ).read_text().strip() == "Local coding smoke passed"
        assert run["metadata"]["coding_review"]["files"]
        if explore:
            assert len(run["metadata"]["coding_review"]["exploration"]) >= 2
            assert len(local_coding_bridge["requests"]) >= 3
        else:
            assert len(local_coding_bridge["requests"]) == 1
    assert (repository / "README.md").read_text() == "Original repository\n"
    assert (repository / ".git/index").read_bytes() == index


def test_local_coding_reloads_saved_llama_preset_before_inference(repository, owned_runner):
    from app.llama import LoadModel, enqueue_load
    from app.models import ModelFile, Run, RunDependency, RuntimeInstance

    with session_factory()() as session:
        model = ModelFile(
            host_path="/models/coder.gguf",
            filename="coder.gguf",
            format="gguf",
            category="llm",
            availability="present",
            size_bytes=1000,
            mtime=1,
        )
        session.add(model)
        session.flush()
        old_load = enqueue_load(LoadModel(model_file_id=model.id, gpus=[2, 7], context_size=4096), session)
        old_load.status = "succeeded"
        instance = session.get(RuntimeInstance, old_load.parameters["instance_id"])
        instance.status = "stopped"
        model_key = "llamacpp:" + model.id
        old_id = instance.id
        session.commit()
    with TestClient(app) as client:
        project = register(client, repository)
        body = {**local_coding_request(project), "model": model_key}
        response = client.post("/api/coding/local", json=body)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "prepare-with-model-reload")
        prepared = client.get(f"/api/runs/{response.json()['id']}").json()
        assert prepared["status"] == "succeeded", prepared
        with session_factory()() as session:
            coding = session.get(Run, prepared["metadata"]["coding_run_id"])
            dependency = session.scalar(select(RunDependency).where(RunDependency.run_id == coding.id))
            assert dependency is not None
            loads = list(
                session.scalars(select(Run).where(Run.executor_type == "llama_load", Run.status == "queued"))
            )
            assert len(loads) == 1
            load = loads[0]
            assert load.parameters["gpus"] == [2, 7]
            assert load.parameters["context_size"] == 4096
            assert load.parameters["instance_id"] != old_id
            assert coding.parameters["endpoint"] == "llamacpp:" + load.parameters["instance_id"]
            assert coding.parameters["model"] == model_key
            assert coding.status == "queued"


def test_local_exploration_selects_files_and_preserves_checkout(
    repository, owned_runner, local_coding_bridge
):
    local_coding_bridge["mode"] = "explore"
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(client, repository)
        body = local_coding_request(project, files=[], explore=True)
        response = client.post("/api/coding/local", json=body)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "exploration-prepare")
        prepared = client.get(f"/api/runs/{response.json()['id']}").json()
        with session_factory()() as session:
            tick(session, "exploration-execute")
        run = client.get(f"/api/runs/{prepared['metadata']['coding_run_id']}").json()
        assert run["status"] == "succeeded", run
        review = run["metadata"]["coding_review"]
        assert len(review["exploration"]) == 3
        assert review["exploration"][1]["result"]["content"] == "Original repository\n"
        assert {item["path"] for item in review["files"]} == {"README.md", "new.py"}
        assert len(local_coding_bridge["requests"]) == 4
        assert "coding.exploration.completed" in client.get(f"/api/runs/{run['id']}/stream").text
        assert client.post("/api/coding/local", json={**body, "explore": False}).status_code == 422
        assert client.post("/api/coding/local", json={**body, "files": ["README.md"]}).status_code == 422
    assert (repository / "README.md").read_text() == "Original repository\n"
    assert (repository / ".git/index").read_bytes() == index


@pytest.mark.parametrize("explore", [False, True])
@pytest.mark.parametrize("cancel_repair", [False, True])
def test_local_repair_preserves_scope_revalidates_and_commits_cumulative_diff(
    repository, owned_runner, local_coding_bridge, validation_sandbox, explore, cancel_repair, monkeypatch
):
    index = (repository / ".git/index").read_bytes()
    local_coding_bridge["mode"] = "explore" if explore else "success"
    with TestClient(app) as client:
        # Initial fixture prints a string; validation requires a numeric result.
        project = register(
            client,
            repository,
            test_commands=[
                [
                    "/usr/bin/python3",
                    "-c",
                    "import subprocess; assert subprocess.check_output(['/usr/bin/python3', 'new.py']).strip() == b'42'",
                ]
            ],
            pr_policy={"commit_task_branch": True},
        )
        run_id = prepare_local_coding(client, project, **({"explore": True, "files": []} if explore else {}))
        with session_factory()() as session:
            tick(session, "initial-code")
        route = f"/api/coding/runs/{run_id}/repair"
        assert client.post(route).status_code == 409  # Validation is still pending.
        with session_factory()() as session:
            tick(session, "initial-validation")
        source = client.get(f"/api/runs/{run_id}").json()
        validation_id = source["metadata"]["validation_run_id"]
        assert client.get(f"/api/runs/{validation_id}").json()["status"] == "failed"
        local_coding_bridge["proposal"] = {
            "summary": "Fix expected numeric output",
            "files": [{"path": "new.py", "content": "print(42)\n"}],
        }
        response = client.post(route)
        assert response.status_code == 202, response.text
        repair = response.json()
        assert repair["parent_run_id"] == validation_id and repair["task_id"] == source["task_id"]
        assert repair["parameters"]["commands"] == source["parameters"]["commands"]
        assert repair["parameters"]["files"] == ["README.md", "new.py"]
        assert repair["parameters"]["explore"] is False
        assert "external_ai" not in repair["effective_permissions"]
        assert client.post(route).status_code == 409
        assert (
            client.post(
                f"/api/coding/runs/{run_id}/commit", json={"reviewed": True, "message": "Stale"}
            ).status_code
            == 409
        )
        original_start = RunnerClient.start_local_proposal
        if cancel_repair:
            local_coding_bridge["mode"] = "wait"
            local_coding_bridge["entered"].clear()

        def checked_start(self, payload):
            with TestClient(runner_app) as native:
                native_route = "/v1/runs/local-coding-proposal"
                assert native.post(native_route, json={**payload, "files": ["other.py"]}).status_code == 409
                assert native.post(native_route, json={**payload, "model": "different"}).status_code == 409
                assert native.post(native_route, json={**payload, "permissions": []}).status_code == 403
            process = original_start(self, payload)
            assert original_start(self, payload)["pid"] == process["pid"]
            if cancel_repair:
                assert local_coding_bridge["entered"].wait(5)
                assert client.post(f"/api/runs/{repair['id']}/cancel").status_code == 200
            return process

        monkeypatch.setattr(RunnerClient, "start_local_proposal", checked_start)
        with session_factory()() as session:
            tick(session, "repair-code")
        repaired = client.get(f"/api/runs/{repair['id']}").json()
        if cancel_repair:
            assert repaired["status"] == "canceled", repaired
            assert not owned_runner.inspect(repair["id"])["alive"]
            assert "coding_review" not in repaired["metadata"]
            assert (repository / ".git/index").read_bytes() == index
            return
        assert repaired["status"] == "succeeded", repaired
        review = repaired["metadata"]["coding_review"]
        assert {f["path"] for f in review["files"]} == {"README.md", "new.py"}
        assert "Original repository" in next(f["diff"] for f in review["files"] if f["path"] == "README.md")
        assert "validation passed" not in next(f["diff"] for f in review["files"] if f["path"] == "new.py")
        assert "AssertionError" in local_coding_bridge["requests"][-1][1]["messages"][0]["content"]
        with session_factory()() as session:
            tick(session, "repair-validation")
        assert (
            client.get(f"/api/runs/{repaired['metadata']['validation_run_id']}").json()["status"]
            == "succeeded"
        )
        assert client.post(f"/api/coding/runs/{repair['id']}/repair").status_code == 409
        commit = client.post(
            f"/api/coding/runs/{repair['id']}/commit",
            json={"reviewed": True, "message": "Accept repaired changes"},
        )
        assert commit.status_code == 202, commit.text
        with session_factory()() as session:
            tick(session, "repair-commit")
        result = client.get(f"/api/runs/{commit.json()['id']}").json()
        assert result["status"] == "succeeded", result
    assert (repository / "README.md").read_text() == "Original repository\n"
    assert not (repository / "new.py").exists()
    assert (repository / ".git/index").read_bytes() == index


@pytest.mark.parametrize("budget,succeed", [(0, False), (1, False), (2, False), (2, True)])
def test_local_automatic_repair_is_opt_in_bounded_and_stops_on_success(
    repository, owned_runner, local_coding_bridge, validation_sandbox, budget, succeed
):
    from app.models import Run

    with TestClient(app) as client:
        project = register(
            client,
            repository,
            test_commands=[
                [
                    "/usr/bin/python3",
                    "-c",
                    "import subprocess; assert subprocess.check_output(['/usr/bin/python3', 'new.py']).strip() == b'42'",
                ]
            ],
        )
        source_id = prepare_local_coding(client, project, max_repair_attempts=budget)
        with session_factory()() as session:
            tick(session, "first-proposal")
        if succeed:
            local_coding_bridge["proposal"] = {
                "summary": "Repair result",
                "files": [{"path": "new.py", "content": "print(42)\n"}],
            }
        for _ in range(7):
            with session_factory()() as session:
                tick(session, "bounded-repair")
        with session_factory()() as session:
            runs = list(
                session.scalars(select(Run).where(Run.project_id == project["id"]).order_by(Run.created_at))
            )
            proposals = [r for r in runs if r.executor_type == "local_proposal"]
            validations = [r for r in runs if r.executor_type == "project_validation"]
            assert len(proposals) == 1 + (1 if succeed else budget)
            assert len(validations) == len(proposals)
            assert all(r.status == "succeeded" for r in proposals)
            assert all(r.parameters["max_repair_attempts"] == budget for r in proposals)
            assert proposals[-1].parameters.get("repair_attempt", 0) == (1 if succeed else budget)
            assert validations[-1].status == ("succeeded" if succeed else "failed")
            from types import SimpleNamespace

            from app.assistant import task_results

            projected = task_results(
                session, SimpleNamespace(metadata_json={"orchestration": True}), proposals[0]
            )
            assert projected["task_status"] == ("succeeded" if succeed else "failed")
            assert any(step["status"] == "failed" for step in projected["steps"])
            assert bool(validations[-1].metadata_json.get("repair_budget_exhausted")) is (
                bool(budget) and not succeed
            )
            if budget:
                first = session.get(Run, source_id)
                assert first.metadata_json["review_status"] == "superseded"
                assert validations[0].metadata_json["repair_run_id"] == first.metadata_json["repair_run_id"]
            assert all(r.parameters["commands"] == proposals[0].parameters["commands"] for r in proposals)
    assert (repository / "README.md").read_text() == "Original repository\n"


@pytest.mark.parametrize("stop", ["cancel", "unavailable"])
def test_automatic_repair_preserves_failed_validation_or_cancellation_without_extra_runs(
    repository, owned_runner, local_coding_bridge, validation_sandbox, monkeypatch, stop
):
    from app.models import Run
    from app.providers import ProviderError

    with TestClient(app) as client:
        project = register(
            client, repository, test_commands=[["/usr/bin/python3", "-c", "raise AssertionError('expected')"]]
        )
        source_id = prepare_local_coding(client, project, max_repair_attempts=2)
        with session_factory()() as session:
            tick(session, "initial-proposal")
        source = client.get(f"/api/runs/{source_id}").json()
        validation_id = source["metadata"]["validation_run_id"]
        if stop == "cancel":
            client.post(f"/api/runs/{validation_id}/cancel")
        else:

            def unavailable(*args):
                raise ProviderError("Runtime requires inspection")

            monkeypatch.setattr("app.llama.prepare_consumer", unavailable)
        with session_factory()() as session:
            tick(session, "validation")
            assert (
                session.scalar(select(func.count()).select_from(Run).where(Run.project_id == project["id"]))
                == 3
            )
            source = session.get(Run, source_id)
            validation = session.get(Run, validation_id)
            assert "repair_run_id" not in source.metadata_json
            assert validation.status == ("canceled" if stop == "cancel" else "failed")
            if stop == "unavailable":
                assert validation.metadata_json["validation"]["commands"][0]["exit_code"] != 0
        if stop == "unavailable":
            events = client.get(f"/api/runs/{validation_id}/events").json()
            assert any(e["event_type"] == "coding.repair.unavailable" for e in events)


@pytest.mark.parametrize("budget", [-1, 3, True, "1"])
def test_local_repair_budget_rejects_unbounded_or_coerced_values(budget):
    with TestClient(app) as client:
        response = client.post(
            "/api/coding/local",
            json={
                "project_id": "00000000-0000-0000-0000-000000000001",
                "expected_updated_at": "2026-10-07T12:00:00Z",
                "prompt": "Change source",
                "files": ["source.py"],
                "model": "local",
                "max_repair_attempts": budget,
            },
        )
        assert response.status_code == 422


@pytest.fixture
def fake_github(repository, validation_sandbox, tmp_path, monkeypatch):
    """Network-free Git/GitHub boundary; other Git commands use real disposable objects."""
    import json
    import shutil

    git = shutil.which("git")
    parent = subprocess.check_output([git, "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(
        [git, "-C", str(repository), "remote", "add", "origin", "https://github.com/fixture/example.git"],
        check=True,
    )
    binaries = tmp_path / "github-bin"
    binaries.mkdir()
    control = tmp_path / "github-control.json"
    control.write_text(json.dumps({"parent": parent, "mode": "success"}))
    calls = tmp_path / "github-calls.jsonl"
    script = (
        """#!/usr/bin/python3
import sys,os,json,pathlib,subprocess,time
control=pathlib.Path(CONTROL); calls=pathlib.Path(CALLS); real_git=REAL_GIT
args=sys.argv[1:]; state=json.loads(control.read_text()); name=pathlib.Path(sys.argv[0]).name
if name=='git' and not any(op in args for op in ['push','ls-remote']):
 os.execv(real_git,[real_git,*args])
with calls.open('a') as f:f.write(json.dumps({'tool':name,'args':args})+'\\n')
assert os.environ['GIT_CONFIG_GLOBAL']=='/dev/null'
assert os.environ['GIT_CONFIG_NOSYSTEM']=='1'
assert os.environ['GH_HOST']=='github.com'
assert pathlib.Path(os.environ['GIT_DIR']).name=='export.git'
assert not any(a.startswith('--force') for a in args)
if name=='git':
 op='push' if 'push' in args else 'ls-remote'; index=args.index(op)
 # Real Git must see no source/global URL rewrites or injected helpers.
 result=subprocess.run([real_git,*args[:index],'config','--get-regexp','^url\\\\.'],capture_output=True)
 assert result.returncode==1,result.stdout
 assert 'https://github.com/fixture/example.git' in args
 if op=='ls-remote':
  ref=args[-1]
  if ref=='refs/heads/develop':
   print(('0'*40 if state['mode']=='bad_base' else state['parent'])+'\\t'+ref);sys.exit(0)
  sys.exit(2)
 state['push_started']=True;control.write_text(json.dumps(state))
 if state['mode']=='wait':
  while True:time.sleep(1)
 if state['mode']=='push_error':
  print('DISPOSABLE_SECRET_DO_NOT_LOG',file=sys.stderr);sys.exit(7)
 sha,ref=args[-1].split(':',1)
 assert ref.startswith('refs/heads/ai/')
 assert subprocess.check_output([real_git,'cat-file','-t',sha],text=True).strip()=='commit'
 state['pushed']=sha;control.write_text(json.dumps(state));sys.exit(0)
assert args[:2]==['pr','create']
assert '--draft' in args and '--no-maintainer-edit' in args
assert args[args.index('--repo')+1]=='fixture/example'
assert args[args.index('--base')+1]=='develop'
assert args[args.index('--head')+1].startswith('ai/')
assert pathlib.Path(args[args.index('--body-file')+1]).read_text()=='Verified project checks.'
if state['mode']=='pr_error':sys.exit(9)
print('https://github.com/fixture/example/pull/17')
""".replace("CONTROL", repr(str(control)))
        .replace("CALLS", repr(str(calls)))
        .replace("REAL_GIT", repr(git))
    )
    for name in ("git", "gh"):
        executable = binaries / name
        executable.write_text(script)
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")
    yield control, calls


def prepared_publication(client, repository):
    project = register(
        client,
        repository,
        test_commands=[["/usr/bin/python3", "new.py"]],
        pr_policy={"commit_task_branch": True, "push_task_branch": True, "pr_to_integration": True},
    )
    source_id = prepare_local_coding(client, project)
    with session_factory()() as session:
        tick(session, "publication-proposal")
        tick(session, "publication-validation")
    response = client.post(
        f"/api/coding/runs/{source_id}/commit", json={"reviewed": True, "message": "Reviewed feature"}
    )
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "publication-commit")
    committed = client.get(f"/api/runs/{response.json()['id']}").json()
    assert committed["status"] == "succeeded", committed
    return project, committed


@pytest.mark.parametrize("mode", ["success", "pr_error", "push_error", "bad_base", "revoked", "cancel"])
def test_reviewed_publication_preserves_checkout_approval_and_partial_progress(
    repository, owned_runner, local_coding_bridge, fake_github, mode, monkeypatch
):
    import json

    from app.models import Approval, Run

    control, calls = fake_github
    state = json.loads(control.read_text())
    state["mode"] = "wait" if mode == "cancel" else mode
    control.write_text(json.dumps(state))
    before = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, committed = prepared_publication(client, repository)
        # Neither source hooks nor URL rewrites may affect the network operation.
        marker = repository / "unwanted-hook"
        hooks = repository / ".git/unsafe-hooks"
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o700)
        subprocess.run(["git", "-C", str(repository), "config", "core.hooksPath", str(hooks)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "config",
                "url.https://invalid.invalid/.insteadOf",
                "https://github.com/",
            ],
            check=True,
        )
        route = f"/api/coding/runs/{committed['id']}/publication"
        preview = client.get(route)
        assert preview.status_code == 200, preview.text
        info = preview.json()
        assert info["repository"] == "fixture/example" and info["base"] == "develop"
        body = {key: info[key] for key in ("repository", "commit", "base", "expected_updated_at")}
        body.update(approved=True, title="Reviewed improvement", body="Verified project checks.")
        assert client.post(route, json={**body, "approved": False}).status_code == 422
        assert client.post(route, json={**body, "force": True}).status_code == 422
        with session_factory()() as session:
            row = session.get(Project, project["id"])
            row.pr_policy = {**row.pr_policy, "push_task_branch": False}
            session.commit()
        assert client.post(route, json=body).status_code == 403
        assert client.get(route).json()["blocked_reason"]
        with session_factory()() as session:
            row = session.get(Project, project["id"])
            row.pr_policy = {**row.pr_policy, "push_task_branch": True}
            session.commit()
        assert client.post(route, json={**body, "base": "main"}).status_code == 409
        assert client.post(route, json={**body, "commit": "0" * 40}).status_code == 409
        response = client.post(route, json=body)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert client.post(route, json=body).status_code == 409
        with session_factory()() as session:
            run = session.get(Run, run_id)
            approval = session.get(Approval, run.parameters["approval_id"])
            assert approval.resolution == "granted" and approval.payload["commit"] == info["commit"]
            if mode == "revoked":
                approval.resolution = "denied"
                session.commit()
            if mode == "cancel":
                from app.runner_client import RunnerError

                original = RunnerClient.request

                def cancel_on_push(self, method, path, payload=None):
                    if method != "POST" or path != "/v1/runs/github-publication":
                        return original(self, method, path, payload)
                    with pytest.raises(RunnerError) as denied:
                        original(self, method, path, {**payload, "permissions": []})
                    assert denied.value.status_code == 403
                    process = original(self, method, path, payload)
                    assert original(self, method, path, payload)["pid"] == process["pid"]
                    with pytest.raises(RunnerError):
                        original(self, method, path, {**payload, "title": "Changed request"})
                    deadline = time.monotonic() + 10
                    while not json.loads(control.read_text()).get("push_started"):
                        assert time.monotonic() < deadline
                        time.sleep(0.05)
                    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
                    return process

                monkeypatch.setattr(RunnerClient, "request", cancel_on_push)
            tick(session, "publication")
        result = client.get(f"/api/runs/{run_id}").json()
        expected = "canceled" if mode == "cancel" else "succeeded" if mode == "success" else "failed"
        assert result["status"] == expected, result
        assert "DISPOSABLE_SECRET" not in str(result)
        assert not marker.exists()
        if mode == "success":
            assert result["metadata"]["publication"]["pr_url"] == "https://github.com/fixture/example/pull/17"
            artifacts = client.get(f"/api/artifacts?run_id={run_id}").json()
            assert artifacts[0]["original_filename"] == "github-publication.json"
            from datetime import timedelta

            from app.db import utcnow

            # Simulate loss of the worker's final transaction after the remote
            # action completed. Recovery must never dispatch another publication.
            external_calls = calls.read_text()
            with session_factory()() as session:
                row = session.get(Run, run_id)
                row.status = "running"
                row.finished_at = None
                row.lease_expires_at = utcnow() - timedelta(seconds=60)
                session.commit()
                assert run_id in recover_stale(session, RunnerClient())
                session.commit()
                assert session.get(Run, run_id).status == "interrupted"
                tick(session, "recovery-check")
            assert calls.read_text() == external_calls
        elif mode == "pr_error":
            assert result["metadata"]["publication_progress"]["stage"] == "pr_requested"
            assert json.loads(control.read_text())["pushed"] == info["commit"]
        elif mode == "push_error":
            assert result["metadata"]["publication_progress"]["stage"] == "push_started"
        elif mode == "cancel":
            assert not owned_runner.inspect(run_id)["alive"]
            assert result["metadata"]["publication_progress"]["stage"] == "push_started"
            assert not json.loads(control.read_text()).get("pushed")
        elif mode == "revoked":
            assert not calls.exists()
        elif mode == "bad_base":
            assert '"push"' not in calls.read_text()
    assert (repository / ".git/index").read_bytes() == before
    assert (repository / "README.md").read_text() == "Original repository\n"


@pytest.mark.skipif(
    os.environ.get("AI_STATION_REAL_GITHUB_TESTS") != "1", reason="Explicit real GitHub opt-in required"
)
def test_real_github_publication(repository, owned_runner, local_coding_bridge):
    """One disposable draft PR in the explicitly selected repository; no real inference."""
    import json
    from pathlib import Path

    source = Path(os.environ["AI_STATION_GITHUB_SMOKE_SOURCE"]).resolve()
    target = os.environ["AI_STATION_GITHUB_SMOKE_REPOSITORY"]
    origin = subprocess.check_output(
        ["git", "-C", str(source), "remote", "get-url", "origin"], text=True
    ).strip()
    from ai_station_runner.publication import github_repository

    assert github_repository(origin) == target
    evidence = Path(os.environ["AI_STATION_GITHUB_SMOKE_EVIDENCE"])
    evidence.parent.mkdir(parents=True, exist_ok=True)
    for args in (
        ["fetch", str(source), "develop"],
        ["reset", "--hard", "FETCH_HEAD"],
        ["remote", "add", "origin", origin],
    ):
        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
    before = (repository / ".git/index").read_bytes()
    path = "docs/publication-smoke.md"
    assert not (repository / path).exists()
    local_coding_bridge["proposal"] = {
        "summary": "Disposable publication acceptance fixture",
        "files": [
            {"path": path, "content": "# Publication acceptance\n\nDisposable draft PR; do not merge.\n"}
        ],
    }
    with TestClient(app) as client:
        project = register(
            client,
            repository,
            pr_policy={"commit_task_branch": True, "push_task_branch": True, "pr_to_integration": True},
        )
        source_id = prepare_local_coding(client, project, files=[path])
        with session_factory()() as session:
            tick(session, "real-publication-fixture")
        commit = client.post(
            f"/api/coding/runs/{source_id}/commit",
            json={"reviewed": True, "message": "test: disposable GitHub publication acceptance"},
        )
        assert commit.status_code == 202, commit.text
        with session_factory()() as session:
            tick(session, "real-publication-commit")
        route = f"/api/coding/runs/{commit.json()['id']}/publication"
        response = client.get(route)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["repository"] == target and preview["base"] == "develop"
        assert preview["branch"].startswith("ai/")
        payload = {key: preview[key] for key in ("repository", "commit", "base", "expected_updated_at")}
        payload.update(
            approved=True,
            title="test: disposable AI Station publication acceptance",
            body="Real owned Git/Host Runner publication with fake local inference. Disposable draft; do not merge.",
        )
        publication = client.post(route, json=payload)
        assert publication.status_code == 202, publication.text
        with session_factory()() as session:
            tick(session, "real-github-publication")
        result = client.get(f"/api/runs/{publication.json()['id']}").json()
        evidence.write_text(json.dumps({"preview": preview, "result": result}, indent=2))
        evidence.chmod(0o600)
        assert (repository / ".git/index").read_bytes() == before
        assert result["status"] == "succeeded", result
        url = result["metadata"]["publication"]["pr_url"]
        remote = json.loads(
            subprocess.check_output(
                [
                    "gh",
                    "pr",
                    "view",
                    url,
                    "--json",
                    "number,isDraft,baseRefName,headRefName,headRefOid,files",
                ],
                text=True,
            )
        )
        assert remote["isDraft"] and remote["baseRefName"] == "develop"
        assert remote["headRefName"] == preview["branch"] and remote["headRefOid"] == preview["commit"]
        assert [f["path"] for f in remote["files"]] == [path]
        subprocess.run(["gh", "pr", "close", url], check=True)
        ref = f"repos/{target}/git/refs/heads/{preview['branch']}"
        remote_ref = json.loads(subprocess.check_output(["gh", "api", ref], text=True))
        assert remote_ref["object"]["sha"] == preview["commit"]
        subprocess.run(["gh", "api", "--method", "DELETE", ref], check=True)
        evidence.write_text(
            json.dumps({"preview": preview, "result": result, "remote": remote, "cleaned_up": True}, indent=2)
        )


@pytest.fixture
def fake_codex(validation_sandbox, tmp_path, monkeypatch):
    binary = tmp_path / "codex"
    binary.write_text("""#!/usr/bin/python3
import json,os,pathlib,sys,time
args=sys.argv[1:]
if '--help' in args:
 print('--ignore-user-config --ignore-rules --strict-config --ephemeral');sys.exit(0)
assert '--ignore-user-config' in args and '--ignore-rules' in args
assert '--strict-config' in args and '--ephemeral' in args
assert 'approval_policy="never"' in args
assert 'permissions.ai_station_proposal.network.enabled=false' in args
assert 'features.skip_host_skill_discovery=true' in args
assert 'web_search="disabled"' in args
assert not list(pathlib.Path.cwd().iterdir())
assert pathlib.Path.cwd()==pathlib.Path(args[args.index('-C')+1])
assert 'AI_STATION_TEST_SECRET' not in os.environ
mode=args[args.index('--model')+1] if '--model' in args else 'success'
if mode=='wait':
 pathlib.Path(__file__).with_suffix('.started').write_text('started')
 while True:time.sleep(1)
if mode=='failure':
 print('DISPOSABLE_SECRET_DO_NOT_LOG',file=sys.stderr);sys.exit(2)
print(json.dumps({'type':'thread.started','thread_id':'fixture-thread'}))
if mode=='tool':print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'forbidden'}}))
proposal={'summary':'Codex fixture changes','files':[{'path':'README.md','content':'Codex fixture\\n'},{'path':'new.py','content':'print(42)\\n'}]}
if 'SECOND_TURN' in args[-1]:
 proposal={'summary':'Second turn','files':[{'path':'more.py','content':'print(43)\\n'}]}
if args[-1].startswith('Select source files'):
 proposal={'tool':'finish','files':['more.py'] if 'SECOND_TURN' in args[-1] else ['README.md','new.py']}
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(proposal)}}))
print(json.dumps({'type':'turn.completed','usage':{'output_tokens':15}}))
""")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("AI_STATION_TEST_SECRET", "private-test-fixture")
    return binary


@pytest.mark.parametrize("mode", ["success", "tool", "failure", "wait"])
def test_codex_owned_proposal_validation_commit_and_cancellation(
    repository, owned_runner, fake_codex, mode, monkeypatch
):
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(
            client,
            repository,
            test_commands=[["/usr/bin/python3", "new.py"]],
            pr_policy={"commit_task_branch": True},
        )
        body = coding_request(project, model=mode)
        assert client.post("/api/coding/codex", json={**body, "external_ai": False}).status_code == 422
        request = client.post("/api/coding/codex", json=body)
        assert request.status_code == 202, request.text
        with session_factory()() as session:
            tick(session, "codex-worktree")
        prepared = client.get(f"/api/runs/{request.json()['id']}").json()
        source_id = prepared["metadata"]["coding_run_id"]
        if mode == "wait":
            original = RunnerClient.request

            def cancel_on_start(self, method, path, payload=None):
                result = original(self, method, path, payload)
                if method == "POST" and path == "/v1/runs/codex-proposal":
                    deadline = time.monotonic() + 10
                    while not fake_codex.with_suffix(".started").exists():
                        assert time.monotonic() < deadline
                        time.sleep(0.05)
                    assert original(self, method, path, payload)["pid"] == result["pid"]
                    assert client.post(f"/api/runs/{source_id}/cancel").status_code == 200
                return result

            monkeypatch.setattr(RunnerClient, "request", cancel_on_start)
        with session_factory()() as session:
            tick(session, "codex-proposal")
        result = client.get(f"/api/runs/{source_id}").json()
        assert result["executor_type"] == "codex_proposal"
        assert result["status"] == (
            "succeeded" if mode == "success" else "canceled" if mode == "wait" else "failed"
        ), result
        if mode == "success":
            assert result["metadata"]["coding_review"]["provider"]["thread_id"] == "fixture-thread"
            with session_factory()() as session:
                tick(session, "codex-validation")
            validation = client.get(f"/api/runs/{result['metadata']['validation_run_id']}").json()
            assert validation["status"] == "succeeded", validation
            committed = client.post(
                f"/api/coding/runs/{source_id}/commit",
                json={"reviewed": True, "message": "Reviewed Codex fixture"},
            )
            assert committed.status_code == 202, committed.text
            with session_factory()() as session:
                tick(session, "codex-commit")
            final = client.get(f"/api/runs/{committed.json()['id']}").json()
            assert final["status"] == "succeeded", final
        else:
            assert (
                owned_runner.data_dir / prepared["metadata"]["relative_path"] / "README.md"
            ).read_text() == "Original repository\n"
            assert not client.get(f"/api/artifacts?run_id={source_id}").json()
        assert not owned_runner.inspect(source_id)["alive"]
        assert (repository / ".git/index").read_bytes() == index
        assert (repository / "README.md").read_text() == "Original repository\n"


@pytest.mark.skipif(
    os.environ.get("AI_STATION_REAL_CODEX_TESTS") != "1", reason="Explicit real Codex opt-in required"
)
def test_real_codex_selected_file_proposal(repository, owned_runner, validation_sandbox):
    """Only synthetic disposable files reach the installed authenticated CLI."""
    import json
    from pathlib import Path

    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project = register(
            client,
            repository,
            test_commands=[["/usr/bin/python3", "new.py"]],
            pr_policy={"commit_task_branch": True},
        )
        request = client.post(
            "/api/coding/codex",
            json=coding_request(
                project,
                model=os.environ.get("AI_STATION_SMOKE_CODEX_MODEL", ""),
                prompt="Return a JSON coding proposal. Replace README.md with exactly 'Codex acceptance passed\\n' and create new.py containing exactly 'print(42)\\n'. Do not use tools. These are synthetic acceptance fixtures.",
            ),
        )
        assert request.status_code == 202, request.text
        with session_factory()() as session:
            tick(session, "real-codex-worktree")
        prepared = client.get(f"/api/runs/{request.json()['id']}").json()
        source_id = prepared["metadata"]["coding_run_id"]
        with session_factory()() as session:
            tick(session, "real-codex-proposal")
        proposal = client.get(f"/api/runs/{source_id}").json()
        evidence = Path(os.environ["AI_STATION_CODEX_SMOKE_EVIDENCE"])
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"proposal": proposal}, indent=2))
        evidence.chmod(0o600)
        assert proposal["status"] == "succeeded", proposal
        with session_factory()() as session:
            tick(session, "real-codex-validation")
        validation = client.get(f"/api/runs/{proposal['metadata']['validation_run_id']}").json()
        assert validation["status"] == "succeeded", validation
        assert proposal["metadata"]["coding_review"]["provider"]["thread_id"]
        committed = client.post(
            f"/api/coding/runs/{source_id}/commit",
            json={"reviewed": True, "message": "Accept synthetic Codex fixture"},
        )
        assert committed.status_code == 202, committed.text
        with session_factory()() as session:
            tick(session, "real-codex-commit")
        commit = client.get(f"/api/runs/{committed.json()['id']}").json()
        assert commit["status"] == "succeeded", commit
        assert (repository / "README.md").read_text() == "Original repository\n"
        assert (repository / ".git/index").read_bytes() == index
        evidence.write_text(
            json.dumps(
                {
                    "proposal": proposal,
                    "validation": validation,
                    "commit": commit,
                    "original_unchanged": True,
                },
                indent=2,
            )
        )


def test_name_only_project_setup_and_isolated_environment(repository, owned_runner):
    from pathlib import Path

    with TestClient(app) as client:
        assert client.post("/api/projects/create", json={"name": "   "}).status_code == 422
        assert (
            client.post(
                "/api/projects/create", json={"name": "New", "repo_path": str(repository)}
            ).status_code
            == 422
        )
        response = client.post("/api/projects/create", json={"name": "My new idea"})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert not client.get("/api/projects").json()
        with session_factory()() as session:
            tick(session, "project-setup")
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "succeeded", run
        project = client.get(f"/api/projects/{run['project_id']}").json()
        repo = Path(project["repo_path"])
        assert repo == owned_runner.data_dir / "projects" / project["id"]
        assert (repo / ".venv/bin/python").exists()
        assert (
            subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip()
            == "develop"
        )
        assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True) == ""
        prepare = enqueue_worktree(client, project)
        with session_factory()() as session:
            tick(session, "managed-worktree")
        prepared = client.get(f"/api/runs/{prepare['id']}").json()
        assert prepared["status"] == "succeeded", prepared
        assert (owned_runner.data_dir / prepared["metadata"]["relative_path"] / ".venv/bin/python").exists()
        assert (repository / "README.md").read_text() == "Original repository\n"


@pytest.mark.parametrize("provider", ["codex", "cursor"])
def test_coding_conversation_continues_same_worktree_and_supersedes_review(
    repository, owned_runner, provider, request
):
    request.getfixturevalue("fake_" + provider)
    with TestClient(app) as client:
        project = register(client, repository)
        response = client.post(
            f"/api/coding/{provider}", json=coding_request(project, files=[], explore=True)
        )
        assert response.status_code == 202, response.text
        preparation = response.json()
        for worker in ("prepare", "first-turn"):
            with session_factory()() as session:
                tick(session, worker)
        path = f"/api/coding/sessions/{preparation['task_id']}"
        detail = client.get(path).json()
        source = next(r for r in detail["runs"] if r["executor_type"] == f"{provider}_proposal")
        assert source["status"] == "succeeded", source
        assert source["metadata"]["coding_review"]["exploration"]
        assert client.get("/api/coding/sessions").json()[0]["id"] == preparation["task_id"]
        assert client.get("/api/coding/sessions?offset=1").json() == []
        body = {"prompt": "SECOND_TURN add another file", "expected_run_id": source["id"]}
        assert client.post(path + "/messages", json=body).status_code == 422
        response = client.post(path + "/messages", json={**body, "external_ai": True})
        assert response.status_code == 202, response.text
        second = response.json()
        assert second["parameters"]["worktree_run_id"] == source["parameters"]["worktree_run_id"]
        assert client.post(path + "/messages", json={**body, "external_ai": True}).status_code == 409
        assert (
            client.post(
                f"/api/coding/runs/{source['id']}/commit", json={"reviewed": True, "message": "Old review"}
            ).status_code
            == 409
        )
        with session_factory()() as session:
            tick(session, "followup")
        final = client.get(f"/api/runs/{second['id']}").json()
        assert final["status"] == "succeeded", final
        assert {f["path"] for f in final["metadata"]["coding_review"]["files"]} == {
            "README.md",
            "new.py",
            "more.py",
        }
        reset_engine()
        assert (
            len([r for r in client.get(path).json()["runs"] if r["executor_type"] == f"{provider}_proposal"])
            == 2
        )
        assert (repository / "README.md").read_text() == "Original repository\n"
        accepted = client.post(
            f"/api/coding/runs/{second['id']}/commit", json={"reviewed": True, "message": "Both turns"}
        )
        assert accepted.status_code == 202, accepted.text
        with session_factory()() as session:
            tick(session, "commit-both-turns")
        assert client.get(f"/api/runs/{accepted.json()['id']}").json()["status"] == "succeeded"


def test_project_setup_cancellation_and_no_destination_overwrite(repository, owned_runner, monkeypatch):
    import sys

    original_start = owned_runner.start

    def slow(**kwargs):
        kwargs["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        return original_start(**kwargs)

    monkeypatch.setattr(owned_runner, "start", slow)
    original = RunnerClient.request
    with TestClient(app) as client:
        run = client.post("/api/projects/create", json={"name": "Canceled idea"}).json()

        def cancel(self, method, path, payload=None):
            result = original(self, method, path, payload)
            if method == "POST" and path == "/v1/projects/create":
                assert original(self, method, path, payload)["pid"] == result["pid"]
                assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
            return result

        monkeypatch.setattr(RunnerClient, "request", cancel)
        with session_factory()() as session:
            tick(session, "cancel-project")
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
        assert not owned_runner.inspect(run["id"])["alive"]
        assert not client.get("/api/projects").json()
    monkeypatch.setattr(RunnerClient, "request", original)
    from uuid import uuid4

    from ai_station_runner.project_setup import ProjectSetup, start_setup

    project_id = str(uuid4())
    dest = owned_runner.data_dir / "projects" / project_id
    dest.mkdir(parents=True)
    (dest / "keep.txt").write_text("user data")
    body = ProjectSetup(
        run_id=uuid4(), project_id=project_id, name="Existing", permissions=["workspace_write", "git_write"]
    )
    from ai_station_runner.gitops import GitError

    with pytest.raises(GitError, match="destination already exists"):
        start_setup(owned_runner, body)
    assert (dest / "keep.txt").read_text() == "user data"
    with pytest.raises(PermissionError):
        start_setup(owned_runner, body.model_copy(update={"permissions": []}))


@pytest.mark.skipif(
    os.environ.get("AI_STATION_REAL_CODEX_TESTS") != "1", reason="Explicit real Codex opt-in required"
)
def test_real_codex_workspace_followup(repository, owned_runner):
    """Two turns with automatic source discovery; synthetic temporary files only."""
    import json
    from pathlib import Path

    with TestClient(app) as client:
        project = register(client, repository)
        response = client.post(
            "/api/coding/codex",
            json=coding_request(
                project,
                files=[],
                explore=True,
                prompt="Synthetic acceptance: create hello.py containing exactly print('Hello Station') and keep README.md unchanged. Explore only these two paths. Return the requested JSON operation/proposal.",
            ),
        )
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        for worker in ("real-prepare", "real-first"):
            with session_factory()() as session:
                tick(session, worker)
        detail = client.get(f"/api/coding/sessions/{task_id}").json()
        first = next(r for r in detail["runs"] if r["executor_type"] == "codex_proposal")
        assert first["status"] == "succeeded", first
        response = client.post(
            f"/api/coding/sessions/{task_id}/messages",
            json={
                "expected_run_id": first["id"],
                "external_ai": True,
                "prompt": "Now create second.py containing exactly print('Second turn'), preserve hello.py and README.md. This is a synthetic continuation test.",
            },
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "real-second")
        second = client.get(f"/api/runs/{response.json()['id']}").json()
        assert second["status"] == "succeeded", second
        names = {x["path"] for x in second["metadata"]["coding_review"]["files"]}
        assert {"hello.py", "second.py"} <= names
        assert first["parameters"]["worktree_run_id"] == second["parameters"]["worktree_run_id"]
        assert (repository / "README.md").read_text() == "Original repository\n"
        path = Path(os.environ["AI_STATION_CODING_WORKSPACE_EVIDENCE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"first": first, "second": second, "original_unchanged": True}, indent=2))
        path.chmod(0o600)
