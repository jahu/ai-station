"""Website completion is proven by owned native output, not model claims."""

# Imported disposable repository/runner fixtures retain their parameter names.
# ruff: noqa: F811
import io
import zipfile

import pytest
from app.api import app
from app.coding_tasks import queue_validation
from app.db import session_factory
from app.engine import tick
from app.models import Run, RunEvent
from app.runs import create_run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_automatic_project_checks import source_proposal
from test_projects import owned_runner, prepared_validation, repository, validation_sandbox  # noqa: F401


def website_source(client, repository, owned_runner, code, *, repair=False):
    _, tree = prepared_validation(client, repository, [])
    workspace = owned_runner.data_dir / tree["relative_path"]
    with session_factory()() as session:
        prep = session.get(Run, tree["run_id"])
        source = create_run(
            session,
            prep.task,
            run_type="coding",
            capability="coding.local",
            executor_type="local_proposal",
            execution_target="host",
            project_id=prep.project_id,
            parent_run_id=prep.id,
            parameters={
                "worktree_id": tree["id"],
                "worktree_run_id": prep.id,
                "commands": [{"kind": "build", "argv": ["/usr/bin/python3", "-c", code]}],
                "output_contract": "static_site",
                "prompt": "Build the reviewed website",
                "files": ["index.html", "build.py"],
                "model": "fixture-local",
                "endpoint": "http://127.0.0.1:9999/v1",
                "guidance": "Keep scope and checks",
                "max_repair_attempts": int(repair),
            },
        )
        source.status = "succeeded"
        source.metadata_json = {"coding_review": {"files": [{"path": "index.html"}]}}
        queue_validation(session, source, prepared=True)
        validation_id = source.metadata_json["validation_run_id"]
        session.commit()
        return source.id, validation_id, workspace


@pytest.mark.parametrize("output", ["missing", "empty", "fresh"])
def test_exit_zero_only_passes_with_new_nonempty_verified_website(
    repository, owned_runner, validation_sandbox, output
):
    script = {
        "missing": "print('Build completed')",
        "empty": "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').touch()",
        "fresh": "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').write_text('<h1>New website</h1>')",
    }[output]
    with TestClient(app) as client:
        _, validation_id, workspace = website_source(client, repository, owned_runner, script)
        (workspace / "dist").mkdir()
        (workspace / "dist/index.html").write_text("Previous website")
        with session_factory()() as session:
            assert tick(session, "website-output") == validation_id
            validation = session.get(Run, validation_id)
            assert validation.status == ("succeeded" if output == "fresh" else "failed"), (
                validation.error_message
            )
            report = validation.metadata_json["validation"]
            assert report["commands"][0]["exit_code"] == 0
            assert report["output_contract"] == "static_site"
            assert report["output_check"]["succeeded"] == (output == "fresh")
            previous = workspace / report["previous_build_relative"] / "index.html"
            assert previous.read_text() == "Previous website"
            assert bool(validation.metadata_json.get("build_artifact_id")) == (output == "fresh")
            assert session.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == validation_id, RunEvent.event_type == "validation.output_checked"
                )
            )
        # A missing/empty output fails controller acceptance without inventing a native failure.
        process = owned_runner.inspect(validation_id)
        assert not process["alive"] and process["exit_code"] == 0
        artifacts = client.get("/api/artifacts", params={"run_id": validation_id}).json()
        validation_json = next(a for a in artifacts if a["original_filename"] == "validation.json")
        saved = client.get("/api/artifacts/" + validation_json["id"] + "/file").json()
        assert saved["output_check"]["succeeded"] == (output == "fresh")
        if output == "fresh":
            artifact = next(a for a in artifacts if a["type"] == "archive")
            data = client.get("/api/artifacts/" + artifact["id"] + "/file")
            with zipfile.ZipFile(io.BytesIO(data.content)) as archive:
                assert archive.namelist() == ["index.html"]
                assert archive.read("index.html") == b"<h1>New website</h1>"
    assert not (repository / "dist").exists()


