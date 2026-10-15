# Imported pytest fixtures share their parameter names.
# ruff: noqa: F811
import json

import pytest
from app.api import app
from app.coding_tasks import queue_validation
from app.db import session_factory
from app.engine import tick
from app.models import Project, Run
from app.project_checks import project_check_policy
from app.runs import create_run, request_cancel
from fastapi.testclient import TestClient
from test_node_project_runs import fake_node  # noqa: F401
from test_projects import owned_runner, prepared_validation, repository, validation_sandbox  # noqa: F401


def source_proposal(client, repository, owned_runner, *, automatic=True, environment=None):
    project, tree = prepared_validation(client, repository, [])
    workspace = owned_runner.data_dir / tree["relative_path"]
    (workspace / "package.json").write_text(
        json.dumps({"name": "test-auto-project", "version": "1.0.0", "scripts": {"build": "node build.js"}})
    )
    with session_factory()() as session:
        row = session.get(Project, project["id"])
        row.auto_install_dependencies = row.auto_validate = automatic
        row.validation_environment = environment
        prep = session.get(Run, tree["run_id"])
        source = create_run(
            session,
            prep.task,
            run_type="coding",
            capability="coding.local",
            executor_type="local_proposal",
            project_id=row.id,
            parent_run_id=prep.id,
            execution_target="host",
            parameters={
                "commands": [],
                "worktree_id": tree["id"],
                "worktree_run_id": prep.id,
                "project_check_policy": project_check_policy(row),
            },
        )
        source.status = "succeeded"
        session.flush()
        queue_validation(session, source)
        session.commit()
        return source.id, workspace


def test_ordinary_task_runs_plan_install_and_validate_in_order(
    repository, owned_runner, validation_sandbox, fake_node
):
    with TestClient(app) as client:
        source_id, workspace = source_proposal(client, repository, owned_runner)
        with session_factory()() as session:
            plan_id = tick(session, "automatic-plan")
            source = session.get(Run, source_id)
            assert source.metadata_json["project_plan_run_id"] == plan_id
            validation_id = source.metadata_json["validation_run_id"]
            deps = source.metadata_json["dependency_run_ids"]
            assert len(deps) == 1
            assert tick(session, "automatic-install") == deps[0]
            assert session.get(Run, deps[0]).status == "succeeded"
            assert tick(session, "automatic-build") == validation_id
            assert session.get(Run, validation_id).status == "succeeded"
            assert {
                session.get(Run, rid).task_id for rid in [source_id, plan_id, deps[0], validation_id]
            } == {source.task_id}
        assert (workspace / "install-proof.json").is_file()
        assert (workspace / "build-proof.txt").is_file()
        assert not (repository / "package.json").exists()


def test_changed_manifest_blocks_install_and_downstream_validation(
    repository, owned_runner, validation_sandbox, fake_node
):
    with TestClient(app) as client:
        source_id, workspace = source_proposal(client, repository, owned_runner)
        with session_factory()() as session:
            tick(session, "automatic-plan")
            source = session.get(Run, source_id)
            validation_id = source.metadata_json["validation_run_id"]
            dep_id = source.metadata_json["dependency_run_ids"][0]
            (workspace / "requirements.txt").write_text("httpx==0.28.1\n")
            assert tick(session, "refuse-changed-manifest") == dep_id
            assert session.get(Run, dep_id).status == "failed"
            assert tick(session, "block-checks") == validation_id
            assert session.get(Run, validation_id).error_type == "PrerequisiteFailed"
        assert not (workspace / "install-proof.json").exists()
        assert not (workspace / "build-proof.txt").exists()


def test_old_manual_project_policy_does_not_start_preparation(repository, owned_runner, validation_sandbox):
    with TestClient(app) as client:
        source_id, _ = source_proposal(client, repository, owned_runner, automatic=False)
        with session_factory()() as session:
            source = session.get(Run, source_id)
            assert "project_plan_run_id" not in source.metadata_json
            assert source.metadata_json["validation_status"] == "not_configured"
            assert tick(session, "no-extra-work") is None


