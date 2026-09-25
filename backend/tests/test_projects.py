import importlib
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
