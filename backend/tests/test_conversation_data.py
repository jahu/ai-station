"""Conversation data uses the existing local data/Python graph, with no Agent row."""

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Agent, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def inspected(client):
    uploaded = client.post(
        "/api/data/uploads", files={"file": ("sales.csv", b"Item,Total\nApple,12\nPear,15\n", "text/csv")}
    )
    assert uploaded.status_code == 201, uploaded.text
    with session_factory()() as session:
        assert tick(session, "inspect-data")
    return uploaded.json()["id"]


def start(client, state, mode="chat"):
    aid = inspected(client)
    response = client.post(
        "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": mode}
    )
    assert response.status_code == 201, response.text
    cid = response.json()["id"]
    response = client.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Calculate the total in the selected file.",
            "data": {"input_artifact_ids": [aid], "model": state["model"]},
            "web_search": {"enabled": True},
        },
    )
    assert response.status_code == 202, response.text
    return cid, response.json()


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_one_turn_data_creates_private_workspace_executes_and_returns_a_result_without_an_agent(
    data_environment, mode
):
    state = data_environment
    with TestClient(app) as client:
        cid, parent = start(client, state, mode)
        with session_factory()() as session:
            for _ in range(20):
                if tick(session, "chat-data") is None:
                    break
            else:
                raise AssertionError("Data queue did not drain")
            runs = list(session.scalars(select(Run).where(Run.task_id == parent["task_id"])))
            assert all(run.status == "succeeded" for run in runs), [
                (r.capability, r.status, r.error_message) for r in runs
            ]
            result = next(run for run in runs if run.executor_type == "agent_data_result")
            assert result.metadata_json["data_result"]["answer"] == "The total is 27."
            assert not list(session.scalars(select(Agent)))
            assert all(run.agent_id is None and run.conversation_id == cid for run in runs)
            root = session.get(Run, parent["id"])
            assert "endpoint" not in root.parameters and not root.parameters["web_search"]["enabled"]
            assert result.project_id and result.project_id == root.project_id
        assert state["calls"] == 1 and len(state["jobs"]) == 1


def drain():
    with session_factory()() as session:
        for _ in range(24):
            if tick(session, "conversation-data-check") is None:
                return
    raise AssertionError("Data queue did not drain")


@pytest.mark.parametrize("repair", [False, True])
def test_inline_result_survives_reload_and_reports_only_verified_repairs(data_environment, repair):
    state = data_environment
    state["program_failures"] = int(repair)
    with TestClient(app) as client:
        cid, parent = start(client, state)
        drain()
        messages = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
        result = messages[-1]
        assert result["task_status"] == "succeeded", result
        assert result["created_projects"] == []
        final = next(r for r in result["data_runs"] if r["metadata"].get("data_result"))
        answer = final["metadata"]["data_result"]
        assert answer["answer"] == "The total is 27." and answer["attempt"] == int(repair)
        assert (
            client.get(f"/api/artifacts/{answer['download_artifact_id']}/file").content == b"Total\r\n27\r\n"
        )
        assert (
            client.get(f"/api/artifacts/{answer['input_artifact_ids'][0]}/file").content
            == b"Item,Total\nApple,12\nPear,15\n"
        )
        assert state["calls"] == 1 + int(repair)
        assert not result.get("coding_runs")
        assert result["data_runs"][0]["task_id"] == parent["task_id"]


@pytest.mark.parametrize("phase", ["setup", "model"])
def test_task_stop_prevents_later_model_and_python_dispatch(data_environment, phase):
    state = data_environment
    with TestClient(app) as client:
        cid, parent = start(client, state)
        with session_factory()() as session:
            assert tick(session, "publish") == parent["id"]
            if phase == "model":
                for _ in range(8):
                    queued = session.scalar(
                        select(Run).where(
                            Run.task_id == parent["task_id"], Run.executor_type == "agent_data_generate"
                        )
                    )
                    if queued:
                        break
                    assert tick(session, "prepare")
                else:
                    raise AssertionError("No model preparation")
        response = client.post(f"/api/chat/conversations/{cid}/tasks/{parent['task_id']}/cancel")
        assert response.status_code == 200, response.text
        drain()
        assert not state["calls"] and not state["jobs"]
        result = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert result["task_status"] == "canceled"
        assert not any(r["metadata"].get("data_result") for r in result["data_runs"])


@pytest.mark.parametrize("mutation", ["origin", "permissions", "deadline", "inputs", "project"])
def test_altered_conversation_authority_cannot_generate_or_execute(data_environment, mutation):
    from datetime import timedelta

    from app.db import utcnow

    state = data_environment
    with TestClient(app) as client:
        _, parent = start(client, state)
        with session_factory()() as session:
            for _ in range(8):
                workflow = session.scalar(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_workflow")
                )
                if workflow:
                    break
                assert tick(session, "private-workspace")
            else:
                raise AssertionError("No private workflow")
            if mutation == "origin":
                workflow.parameters = {**workflow.parameters, "conversation_data_origin": {}}
            elif mutation == "permissions":
                workflow.effective_permissions = [*workflow.effective_permissions, "external_ai"]
            elif mutation == "deadline":
                workflow.parameters = {
                    **workflow.parameters,
                    "agent_coding_deadline": (utcnow() + timedelta(hours=1)).isoformat(),
                }
            elif mutation == "inputs":
                workflow.parameters = {**workflow.parameters, "data_inputs": []}
            else:
                workflow.project_id = None
            session.commit()
        drain()
        assert state["calls"] == 0 and not state["jobs"]
        with session_factory()() as session:
            assert session.get(Run, workflow.id).status == "failed"


