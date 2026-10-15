# Imported fixtures share their pytest parameter names.
# ruff: noqa: F811
import hashlib
from datetime import timedelta

import pytest
from app.api import app
from app.artifacts import register_file
from app.config import get_settings
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Run
from app.permissions import PermissionDenied
from app.python_execution import PERMISSIONS, enqueue_python
from app.recovery import recover_stale
from app.runner_client import RunnerClient, RunnerUnavailable
from app.runs import request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner, prepared_validation, repository  # noqa: F401


def queued(client, repository, owned_runner):
    project, tree = prepared_validation(client, repository, [])
    script = b"print('process the selected data')\n"
    (owned_runner.data_dir / tree["relative_path"] / "script.py").write_bytes(script)
    input_file = owned_runner.data_dir / "input.csv"
    input_file.write_bytes(b"value\n27\n")
    with session_factory()() as session:
        inp = register_file(
            session,
            source=input_file,
            artifact_type="document",
            mime_type="text/csv",
            original_filename="input.csv",
            run_id=None,
        )
        task = session.get(Run, tree["run_id"]).task
        params = {
            "worktree_id": tree["id"],
            "script_relative": "script.py",
            "script_sha256": hashlib.sha256(script).hexdigest(),
            "input_artifact_ids": [inp.id],
            "expected_outputs": ["result.csv"],
            "maximum_runtime": 60,
        }
        run = enqueue_python(session, task, params, permissions=list(PERMISSIONS))
        rid, aid = run.id, inp.id
        session.commit()
    return rid, aid, script


def fake_python(monkeypatch, script, *, failed=False, uncertain=False, canceled=False, tamper=False):
    real = RunnerClient.request
    reports = {}

    def request(self, method, path, payload=None):
        original_path = path
        path = path.split("?", 1)[0]
        if path == "/v1/runs/python":
            rid = payload["run_id"]
            root = get_settings().data_dir / f"runtime/python/{rid}"
            (root / "inputs").mkdir(parents=True)
            (root / "inputs/script.py").write_bytes(script)
            data = b"total\n27\n"
            (root / "output-0.csv").write_bytes(data)
            report = {
                "run_id": rid,
                "project_id": payload["project_id"],
                "worktree_run_id": payload["worktree_run_id"],
                "script_sha256": payload["script_sha256"],
                "exit_code": 2 if failed else 0,
                "error": None,
                "succeeded": not failed,
                "outputs": []
                if failed
                else [
                    {
                        "name": "result.csv",
                        "relative_path": f"runtime/python/{rid}/output-0.csv",
                        "size_bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                ],
            }
            if tamper:
                report["outputs"][0]["relative_path"] = "db/ai-station.sqlite"
            reports[rid] = report
            if canceled:
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, rid))
                    session.commit()
            return {
                "pid": 123,
                "process_group_id": 123,
                "runner_id": "fake-python",
                "stdout_log": "runs/fake/stdout.log",
                "stderr_log": "runs/fake/stderr.log",
            }
        if path.startswith("/v1/process/") and method == "GET" and path.rsplit("/", 1)[-1] in reports:
            return {
                "alive": False,
                "completion_pending": False,
                "cleanup_confirmed": not uncertain,
                "status": "canceled" if canceled else "exited",
                "exit_code": 0,
                "stdout": "bounded python output\n",
                "stderr": "",
                "stderr_tail": "",
                "stdout_offset": 22,
                "stderr_offset": 0,
                "stdout_more": False,
                "stderr_more": False,
            }
        if path == "/v1/process/cancel" and payload["run_id"] in reports:
            return {}
        if path.startswith("/v1/runs/python/") and path.endswith("/report"):
            return reports[path.split("/")[-2]]
        return real(self, method, original_path, payload)

    monkeypatch.setattr(RunnerClient, "request", request)
    return reports


def test_python_runs_publish_verified_outputs_source_and_input_lineage(repository, owned_runner, monkeypatch):
    with TestClient(app) as client:
        rid, aid, script = queued(client, repository, owned_runner)
        fake_python(monkeypatch, script)
        with session_factory()() as session:
            assert tick(session, "python-test") == rid
            run = session.get(Run, rid)
            assert run.status == "succeeded" and run.execution_target == "container"
            assert run.effective_permissions == list(PERMISSIONS)
            assert run.metadata_json["process_confirmed_gone"]
            source = session.get(Artifact, run.metadata_json["script_artifact_id"])
            output = session.get(Artifact, run.metadata_json["output_artifact_ids"][0])
            assert source.sha256 == hashlib.sha256(script).hexdigest()
            assert output.parent_artifact_ids == [source.id, aid]
            assert output.mime_type == "text/csv" and output.original_filename == "result.csv"
            assert len(list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))) == 3
        response = client.get(f"/api/artifacts/{output.id}/file")
        assert response.status_code == 200 and response.content == b"total\n27\n"
        assert "attachment" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    "mode,status",
    [("failed", "failed"), ("uncertain", "interrupted"), ("canceled", "canceled"), ("tamper", "failed")],
)
def test_failed_or_uncertain_python_cannot_publish_successful_outputs(
    repository, owned_runner, monkeypatch, mode, status
):
    with TestClient(app) as client:
        rid, aid, script = queued(client, repository, owned_runner)
        fake_python(monkeypatch, script, **{mode: True})
        with session_factory()() as session:
            tick(session, "failed-python")
            run = session.get(Run, rid)
            assert run.status == status
            assert not run.metadata_json.get("output_artifact_ids")
            rows = list(session.scalars(select(Artifact).where(Artifact.run_id == rid)))
            assert not any(row.original_filename == "result.csv" for row in rows)


def test_python_requires_explicit_permission_and_owned_workspace(repository, owned_runner):
    with TestClient(app) as client:
        rid, _, _ = queued(client, repository, owned_runner)
        with session_factory()() as session:
            run = session.get(Run, rid)
            params = {
                key: run.parameters[key]
                for key in (
                    "worktree_id",
                    "script_relative",
                    "script_sha256",
                    "input_artifact_ids",
                    "expected_outputs",
                    "maximum_runtime",
                )
            }
            with pytest.raises(PermissionDenied):
                enqueue_python(session, run.task, params, permissions=["filesystem_read", "workspace_write"])
            params["input_artifact_ids"] = ["11111111-1111-4111-8111-111111111111"]
            with pytest.raises(ValueError, match="unavailable"):
                enqueue_python(session, run.task, params, permissions=list(PERMISSIONS))


def test_lost_runner_does_not_release_or_replay_python_execution(repository, owned_runner):
    with TestClient(app) as client:
        rid, _, _ = queued(client, repository, owned_runner)
        with session_factory()() as session:
            run = session.get(Run, rid)
            run.status = "running"
            run.worker_id = "lost"
            run.metadata_json = {"dispatch_attempted": True}
            run.lease_expires_at = utcnow() - timedelta(seconds=60)
            session.commit()

            class MissingRunner:
                def inspect_process(self, run_id):
                    raise RunnerUnavailable("temporarily unavailable")

            assert recover_stale(session, MissingRunner()) == [rid]
            session.refresh(run)
            assert run.status == "running" and run.lease_expires_at > utcnow()
