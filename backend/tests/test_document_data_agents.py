"""Document adoption uses immutable complete text in offline Python, bounded model views."""

import json

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_documents import upload_document
from test_agent_research_data import complete, step
from test_agents import create, run_now
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_document_data_agent_receives_complete_text_beyond_legacy_public_source_limit(data_environment):
    api = TestClient(app)
    original = "a" * 180000 + "\nFinal observed numbers: 12 and 15."
    artifact = upload_document(api, original.encode(), "large-observation.txt")
    agent = create(
        api,
        model=data_environment["model"],
        tools=["read_documents", "python_data"],
        documents={"artifact_ids": [artifact["id"]]},
        enabled=True,
    )
    rows = complete(run_now(api, agent))
    final = next(r for r in rows if r.executor_type == "agent_data_result")
    assert final.status == "succeeded", [(r.executor_type, r.status, r.error_message) for r in rows]
    python = next(r for r in rows if r.executor_type == "python")
    assert "network_read" not in python.effective_permissions
    with session_factory()() as s:
        captured = s.get(Artifact, python.parameters["inputs"][0]["artifact_id"])
        assert captured.size_bytes > 128 * 1024
        payload = json.loads((get_settings().data_dir / captured.relative_path).read_bytes())
        assert payload["observations"][0]["result"]["documents"][0]["text"] == original
    serialized = json.dumps(data_environment["model_requests"])
    assert (
        "Final observed numbers" not in serialized
    )  # The model gets excerpts, Python gets the complete file.
    assert len(data_environment["jobs"]) == 1


def test_changed_document_stops_data_handoff_before_model_or_python(data_environment):
    api = TestClient(app)
    artifact = upload_document(api)
    agent = create(
        api,
        model=data_environment["model"],
        tools=["read_documents", "python_data"],
        documents={"artifact_ids": [artifact["id"]]},
        enabled=True,
    )
    parent = run_now(api, agent)
    for _ in range(10):
        step()
        with session_factory()() as s:
            source = s.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_tool")
            )
            if source and source.status == "succeeded":
                break
    else:
        pytest.fail("Document source did not finish")
    (get_settings().data_dir / artifact["relative_path"]).write_bytes(b"Changed source")
    rows = complete(parent)
    assert any(r.status == "failed" for r in rows)
    assert data_environment["calls"] == 0 and not data_environment["jobs"]


def test_local_code_receives_bounded_document_text_without_live_document_access():
    from test_agent_page_coding import children, start

    api = TestClient(app)
    artifact = upload_document(api, b"Reviewed requirement: use a blue heading.")
    _, parent = start(
        api,
        tools=["coding_local", "read_documents"],
        documents={"artifact_ids": [artifact["id"]]},
        fetch_urls=[],
    )
    step()
    published = children(parent["id"])
    source = next(r for r in published if r.parameters.get("tool") == "read_documents")
    handoff = next(r for r in published if r.executor_type == "agent_page_coding")
    assert step() == source.id
    assert step() == handoff.id
    prepared = next(r for r in children(parent["id"]) if r.executor_type == "worktree_prepare")
    assert "use a blue heading" in prepared.parameters["local_coding"]["guidance"]
    assert prepared.parameters["local_coding"]["context_sources"][0]["urls"] == []
    assert api.post("/api/runs/" + parent["id"] + "/cancel").status_code == 200