def test_missing_detected_command_fails_in_worker_without_native_dispatch(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    from app.runner_client import RunnerClient

    with TestClient(app) as client:
        source_id, workspace = source_proposal(
            client, repository, owned_runner, output_contract="static_site"
        )
        (workspace / "package.json").unlink()
        with session_factory()() as session:
            assert tick(session, "website-plan")
            source = session.get(Run, source_id)
            validation_id = source.metadata_json["validation_run_id"]
            assert not session.get(Run, validation_id).parameters["commands"]
            assert not source.metadata_json["dependency_run_ids"]

            def forbidden(*args, **kwargs):
                pytest.fail("Empty website checks must not launch a native process")

            monkeypatch.setattr(RunnerClient, "start_validation", forbidden)
            assert tick(session, "website-no-build") == validation_id
            validation = session.get(Run, validation_id)
            assert validation.status == "failed" and validation.error_type == "ValidationFailed"
            assert validation.metadata_json["validation"]["output_check"]["succeeded"] is False
            assert "dispatch_attempted" not in validation.metadata_json
            assert "dist/index.html" in validation.error_message


def test_missing_output_queues_one_scoped_repair_with_real_diagnostic(
    repository, owned_runner, validation_sandbox
):
    with TestClient(app) as client:
        source_id, validation_id, _ = website_source(
            client, repository, owned_runner, "print('Build completed')", repair=True
        )
        with session_factory()() as session:
            assert tick(session, "website-output-repair") == validation_id
            validation = session.get(Run, validation_id)
            source = session.get(Run, source_id)
            repair = session.get(Run, validation.metadata_json["repair_run_id"])
            assert repair.parameters["files"] == source.parameters["files"]
            assert repair.parameters["worktree_id"] == source.parameters["worktree_id"]
            assert repair.parameters["commands"] == source.parameters["commands"]
            assert repair.parameters["output_contract"] == "static_site"
            assert repair.parameters["repair_attempt"] == repair.parameters["max_repair_attempts"] == 1
            assert repair.task_id == source.task_id and repair.parent_run_id == validation_id
            assert "dist/index.html" in repair.parameters["prompt"]
            assert '"failed_commands": []' in repair.parameters["prompt"]
            assert "Do not weaken tests" in repair.parameters["prompt"]
            from app.local_coding import queue_automatic_repair

            queue_automatic_repair(session, validation)
            assert len(list(session.scalars(select(Run).where(Run.parent_run_id == validation_id)))) == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_agent_freezes_website_expectation_only_with_reviewed_checks(automatic):
    from test_agent_coding import project, start

    with TestClient(app) as client, session_factory()() as session:
        row = project(session)
        row.auto_validate = automatic
        session.commit()
        _, parent = start(client, row.id, goal="Odczytaj stronę i zbuduj nową wersję HTML/CSS")
        assert tick(session, "website-agent") == parent["id"]
        prep = session.scalar(select(Run).where(Run.parent_run_id == parent["id"]))
        request = prep.parameters["local_coding"]
        assert request.get("output_contract") == ("static_site" if automatic else None)
        if automatic:
            assert "nonempty dist/index.html" in request["guidance"]
        assert "external_ai" not in prep.effective_permissions


def test_same_workspace_followup_keeps_required_output_and_scope(
    repository, owned_runner, validation_sandbox
):
    with TestClient(app) as client:
        source_id, validation_id, _ = website_source(
            client,
            repository,
            owned_runner,
            "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').write_text('<h1>First</h1>')",
        )
        with session_factory()() as session:
            assert tick(session, "first-website") == validation_id
            source = session.get(Run, source_id)
            original = dict(source.parameters)
            task_id = source.task_id
        response = client.post(
            f"/api/coding/sessions/{task_id}/messages",
            json={"prompt": "Change the title", "expected_run_id": source_id},
        )
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            followup = session.get(Run, response.json()["id"])
            assert followup.task_id == task_id
            assert followup.parameters["worktree_id"] == original["worktree_id"]
            assert followup.parameters["files"] == original["files"]
            assert followup.parameters["output_contract"] == "static_site"
            assert followup.parameters["cumulative"] is True


def test_explicit_check_repeat_cannot_drop_website_expectation(repository, owned_runner, validation_sandbox):
    with TestClient(app) as client:
        source_id, validation_id, _ = website_source(
            client,
            repository,
            owned_runner,
            "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').write_text('<h1>Checked</h1>')",
        )
        with session_factory()() as session:
            assert tick(session, "first-website-check") == validation_id
        response = client.post(
            f"/api/coding/runs/{source_id}/checks", json={"expected_validation_run_id": validation_id}
        )
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            repeat = session.get(Run, rid)
            assert repeat.parameters["output_contract"] == "static_site"
            assert repeat.parameters["manual_checks_only"] is True
            assert tick(session, "repeat-website-check") == rid
            assert repeat.status == "succeeded", repeat.error_message
            assert repeat.metadata_json["validation"]["output_check"]["succeeded"]
            assert repeat.metadata_json["validation"]["previous_build_relative"]
