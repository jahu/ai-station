"""Preview source provenance and typed controls, without a browser or native process."""

import hashlib
import zipfile
from uuid import uuid4

import pytest
from app.build_artifacts import register_build
from app.config import get_settings
from app.models import Artifact, Project
from app.runs import create_run, create_task
from app.site_preview import Interact, OpenPreview, source_snapshot, viewport_action
from fastapi import HTTPException
from pydantic import ValidationError


def built(session, entries=None):
    project = Project(name="Disposable site", repo_path="/projects/site")
    session.add(project)
    session.flush()
    task = create_task(
        session, title="Build site", prompt="", capability="coding.local", project_id=project.id
    )
    run = create_run(
        session,
        task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        parameters={"worktree_run_id": str(uuid4())},
    )
    session.flush()
    path = get_settings().data_dir / f"runtime/validation/{run.id}.build.zip"
    path.parent.mkdir(parents=True)
    entries = entries or {"index.html": "<h1>Immutable site</h1>"}
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    report = {
        "commands": [{"kind": "build", "exit_code": 0}],
        "build_export": {
            "status": "ready",
            "relative_path": str(path.relative_to(get_settings().data_dir)),
            "file_count": len(entries),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "uncompressed_bytes": sum(len(content.encode()) for content in entries.values()),
        },
    }
    register_build(session, run, report)
    run.status = "succeeded"
    session.flush()
    artifact = session.get(Artifact, run.metadata_json["build_artifact_id"])
    return run, artifact


def test_preview_freezes_the_actual_registered_build_without_a_worktree_or_file_read(session, monkeypatch):
    run, artifact = built(session)
    # An archived/removed source workspace is not needed to inspect its immutable build.
    from pathlib import Path

    monkeypatch.setattr(
        Path, "read_bytes", lambda *_: pytest.fail("HTTP source inspection must not read build bytes")
    )
    value = source_snapshot(session, run.id, artifact.id)
    assert value["project_id"] == run.project_id and value["source_task_id"] == run.task_id
    assert value["artifact_id"] == artifact.id and value["sha256"] == artifact.sha256
    assert (
        value["validation_run_id"] == run.id and value["worktree_run_id"] == run.parameters["worktree_run_id"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "failed",
        "executor",
        "artifact_id",
        "artifact_run",
        "path",
        "role",
        "project",
        "size",
        "hash",
        "lineage",
    ],
)
def test_preview_rejects_an_unverified_or_unrelated_build(session, change):
    run, artifact = built(session)
    if change == "failed":
        run.status = "failed"
    elif change == "executor":
        run.executor_type = "local_proposal"
    elif change == "artifact_id":
        run.metadata_json = {**run.metadata_json, "build_artifact_id": str(uuid4())}
    elif change == "artifact_run":
        other_task = create_task(session, title="Unrelated producer", prompt="", capability="coding.local")
        other_run = create_run(
            session, other_task, run_type="coding", capability="coding.local", executor_type="local_proposal"
        )
        artifact.run_id = other_run.id
    elif change == "path":
        artifact.relative_path = "db/ai-station.sqlite"
    elif change == "role":
        artifact.metadata_json = {**artifact.metadata_json, "role": "upload"}
    elif change == "project":
        artifact.metadata_json = {**artifact.metadata_json, "project_id": str(uuid4())}
    elif change == "size":
        artifact.size_bytes += 1
    elif change == "hash":
        artifact.sha256 = "b" * 64
    else:
        other = create_task(session, title="Other project intent", prompt="", capability="coding.local")
        parent = create_run(
            session, other, run_type="coding", capability="coding.local", executor_type="local_proposal"
        )
        run.parent_run_id = parent.id
        artifact.metadata_json = {**artifact.metadata_json, "source_run_id": parent.id}
    with pytest.raises(HTTPException) as error:
        source_snapshot(session, run.id, artifact.id)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "evaluate", "script": "alert(1)"},
        {"kind": "click", "x": True, "y": 0},
        {"kind": "text", "text": "x\x00"},
        {"kind": "key", "key": "Control+L"},
        {"kind": "reset", "url": "https://example.org"},
    ],
)
def test_public_action_schema_cannot_smuggle_code_urls_hotkeys_or_boolean_coordinates(action):
    with pytest.raises(ValidationError):
        Interact(client_request_id=uuid4(), expected_revision=0, action=action)


def test_typed_click_coordinates_are_bound_to_the_shown_viewport():
    value = Interact(
        client_request_id=uuid4(), expected_revision=0, action={"kind": "click", "x": 390, "y": 20}
    )
    with pytest.raises(HTTPException) as error:
        viewport_action(value, {"width": 390, "height": 844})
    assert error.value.status_code == 422
    value = Interact(
        client_request_id=uuid4(),
        expected_revision=0,
        action={"kind": "text", "text": "<script>literal text</script>"},
    )
    assert viewport_action(value, {"width": 390, "height": 844}) == {
        "kind": "text",
        "text": "<script>literal text</script>",
    }
    with pytest.raises(ValidationError):
        OpenPreview(client_request_id=uuid4(), source_run_id=uuid4(), artifact_id=uuid4(), image="untrusted")