def test_stop_after_readonly_plan_publishes_no_dependency_or_check_job(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    from app.runner_client import RunnerClient

    original = RunnerClient.request
    with TestClient(app) as client:
        source_id, _ = source_proposal(client, repository, owned_runner)
        with session_factory()() as session:
            plan_id = session.get(Run, source_id).metadata_json["project_plan_run_id"]

        def cancel(self, method, path, payload=None):
            result = original(self, method, path, payload)
            if path == "/v1/worktrees/plan":
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, plan_id))
                    session.commit()
            return result

        monkeypatch.setattr(RunnerClient, "request", cancel)
        with session_factory()() as session:
            assert tick(session, "stopped-plan") == plan_id
            assert session.get(Run, plan_id).status == "canceled"
            source = session.get(Run, source_id)
            assert "dependency_run_ids" not in source.metadata_json
            assert "validation_run_id" not in source.metadata_json


def test_saved_commands_override_detected_defaults(repository, owned_runner, validation_sandbox):
    with TestClient(app) as client:
        source_id, _ = source_proposal(client, repository, owned_runner)
        saved = [{"kind": "test", "argv": ["python3", "-m", "unittest", "discover", "-v"]}]
        with session_factory()() as session:
            source = session.get(Run, source_id)
            source.parameters = {**source.parameters, "commands": saved}
            session.commit()
            tick(session, "saved-check-plan")
            session.refresh(source)
            checks = session.get(Run, source.metadata_json["validation_run_id"])
            assert checks.parameters["commands"] == saved
            assert source.metadata_json["automatic_commands"] == saved
            assert "check_warnings" not in source.metadata_json


def test_mixed_root_dependencies_are_separate_ordered_jobs(repository, owned_runner, validation_sandbox):
    from app.models import RunDependency

    with TestClient(app) as client:
        source_id, workspace = source_proposal(client, repository, owned_runner)
        (workspace / "requirements.txt").write_text("demo==1.0.0\n")
        with session_factory()() as session:
            tick(session, "mixed-check-plan")
            source = session.get(Run, source_id)
            deps = [session.get(Run, rid) for rid in source.metadata_json["dependency_run_ids"]]
            assert [r.parameters["ecosystem"] for r in deps] == ["python", "node"]
            assert session.get(RunDependency, (deps[1].id, deps[0].id)) is not None
            assert (
                session.get(RunDependency, (source.metadata_json["validation_run_id"], deps[-1].id))
                is not None
            )


