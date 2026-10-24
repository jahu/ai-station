"""Saved final result context reuses provenance without rerunning an agent."""

import hashlib
import json

import pytest
from app.agent_result_context import reference
from app.config import get_settings
from app.db import session_factory
from app.models import Artifact, Message, Run
from app.paths import safe_join
from sqlalchemy import select
from test_agent_result_context import completed, followup
from test_conversation_agent_control import enable, result, send, step
from test_conversation_agent_control import saved as saved
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def family_result(saved, monkeypatch, family):
    mid, rid, aid = completed(saved, monkeypatch)
    with session_factory()() as db:
        source, artifact = db.get(Run, rid), db.get(Artifact, aid)
        root = db.get(Run, source.parent_run_id)
        definition = dict(root.parameters["definition"])
        if family == "coding":
            definition.update(tools=["coding_local"])
            source.executor_type = "local_proposal"
            source.parameters = {"worktree_run_id": "owned-tree"}
            review = {
                "run_id": rid,
                "project_id": source.project_id,
                "worktree_run_id": "owned-tree",
                "files": [{"path": "app.py", "insertions": 3}],
                "summary": "Created the requested calculator.",
            }
            source.metadata_json = {"coding_review": review}
            content = json.dumps(review).encode()
            artifact.mime_type = "application/json"
            artifact.artifact_type = "json"
            artifact.original_filename = "coding-review.json"
        else:
            definition.update(
                tools=["create_media"],
                media={"kind": "image", "request": {"mode": "t2i", "prompt": "A synthetic fixture image"}},
            )
            source.executor_type = "photo_pipe"
            content = b"Synthetic media metadata fixture; no real image inference"
            artifact.artifact_type = "image"
            artifact.mime_type = "image/png"
            artifact.original_filename = "result.png"
        root.parameters = {**root.parameters, "definition": definition}
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(content)
        artifact.size_bytes, artifact.sha256 = len(content), hashlib.sha256(content).hexdigest()
        db.commit()
    return mid, rid, aid


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_coding_review_becomes_quoted_context_without_another_execution(saved, monkeypatch, mode):
    mid, rid, aid = family_result(saved, monkeypatch, "coding")
    with session_factory()() as db:
        text, source = reference(db, db.get(Message, mid))
        assert source["available"] and source["family"] == "coding"
        assert source["run_id"] == rid and source["artifact_id"] == aid
        assert "app.py" in text and "Created the requested calculator" in text
    followup(saved, mode=mode)
    step()
    with session_factory()() as db:
        chat = db.scalar(select(Run).where(Run.executor_type == "chat"))
        assert "app.py" in str(chat.parameters["messages"])
        assert not {"workspace_write", "shell_project_commands"}.intersection(chat.effective_permissions)
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "agent_workflow")))) == 1


@pytest.mark.parametrize("problem", ["bytes", "metadata", "trashed", "superseded", "shape"])
def test_changed_or_unavailable_coding_review_is_never_quoted(saved, monkeypatch, problem):
    mid, rid, aid = family_result(saved, monkeypatch, "coding")
    with session_factory()() as db:
        artifact, run = db.get(Artifact, aid), db.get(Run, rid)
        if problem == "bytes":
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"replacement")
        elif problem == "shape":
            contents = b"[]"
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(contents)
            artifact.size_bytes, artifact.sha256 = len(contents), hashlib.sha256(contents).hexdigest()
            run.metadata_json = {"coding_review": []}
        elif problem == "metadata":
            run.metadata_json = {"coding_review": {"summary": "A different result"}}
        elif problem == "trashed":
            from app.db import utcnow

            artifact.trashed_at = utcnow()
        else:
            run.metadata_json = {**run.metadata_json, "repair_run_id": "replacement"}
        db.commit()
        text, source = reference(db, db.get(Message, mid))
        assert not source["available"] and "Created the requested calculator" not in text


def test_media_quotes_only_published_metadata_without_reading_or_claiming_pixels(saved, monkeypatch):
    mid, _, aid = family_result(saved, monkeypatch, "media")

    def forbidden(*args, **kwargs):
        raise AssertionError("Media contents must not be read by the conversation enqueue")

    monkeypatch.setattr("app.agent_email_results.artifact_content", forbidden)
    with session_factory()() as db:
        text, source = reference(db, db.get(Message, mid))
        assert source["available"] and source["family"] == "media"
        assert source["inspection"] == "publication_metadata_only" and aid in text
        assert "have not been inspected" in text and "Synthetic media metadata fixture" not in text


def test_shared_email_reader_retains_strict_media_byte_verification(saved, monkeypatch):
    from app.agent_email_results import verified_result
    from app.agent_schema import AgentSettings

    mid, rid, aid = family_result(saved, monkeypatch, "media")
    with session_factory()() as db:
        source = db.get(Run, rid)
        root = db.get(Run, source.parent_run_id)
        artifact = db.get(Artifact, aid)
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed bytes")
        with pytest.raises(ValueError):
            verified_result(db, source, root, AgentSettings.model_validate(root.parameters["definition"]))
        assert reference(db, db.get(Message, mid))[1]["inspection"] == "publication_metadata_only"


def data_result(saved, data_environment):
    api = saved[0]
    upload = api.post(
        "/api/data/uploads", files={"file": ("sales.csv", b"Item,Total\nApple,12\nPear,15\n", "text/csv")}
    )
    assert upload.status_code == 201
    step()
    enable(
        saved,
        tools=["python_data"],
        model=data_environment["model"],
        data={"input_artifact_ids": [upload.json()["id"]], "max_repairs": 1},
    )
    data_environment["program_failures"] = 1
    queued = send(saved)
    step()
    for _ in range(22):
        if step() is None:
            break
    message = result(saved, queued["id"])
    assert message["agent_control_run"]["status"] == "succeeded", message
    return message


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_ordinary_worker_data_repair_result_is_available_in_conversation(
    saved, data_environment, monkeypatch, mode
):
    message = data_result(saved, data_environment)
    with session_factory()() as db:
        text, source = reference(db, db.get(Message, message["id"]))
        assert source["available"] and source["family"] == "data"
        assert "The total is 27." in text and "Table preview" in text
        assert source["artifact_id"] and source["sha256"]
    followup(saved, mode=mode)
    step()
    with session_factory()() as db:
        chat = db.scalar(select(Run).where(Run.executor_type == "chat"))
        assert "The total is 27." in str(chat.parameters["messages"])
        assert chat.parameters["agent_result_sources"][0]["family"] == "data"
        assert "workspace_write" not in chat.effective_permissions


@pytest.mark.parametrize("problem", ["bytes", "answer", "parent", "outputs"])
def test_data_context_rejects_changed_report_or_execution_binding(saved, data_environment, problem):
    message = data_result(saved, data_environment)
    with session_factory()() as db:
        source = db.get(Run, message["agent_control_run"]["result_run_id"])
        python = db.get(Run, source.parameters["python_run_id"])
        artifact = db.get(Artifact, source.metadata_json["data_result"]["report_artifact_id"])
        if problem == "bytes":
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed report")
        elif problem == "answer":
            source.metadata_json = {
                **source.metadata_json,
                "data_result": {**source.metadata_json["data_result"], "answer": "Invented999"},
            }
        elif problem == "parent":
            source.parent_run_id = message["run_id"]
        else:
            python.metadata_json = {**python.metadata_json, "output_artifact_ids": []}
        db.commit()
        text, provenance = reference(db, db.get(Message, message["id"]))
        assert not provenance["available"] and "The total is 27." not in text and "Invented999" not in text
