# Disposable repository/Runner fixtures are imported with their parameter names.
# ruff: noqa: F811
import hashlib
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.api import app
from app.coding_tasks import queue_validation
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Project, Run, Task, Worktree
from app.runs import create_run, create_task
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner, prepared_validation, repository, validation_sandbox  # noqa: F401


def prepared_checks(client, repository, owned_runner, *, exit_code=0, manifest=False):
    project, tree = prepared_validation(client, repository, [])
    workspace = owned_runner.data_dir / tree["relative_path"]
    snapshot = None
    if manifest:
        (workspace / "package.json").write_text("{}")
        snapshot = {
            "requirements.txt": None,
            "pyproject.toml": None,
            "package.json": hashlib.sha256(b"{}").hexdigest(),
        }
    commands = [
        {
            "kind": "test",
            "argv": [
                "/usr/bin/python3",
                "-c",
                f"from pathlib import Path; p=Path('check-count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); raise SystemExit({exit_code})",
            ],
        },
        {
            "kind": "build",
            "argv": [
                "/usr/bin/python3",
                "-c",
                "from pathlib import Path; p=Path('dist'); p.mkdir(exist_ok=True); (p/'index.html').write_text('<h1>Built</h1>')",
            ],
        },
    ]
    with session_factory()() as session:
        prep = session.get(Run, tree["run_id"])
        source = create_run(
            session,
            prep.task,
            run_type="coding",
            capability="coding.local",
            executor_type="local_proposal",
            project_id=project["id"],
            parent_run_id=prep.id,
            parameters={
                "commands": commands,
                "worktree_id": tree["id"],
                "worktree_run_id": prep.id,
                "max_repair_attempts": 0,
            },
            metadata={
                "execution_location": "local",
                "coding_review": {"branch": tree["branch"], "files": []},
            },
        )
        source.status = "succeeded"
        session.flush()
        queue_validation(session, source, prepared=True, manifest_snapshot=snapshot)
        sid = source.id
        vid = source.metadata_json["validation_run_id"]
        tid = source.task_id
        session.commit()
    with session_factory()() as session:
        assert tick(session, "initial-checks") == vid
    return {
        "source": sid,
        "validation": vid,
        "task": tid,
        "project": project["id"],
        "tree": tree["id"],
        "workspace": workspace,
        "snapshot": snapshot,
        "commands": commands,
    }


def repeat(client, proof, **extra):
    return client.post(
        "/api/coding/runs/" + proof["source"] + "/checks",
        json={"expected_validation_run_id": proof["validation"], **extra},
    )


def test_repeat_preserves_task_scope_history_and_build_artifacts(
    repository, owned_runner, validation_sandbox
):
    before = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        old = client.get("/api/runs/" + proof["validation"]).json()
        version = client.get("/api/projects/" + proof["project"]).json()["updated_at"]
        with session_factory()() as session:
            session.get(Project, proof["project"]).test_commands = [["/usr/bin/false"]]
            prior = session.get(Run, proof["validation"])
            prior.parameters = {**prior.parameters, "agent_coding_deadline": "2000-01-01T00:00:00+00:00"}
            session.commit()
        response = repeat(client, proof)
        assert response.status_code == 202, response.text
        new = response.json()
        assert (
            new["task_id"] == proof["task"]
            and new["parent_run_id"] == proof["source"]
            and new["project_id"] == proof["project"]
        )
        assert (
            new["parameters"]["commands"] == proof["commands"]
            and new["parameters"]["worktree_id"] == proof["tree"]
        )
        assert (
            new["parameters"]["manual_checks_only"] is True
            and new["parameters"]["rerun_of"] == proof["validation"]
        )
        assert "agent_coding_deadline" not in new["parameters"]
        assert client.get("/api/projects/" + proof["project"]).json()["updated_at"] == version
        with session_factory()() as session:
            assert tick(session, "repeat-checks") == new["id"]
        checked = client.get("/api/runs/" + new["id"]).json()
        assert checked["status"] == "succeeded", checked
        assert (proof["workspace"] / "check-count.txt").read_text() == "2"
        assert old["metadata"]["build_artifact_id"] != checked["metadata"]["build_artifact_id"]
        for aid in (old["metadata"]["build_artifact_id"], checked["metadata"]["build_artifact_id"]):
            response = client.get("/api/artifacts/" + aid + "/file")
            assert response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                assert z.read("index.html") == b"<h1>Built</h1>"
        history = client.get("/api/coding/sessions/" + proof["task"]).json()["runs"]
        assert {proof["validation"], new["id"]} <= {r["id"] for r in history}
        assert len([r for r in history if r["executor_type"] == "local_proposal"]) == 1
        assert client.get("/api/runs/" + proof["source"]).json()["metadata"]["validation_run_id"] == new["id"]
        events = client.get("/api/runs/" + new["id"] + "/events").json()
        assert any(e["event_type"] == "validation.rerun_requested" for e in events)
    assert (repository / ".git/index").read_bytes() == before and not (
        repository / "check-count.txt"
    ).exists()


