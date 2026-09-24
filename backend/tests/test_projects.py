import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from ai_station_runner.app import app as runner_app
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import reset_engine, session_factory
from app.models import Project
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