@pytest.mark.parametrize(
    "extra",
    [
        {"action": "image.generate"},
        {"attachments": [{"name": "secret.txt", "content": "not shared"}]},
        {"web_search": {"enabled": True, "query": "precise research"}},
        {"web_search": {"enabled": True, "render_pages": True}},
        {"data_override": {"model": "cloud-model"}},
        {"data_override": {"maximum_runtime": 3601}},
        {"data_override": {"command": "python arbitrary.py"}},
    ],
)
def test_rejects_mixed_scope_or_unreviewed_executor_fields_without_enqueuing(data_environment, extra):
    from copy import deepcopy

    state = data_environment
    extra = deepcopy(extra)
    with TestClient(app) as client:
        aid = inspected(client)
        cid = client.post(
            "/api/chat/conversations", json={"model": "not-running", "execution_mode": "chat"}
        ).json()["id"]
        overrides = extra.pop("data_override", {})
        body = {"content": "Analyse this file", "data": {"input_artifact_ids": [aid], **overrides}, **extra}
        response = client.post(f"/api/chat/conversations/{cid}/messages", json=body)
        assert response.status_code == 422, response.text
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []
        assert not state["calls"] and not state["jobs"]


def test_first_send_receipt_replay_does_not_duplicate_analysis(data_environment):
    from uuid import uuid4

    state = data_environment
    with TestClient(app) as client:
        aid = inspected(client)
        body = {
            "client_request_id": str(uuid4()),
            "selection": {"model": "not-running", "execution_mode": "chat"},
            "execution_mode": "chat",
            "content": "Total the sales",
            "action": "data.analyze",
            "data": {"input_artifact_ids": [aid], "model": state["model"]},
        }
        first = client.post("/api/chat/turns", json=body)
        assert first.status_code == 202, first.text
        assert client.post("/api/chat/turns", json=body).json() == first.json()
        changed = client.post("/api/chat/turns", json={**body, "data": {**body["data"], "max_repairs": 0}})
        assert changed.status_code == 409, changed.text
        drain()
        assert state["calls"] == 1 and len(state["jobs"]) == 1


def test_failed_result_contract_stays_failed_after_repair_budget(data_environment):
    state = data_environment
    state["bad_report"] = True
    with TestClient(app) as client:
        cid, _ = start(client, state)
        drain()
        result = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert result["task_status"] == "failed"
        assert not any(run["metadata"].get("data_result") for run in result["data_runs"])
        assert state["calls"] == 2 and len(state["jobs"]) == 2


@pytest.mark.parametrize("change", ["uninspected", "trashed", "bytes"])
def test_invalid_original_never_publishes_workspace(data_environment, change):
    from app.config import get_settings
    from app.db import utcnow
    from app.models import Artifact

    state = data_environment
    with TestClient(app) as client:
        aid = inspected(client)
        with session_factory()() as session:
            artifact = session.get(Artifact, aid)
            if change == "uninspected":
                artifact.metadata_json = {**artifact.metadata_json, "data_inspection_run_id": None}
            elif change == "trashed":
                artifact.trashed_at = utcnow()
            else:
                (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed\n999\n")
            session.commit()
        cid = client.post(
            "/api/chat/conversations", json={"model": "not-running", "execution_mode": "chat"}
        ).json()["id"]
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Calculate total",
                "data": {"input_artifact_ids": [aid], "model": state["model"]},
            },
        )
        if change == "bytes":
            # HTTP freezes metadata and enqueues. The worker verifies actual bytes
            # before it can publish setup, preserving the execution boundary.
            assert response.status_code == 202, response.text
            drain()
            with session_factory()() as session:
                assert session.get(Run, response.json()["id"]).status == "failed"
        else:
            assert response.status_code == 422, response.text
        with session_factory()() as session:
            assert not list(session.scalars(select(Run).where(Run.executor_type == "project_setup")))
        assert not state["calls"] and not state["jobs"]


def test_selected_file_followup_stays_in_conversation_and_uses_a_new_private_task(data_environment):
    state = data_environment
    with TestClient(app) as client:
        cid, first = start(client, state)
        drain()
        with session_factory()() as session:
            root = session.get(Run, first["id"])
            scope = root.parameters["data"]
            first_project = root.project_id
        second = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Recheck the total in this file.",
                "data": scope,
            },
        )
        assert second.status_code == 202, second.text
        assert second.json()["task_id"] != first["task_id"]
        drain()
        with session_factory()() as session:
            root = session.get(Run, second.json()["id"])
            assert root.project_id and root.project_id != first_project
            assert not list(session.scalars(select(Agent)))
        messages = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
        answers = [message for message in messages if message.get("data_runs")]
        assert len(answers) == 2 and all(message["task_status"] == "succeeded" for message in answers)
        assert state["calls"] == 2 and len(state["jobs"]) == 2