def test_failed_manual_checks_never_trigger_inference_repair_or_dependencies(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner, exit_code=1)
        with session_factory()() as session:
            source = session.get(Run, proof["source"])
            source.parameters = {**source.parameters, "max_repair_attempts": 2}
            session.commit()

        def forbidden(*args, **kwargs):
            raise AssertionError("Manual checks must not invoke a coding model")

        monkeypatch.setattr("app.local_coding.enqueue_local_repair", forbidden)
        response = repeat(client, proof)
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            assert tick(session, "failed-repeat") == rid
        run = client.get("/api/runs/" + rid).json()
        assert run["status"] == "failed" and run["error_type"] == "ValidationFailed"
        history = client.get("/api/coding/sessions/" + proof["task"]).json()["runs"]
        assert [r["executor_type"] for r in history].count("local_proposal") == 1
        assert all(r["executor_type"] not in ("llama_load", "project_dependencies") for r in history)
        assert not [
            item
            for item in client.get("/api/artifacts", params={"run_id": rid}).json()
            if item["type"] == "archive"
        ]


def test_repeat_is_atomic_for_concurrent_and_stale_requests(repository, owned_runner, validation_sandbox):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: repeat(client, proof), range(2)))
        assert sorted(r.status_code for r in responses) == [202, 409], [r.text for r in responses]
        assert repeat(client, proof).status_code == 409
        runs = client.get("/api/coding/sessions/" + proof["task"]).json()["runs"]
        assert len([r for r in runs if r["executor_type"] == "project_validation"]) == 2
        assert repeat(client, proof, commands=[["/bin/sh", "-c", "echo no"]]).status_code == 422


@pytest.mark.parametrize(
    "condition",
    [
        "removed",
        "unowned",
        "superseded",
        "active_other_task",
        "wrong_parent",
        "wrong_task",
        "wrong_worktree",
        "wrong_target",
        "wrong_capability",
        "wrong_permissions",
        "uncertain_process",
        "preparation_failed",
        "invalid_commands",
        "invalid_manifest",
    ],
)
def test_invalid_or_unsafe_scope_never_publishes_a_repeat(
    repository, owned_runner, validation_sandbox, condition
):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        with session_factory()() as session:
            source = session.get(Run, proof["source"])
            previous = session.get(Run, proof["validation"])
            tree = session.get(Worktree, proof["tree"])
            if condition == "removed":
                tree.removed_at = utcnow()
            elif condition == "unowned":
                tree.owned = False
            elif condition == "superseded":
                source.metadata_json = {**source.metadata_json, "continuation_run_id": str(uuid4())}
            elif condition == "active_other_task":
                task = create_task(
                    session,
                    title="Other task",
                    prompt="No execution",
                    capability="test.echo",
                    project_id=proof["project"],
                )
                create_run(session, task, run_type="test", capability="test.echo", executor_type="test")
            elif condition == "wrong_parent":
                previous.parent_run_id = tree.run_id
            elif condition == "wrong_task":
                task = create_task(
                    session,
                    title="Other task",
                    prompt="No execution",
                    capability="test.echo",
                    project_id=proof["project"],
                )
                previous.task_id = task.id
            elif condition == "wrong_worktree":
                previous.parameters = {**previous.parameters, "worktree_id": str(uuid4())}
            elif condition == "wrong_target":
                previous.execution_target = "container"
            elif condition == "wrong_capability":
                previous.capability = "unrelated.action"
            elif condition == "wrong_permissions":
                previous.effective_permissions = ["external_ai"]
            elif condition == "uncertain_process":
                previous.status = "interrupted"
                previous.metadata_json = {**previous.metadata_json, "process_confirmed_gone": False}
            elif condition == "preparation_failed":
                session.get(Run, tree.run_id).status = "failed"
            elif condition == "invalid_commands":
                previous.parameters = {
                    **previous.parameters,
                    "commands": [{"kind": "test", "argv": ["bash", "-c", "anything"]}],
                }
            else:
                previous.parameters = {
                    **previous.parameters,
                    "manifest_snapshot": {"package.json": "invalid"},
                }
            session.commit()
            count = len(list(session.scalars(select(Run.id))))
        response = repeat(client, proof)
        assert response.status_code == 409, (condition, response.text)
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run.id)))) == count
            assert session.get(Run, proof["source"]).metadata_json["validation_run_id"] == proof["validation"]


