"""Agent checks select the existing bounded local correction policy."""

import pytest
from app.api import app
from app.coding_tasks import queue_proposal
from app.db import session_factory
from app.engine import tick
from app.models import Run, RunEvent, Worktree
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_coding import project, start
from test_projects import local_coding_bridge as local_coding_bridge
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_projects import validation_sandbox as validation_sandbox


@pytest.mark.parametrize("automatic_checks", [False, True])
def test_saved_project_checks_choose_and_freeze_one_agent_repair(automatic_checks):
    with TestClient(app) as api, session_factory()() as s:
        row = project(s)
        row.auto_validate = automatic_checks
        s.commit()
        agent, parent = start(api, row.id)
        assert tick(s, "agent-repair") == parent["id"]
        preparation = s.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        body = preparation.parameters["local_coding"]
        assert body["max_repair_attempts"] == int(automatic_checks)
        assert body["project_check_policy"]["auto_validate"] == automatic_checks
        policy = s.scalar(
            select(RunEvent).where(
                RunEvent.run_id == preparation.id, RunEvent.event_type == "coding.repair.policy"
            )
        )
        assert bool(policy) == automatic_checks
        if policy:
            assert (
                policy.payload["maximum_attempts"] == 1
                and policy.payload["deadline_at"] == preparation.parameters["agent_coding_deadline"]
            )
        tree = s.scalar(select(Worktree).where(Worktree.run_id == preparation.id))
        preparation.metadata_json = {**preparation.metadata_json, "worktree": {"branch": tree.branch}}
        queue_proposal(s, preparation, tree)
        proposal = s.get(Run, preparation.metadata_json["coding_run_id"])
        assert proposal.parameters["max_repair_attempts"] == int(automatic_checks)
        assert proposal.parameters["agent_coding_deadline"] == preparation.parameters["agent_coding_deadline"]
        assert proposal.task_id == parent["task_id"] and proposal.agent_id == agent["id"]


def test_private_workspace_uses_its_saved_automatic_check_policy():
    from test_agent_workspace import native_finish, setup
    from test_agent_workspace import start as auto_start

    with TestClient(app) as api, session_factory()() as s:
        _, parent = auto_start(api, workspace_policy={"auto_validate": True})
        stage = setup(s, parent)
        native_finish(s, stage)
        child = s.get(Run, stage.metadata_json["workspace_workflow_run_id"])
        assert tick(s, "agent-repair") == child.id
        preparation = s.scalar(select(Run).where(Run.parent_run_id == child.id))
        assert preparation.parameters["local_coding"]["max_repair_attempts"] == 1
        assert (
            preparation.parameters["agent_coding_deadline"]
            == s.get(Run, parent["id"]).parameters["agent_coding_deadline"]
        )


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "expired"])
def test_agent_checks_run_one_real_worktree_correction_then_stop(
    repository, owned_runner, local_coding_bridge, validation_sandbox, monkeypatch, outcome
):
    import subprocess
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app.assistant import task_results
    from test_projects import register

    (repository / "test_result.py").write_text(
        "import pathlib,subprocess,sys,unittest\n"
        "class Result(unittest.TestCase):\n"
        " def test_result(self):\n"
        "  self.assertEqual(subprocess.check_output([sys.executable,str(pathlib.Path(__file__).with_name('new.py'))]).strip(),b'42')\n"
    )
    subprocess.run(["git", "-C", str(repository), "add", "test_result.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "Trusted check"], check=True, capture_output=True
    )
    local_coding_bridge["mode"] = "explore"
    with TestClient(app) as api:
        saved = register(api, repository, auto_validate=True)
        agent, parent = start(api, saved["id"], model="fixture-local")
        for _ in range(3):
            with session_factory()() as s:
                assert tick(s, "agent-checked-build") is not None
        with session_factory()() as s:
            original = s.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "local_proposal")
            )
            assert original.status == "succeeded", original.error_message
            deadline = original.parameters["agent_coding_deadline"]
        if outcome == "expired":
            monkeypatch.setattr(
                "app.local_coding.utcnow", lambda: datetime.fromisoformat(deadline) + timedelta(seconds=1)
            )
        local_coding_bridge["mode"] = "success"
        local_coding_bridge["proposal"] = {
            "summary": "Fix result while keeping trusted checks",
            "files": [
                {"path": "new.py", "content": "print(" + ("42" if outcome == "succeeded" else "41") + ")\n"}
            ],
        }
        for _ in range(12):
            with session_factory()() as s:
                if tick(s, "agent-checked-build") is None:
                    break
        with session_factory()() as s:
            rows = list(
                s.scalars(select(Run).where(Run.task_id == parent["task_id"]).order_by(Run.created_at))
            )
            proposals = [row for row in rows if row.executor_type == "local_proposal"]
            checks = [row for row in rows if row.executor_type == "project_validation"]
            if outcome == "expired":
                assert len(proposals) == len(checks) == 1
                assert s.scalar(
                    select(RunEvent).where(
                        RunEvent.run_id == checks[0].id, RunEvent.event_type == "coding.repair.expired"
                    )
                )
                return
            assert len(proposals) == len(checks) == 2
            assert all(
                row.parameters["max_repair_attempts"] == 1
                and row.parameters["agent_coding_deadline"] == deadline
                for row in proposals
            )
            assert all(row.agent_id == agent["id"] for row in proposals)
            assert (
                checks[0].status == "failed" and checks[0].metadata_json["repair_run_id"] == proposals[-1].id
            )
            assert checks[-1].status == outcome
            assert bool(checks[-1].metadata_json.get("repair_budget_exhausted")) == (outcome == "failed")
            projected = task_results(s, SimpleNamespace(metadata_json={"orchestration": True}), proposals[0])
            assert projected["task_status"] == outcome
            assert len({row.parameters["worktree_id"] for row in proposals}) == 1
    assert not (repository / "new.py").exists()
    assert (repository / "README.md").read_text() == "Original repository\n"