def test_untrusted_planner_cannot_supply_arbitrary_commands(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    from app.runner_client import RunnerClient

    original = RunnerClient.request

    def unsafe(self, method, path, payload=None):
        result = original(self, method, path, payload)
        if path == "/v1/worktrees/plan":
            result["commands"] = [{"kind": "build", "argv": ["bash", "-c", "touch forbidden"]}]
        return result

    monkeypatch.setattr(RunnerClient, "request", unsafe)
    with TestClient(app) as client:
        source_id, workspace = source_proposal(client, repository, owned_runner)
        with session_factory()() as session:
            plan_id = tick(session, "invalid-planner")
            assert session.get(Run, plan_id).status == "failed"
            assert "dependency_run_ids" not in session.get(Run, source_id).metadata_json
        assert not (workspace / "forbidden").exists()


def test_coding_agent_uses_policy_frozen_before_approval():
    from test_agent_coding import project, start

    with TestClient(app) as client, session_factory()() as session:
        row = project(session)
        row.auto_install_dependencies = row.auto_validate = True
        session.commit()
        _, parent = start(client, row.id, require_approval=True)
        run = session.get(Run, parent["id"])
        assert run.parameters["coding_project_policy"]["auto_install_dependencies"]
        assert run.parameters["coding_project_policy"]["auto_validate"]
        assert run.parameters["coding_project_policy"]["project_updated_at"] == row.updated_at.isoformat()
        assert run.status == "waiting_for_approval"
        from sqlalchemy import select

        assert not list(session.scalars(select(Run).where(Run.parent_run_id == run.id)))


def test_detected_checks_must_pass_before_reviewed_commit(repository, owned_runner, validation_sandbox):
    from app.models import Worktree
    from app.reviewed_commits import ReviewedCommit, enqueue_reviewed_commit
    from fastapi import HTTPException

    with TestClient(app) as client:
        source_id, _ = source_proposal(client, repository, owned_runner, automatic=False)
        with session_factory()() as session:
            source = session.get(Run, source_id)
            tree = session.get(Worktree, source.parameters["worktree_id"])
            source.metadata_json = {
                **source.metadata_json,
                "coding_review": {"files": [{"path": "README.md"}], "branch": tree.branch},
                "automatic_commands": [{"kind": "build", "argv": ["npm", "run", "build"]}],
            }
            session.commit()
            with pytest.raises(HTTPException, match="Configured validation"):
                enqueue_reviewed_commit(
                    session, source, ReviewedCommit(message="Reviewed fixture", reviewed=True)
                )


def test_lost_planning_worker_interrupts_without_publishing_or_replaying(
    repository, owned_runner, validation_sandbox
):
    from datetime import timedelta

    from app.db import utcnow
    from app.recovery import recover_stale
    from app.runner_client import RunnerClient
    from app.runs import transition
    from app.state import RunStatus

    with TestClient(app) as client:
        source_id, _ = source_proposal(client, repository, owned_runner)
        with session_factory()() as session:
            source = session.get(Run, source_id)
            plan = session.get(Run, source.metadata_json["project_plan_run_id"])
            transition(session, plan, RunStatus.CLAIMED, event_type="test.claimed")
            transition(session, plan, RunStatus.PREPARING, event_type="test.preparing")
            transition(session, plan, RunStatus.RUNNING, event_type="test.running")
            plan.worker_id = "lost-plan-worker"
            plan.lease_expires_at = utcnow() - timedelta(minutes=10)
            session.commit()
            recover_stale(session, RunnerClient())
            assert plan.status == "interrupted"
            assert "dependency_run_ids" not in source.metadata_json
            assert "validation_run_id" not in source.metadata_json


def test_component_plan_freezes_distinct_dependency_snapshots_and_validation_environment(
    repository,
    owned_runner,
    validation_sandbox,
):
    environment = {
        "python_manifest": "requirements-dev.lock",
        "node_directory": "frontend",
        "python_source_roots": ["backend"],
        "timeout_seconds": 1800,
    }
    with TestClient(app) as client:
        source_id, workspace = source_proposal(client, repository, owned_runner, environment=environment)
        (workspace / "requirements-dev.lock").write_text("pytest==8.3.5\n")
        (workspace / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["backend/tests"]\n')
        (workspace / "backend/tests").mkdir(parents=True)
        (workspace / "backend/tests/test_probe.py").write_text("def test_ok(): assert True\n")
        (workspace / "frontend").mkdir()
        (workspace / "frontend/package.json").write_text('{"scripts":{"build":"vite build"}}')
        with session_factory()() as session:
            source = session.get(Run, source_id)
            plan_id = source.metadata_json["project_plan_run_id"]
            assert tick(session, "component-plan") == plan_id
            session.refresh(source)
            assert session.get(Run, plan_id).status == "succeeded"
            python, node = [session.get(Run, rid) for rid in source.metadata_json["dependency_run_ids"]]
            assert python.parameters["python_manifest"] == "requirements-dev.lock"
            assert python.parameters["manifest_snapshot"]["requirements-dev.lock"]
            assert node.parameters["directory"] == "frontend"
            assert (
                node.parameters["manifest_snapshot"]["package.json"]
                != python.parameters["manifest_snapshot"]["package.json"]
            )
            validation = session.get(Run, source.metadata_json["validation_run_id"])
            assert validation.parameters["validation_environment"] == environment
            assert validation.parameters["node_manifest_snapshot"] == node.parameters["manifest_snapshot"]
            assert validation.parameters["manifest_snapshot"] == python.parameters["manifest_snapshot"]