def test_fresh_repeat_can_resume_stopped_task_and_can_be_stopped_before_dispatch(
    repository, owned_runner, validation_sandbox
):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        with session_factory()() as session:
            session.get(Task, proof["task"]).metadata_json = {"stop_requested_at": utcnow().isoformat()}
            session.commit()
        response = repeat(client, proof)
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        assert client.post("/api/coding/sessions/" + proof["task"] + "/cancel").status_code == 200
        assert client.get("/api/runs/" + rid).json()["status"] == "canceled"
        assert (proof["workspace"] / "check-count.txt").read_text() == "1"
        assert not client.get("/api/artifacts", params={"run_id": rid}).json()


def test_repeat_keeps_manifest_snapshot_and_rejects_dependency_changes(
    repository, owned_runner, validation_sandbox
):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner, manifest=True)
        (proof["workspace"] / "package.json").write_text('{"dependencies":{"changed":"1"}}')
        response = repeat(client, proof)
        assert response.status_code == 202, response.text
        new = response.json()
        assert new["parameters"]["manifest_snapshot"] == proof["snapshot"]
        with session_factory()() as session:
            assert tick(session, "changed-manifest-repeat") == new["id"]
        failed = client.get("/api/runs/" + new["id"]).json()
        assert failed["status"] == "failed" and failed["error_type"] == "ValidationExecutionFailed"
        assert (proof["workspace"] / "check-count.txt").read_text() == "1"


@pytest.mark.parametrize("known_identity", [False, True])
def test_only_provably_undispatched_failures_can_repeat_without_gone_marker(
    repository, owned_runner, validation_sandbox, known_identity
):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        with session_factory()() as session:
            previous = session.get(Run, proof["validation"])
            previous.status = "canceled"
            previous.metadata_json = {"dispatch_attempted": False}
            previous.pid = None
            previous.process_group_id = 123 if known_identity else None
            previous.runner_id = None
            previous.started_at = None
            session.commit()
        response = repeat(client, proof)
        assert response.status_code == (409 if known_identity else 202), response.text


def test_already_committed_turn_can_repeat_its_recorded_checks(repository, owned_runner, validation_sandbox):
    with TestClient(app) as client:
        proof = prepared_checks(client, repository, owned_runner)
        with session_factory()() as session:
            source = session.get(Run, proof["source"])
            source.metadata_json = {
                **source.metadata_json,
                "commit_run_id": str(uuid4()),
                "review_status": "committed",
            }
            session.commit()
        response = repeat(client, proof)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            assert tick(session, "check-committed-turn") == response.json()["id"]
        assert client.get("/api/runs/" + response.json()["id"]).json()["status"] == "succeeded"
