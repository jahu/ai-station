from datetime import timedelta
from uuid import uuid4

import pytest
from app.api import app
from app.conversation_data_reference import requested
from app.db import session_factory, utcnow
from app.models import Artifact, Message, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_data import drain, inspected, start
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize(
    "content",
    [
        "Policz średnią z tych danych",
        "A teraz oblicz sumę w tym pliku",
        "Calculate the average from these data",
        "Count the rows in this file",
        "Please compare these input files",
        "Jaka jest suma w tym arkuszu?",
        "Could you calculate the average from these data?",
        "Czy możesz policzyć średnią z tych danych?",
    ],
)
def test_only_current_direct_data_references_select_analysis(content):
    assert requested(content)


@pytest.mark.parametrize(
    "content",
    [
        'Co oznacza "Policz średnią z tych danych"?',
        '"Calculate the average from these data"',
        "> Calculate the average from these data",
        "```\nCalculate the average from these data\n```",
        "Do not calculate the average from these data",
        "What is an Excel spreadsheet?",
        "Calculate the average",
        "Explain the previous result",
        "Calculate this result from these data",
    ],
)
def test_quotes_unrelated_chat_and_output_references_do_not_grant_python(content):
    assert not requested(content)


def follow(client, cid, **extra):
    return client.post(
        f"/api/chat/conversations/{cid}/messages",
        json={
            "content": "Policz średnią z tych danych",
            "web_search": {"enabled": True},
            **extra,
        },
    )


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_natural_followup_reuses_exact_original_inputs_in_a_new_local_task(data_environment, mode):
    state = data_environment
    with TestClient(app) as client:
        cid, first = start(client, state, mode)
        drain()
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        second = response.json()
        assert second["task_id"] != first["task_id"]
        with session_factory()() as session:
            original = session.get(Run, first["id"])
            root = session.get(Run, second["id"])
            assert root.parameters["data_inputs"] == original.parameters["data_inputs"]
            assert root.parameters["data"] == original.parameters["data"]
            assert root.parameters["data_reference"]["run_id"] == original.id
            assert not root.parameters["web_search"]["enabled"]
            assert "endpoint" not in root.parameters and "external_ai" not in root.effective_permissions
        drain()
        messages = client.get(f"/api/chat/conversations/{cid}").json()["messages"]
        user = next(m for m in messages if m["run_id"] == second["id"] and m["role"] == "user")
        assert user["metadata"]["conversation_reference"]["filenames"] == ["sales.csv"]
        assert messages[-1]["task_status"] == "succeeded"
        assert state["calls"] == 2 and len(state["jobs"]) == 2
        payload = state["model_requests"][-1]["messages"][1]["content"]
        assert "Calculate the total in the selected file." in payload
        assert "The total is 27." in payload


def test_completed_expired_source_can_be_reused_without_extending_its_budget(data_environment):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        past = (utcnow() - timedelta(hours=2)).isoformat()
        with session_factory()() as session:
            for row in session.scalars(select(Run).where(Run.task_id == first["task_id"])):
                if "agent_coding_deadline" in row.parameters:
                    row.parameters = {**row.parameters, "agent_coding_deadline": past}
            session.commit()
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        drain()
        with session_factory()() as session:
            assert session.get(Run, first["id"]).parameters["agent_coding_deadline"] == past
            assert session.get(Run, response.json()["id"]).parameters["agent_coding_deadline"] != past
        assert data_environment["calls"] == 2


@pytest.mark.parametrize("mutation", ["origin", "workflow", "inputs", "result", "python", "trash", "failed"])
def test_latest_unverified_source_never_falls_back_or_launches_new_work(data_environment, mutation):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        with session_factory()() as session:
            root = session.get(Run, first["id"])
            if mutation == "origin":
                root.parameters = {**root.parameters, "user_message_id": str(uuid4())}
            elif mutation == "workflow":
                root.metadata_json = {**root.metadata_json, "data_workflow_run_id": str(uuid4())}
            elif mutation == "inputs":
                root.parameters = {**root.parameters, "data_inputs": []}
            elif mutation in {"result", "python"}:
                result = session.scalar(
                    select(Run).where(Run.task_id == root.task_id, Run.executor_type == "agent_data_result")
                )
                if mutation == "result":
                    result.metadata_json = {
                        **result.metadata_json,
                        "data_result": {
                            **result.metadata_json["data_result"],
                            "input_artifact_ids": [str(uuid4())],
                        },
                    }
                else:
                    python = session.get(Run, result.parameters["python_run_id"])
                    python.metadata_json = {**python.metadata_json, "process_confirmed_gone": False}
            elif mutation == "trash":
                session.get(Artifact, root.parameters["data_inputs"][0]["artifact_id"]).trashed_at = utcnow()
            else:
                root.status = "failed"
            session.commit()
        response = follow(client, cid)
        assert response.status_code == 422, response.text
        assert data_environment["calls"] == 1 and len(data_environment["jobs"]) == 1


def test_newer_attachment_is_a_barrier_to_reusing_an_older_dataset(data_environment):
    with TestClient(app) as client:
        cid, _ = start(client, data_environment)
        drain()
        with session_factory()() as session:
            session.add(
                Message(
                    conversation_id=cid,
                    role="user",
                    content="A new photo",
                    metadata_json={"images": [{"id": str(uuid4())}]},
                )
            )
            session.commit()
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"].get("data")
        assert "python_execute" not in response.json()["effective_permissions"]
        assert data_environment["calls"] == 1


def test_source_bytes_changed_after_send_fail_before_a_new_workspace_or_model(data_environment):
    from app.config import get_settings

    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            artifact = session.get(Artifact, root.parameters["data_inputs"][0]["artifact_id"])
            (get_settings().data_dir / artifact.relative_path).write_bytes(b"Changed source")
        drain()
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            assert root.status == "failed" and root.project_id is None
        assert data_environment["calls"] == 1 and len(data_environment["jobs"]) == 1


def test_explicit_selected_files_override_implicit_reference(data_environment):
    with TestClient(app) as client:
        cid, _ = start(client, data_environment)
        drain()
        aid = inspected(client)
        response = follow(client, cid, data={"input_artifact_ids": [aid], "model": data_environment["model"]})
        assert response.status_code == 202, response.text
        assert response.json()["parameters"]["data"]["input_artifact_ids"] == [aid]
        assert "data_reference" not in response.json()["parameters"]


def test_two_natural_followups_remain_bounded_and_use_the_latest_completed_source(data_environment):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        second = follow(client, cid)
        assert second.status_code == 202, second.text
        drain()
        third = follow(client, cid, content="Teraz oblicz sumę w tym pliku")
        assert third.status_code == 202, third.text
        assert third.json()["parameters"]["data_reference"]["run_id"] == second.json()["id"]
        assert len(third.json()["parameters"]["data_reference"]["context"]) <= 6000
        assert first["id"] not in third.json()["parameters"]["data_reference"]["context"]
        drain()
        assert data_environment["calls"] == 3 and len(data_environment["jobs"]) == 3


@pytest.mark.parametrize(
    "content,accepted",
    [
        ("Calculate the average from these input files", True),
        ("Calculate the average from these   input files", True),
        ("Calculate the average in this file", False),
        ('Calculate the average in this file, quoted text says "these files"', False),
    ],
)
def test_multiple_inputs_require_an_unquoted_group_reference(data_environment, content, accepted):
    with TestClient(app) as client:
        ids = [inspected(client), inspected(client)]
        conversation = client.post(
            "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": "chat"}
        ).json()
        cid = conversation["id"]
        first = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Calculate the total from these selected files",
                "data": {"input_artifact_ids": ids, "model": data_environment["model"]},
            },
        )
        assert first.status_code == 202, first.text
        drain()
        response = follow(client, cid, content=content)
        assert response.status_code == (202 if accepted else 422), response.text
        if accepted:
            assert response.json()["parameters"]["data"]["input_artifact_ids"] == ids
            drain()
            assert data_environment["calls"] == 2
        else:
            assert data_environment["calls"] == 1


def test_a_foreign_conversation_has_no_implicit_file_scope(data_environment):
    with TestClient(app) as client:
        _, _ = start(client, data_environment)
        drain()
        other = client.post(
            "/api/chat/conversations", json={"model": "external-not-used", "execution_mode": "chat"}
        ).json()
        response = follow(client, other["id"])
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"].get("data")
        assert "python_execute" not in response.json()["effective_permissions"]
        assert data_environment["calls"] == 1


def test_latest_failed_analysis_blocks_fallback_to_older_success(data_environment):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        with session_factory()() as session:
            scope = dict(session.get(Run, first["id"]).parameters["data"])
        latest = follow(client, cid, content="Check the total again", data=scope)
        assert latest.status_code == 202
        with session_factory()() as session:
            session.get(Run, latest.json()["id"]).status = "failed"
            session.commit()
        response = follow(client, cid)
        assert response.status_code == 422, response.text
        assert data_environment["calls"] == 1


@pytest.mark.parametrize("mutation", ["reference", "message", "old_origin"])
def test_queued_reference_tampering_fails_before_workspace_or_inference(data_environment, mutation):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            if mutation == "reference":
                root.parameters = {
                    **root.parameters,
                    "data_reference": {**root.parameters["data_reference"], "context": "Injected context"},
                }
            elif mutation == "message":
                user = session.get(Message, root.parameters["user_message_id"])
                user.metadata_json = {
                    key: value for key, value in user.metadata_json.items() if key != "conversation_reference"
                }
            else:
                old = session.get(Run, first["id"])
                old.parameters = {**old.parameters, "user_message_id": str(uuid4())}
            session.commit()
        drain()
        with session_factory()() as session:
            root = session.get(Run, response.json()["id"])
            assert root.status == "failed" and root.project_id is None
        assert data_environment["calls"] == 1 and len(data_environment["jobs"]) == 1


@pytest.mark.parametrize(
    "override", [{"action": "chat"}, {"web_search": {"enabled": True, "query": "public data"}}]
)
def test_explicit_chat_or_exact_web_scope_keeps_its_own_execution(data_environment, override):
    with TestClient(app) as client:
        cid, _ = start(client, data_environment)
        drain()
        response = follow(client, cid, **override)
        assert response.status_code == 202, response.text
        assert not response.json()["parameters"].get("data")
        assert "python_execute" not in response.json()["effective_permissions"]


def test_receipt_replay_keeps_original_scope_after_input_changes_and_stop_prevents_work(data_environment):
    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        conversation = client.get(f"/api/chat/conversations/{cid}").json()
        body = {
            "client_request_id": str(uuid4()),
            "conversation_id": cid,
            "expected_settings_version": conversation["settings_version"],
            "content": "Calculate the average from these data",
        }
        accepted = client.post("/api/chat/turns", json=body)
        assert accepted.status_code == 202, accepted.text
        root = accepted.json()["run"]
        with session_factory()() as session:
            source = session.get(Run, first["id"])
            session.get(Artifact, source.parameters["data_inputs"][0]["artifact_id"]).trashed_at = utcnow()
            session.commit()
        replay = client.post("/api/chat/turns", json=body)
        assert replay.status_code == 202 and replay.json()["run"]["id"] == root["id"]
        stopped = client.post(f"/api/chat/conversations/{cid}/tasks/{root['task_id']}/cancel")
        assert stopped.status_code == 200, stopped.text
        drain()
        assert data_environment["calls"] == 1 and len(data_environment["jobs"]) == 1


def test_quoted_context_is_valid_bounded_json_with_explicit_truncation():
    import json

    from app.conversation_data_reference import quoted_context

    value = quoted_context("a" * 16000, "\u0001" * 8000)
    assert len(value) <= 6000 and json.loads(value)["truncated"]


@pytest.mark.parametrize("bound", [False, True])
def test_bound_work_task_wins_and_an_empty_context_does_not_break_data_reuse(data_environment, bound):
    from app.chat import MessageBody
    from app.conversation_data_reference import resolve
    from app.models import ChatWorkContext, Conversation

    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        body = MessageBody(content="Calculate the average from these data")
        with session_factory()() as session:
            session.add(ChatWorkContext(conversation_id=cid, task_id=first["task_id"] if bound else None))
            session.flush()
            selected, reference = resolve(session, session.get(Conversation, cid), body, "work")
            if bound:
                assert selected is body and reference is None
            else:
                assert selected.data is not None and reference["run_id"] == first["id"]


def test_completed_legacy_definition_defaults_are_readable_but_execution_stays_strict(data_environment):
    from app.conversation_data import validate_workflow

    with TestClient(app) as client:
        cid, first = start(client, data_environment)
        drain()
        with session_factory()() as session:
            root = session.get(Run, first["id"])
            workflow = session.get(Run, root.metadata_json["data_workflow_run_id"])
            for row in session.scalars(select(Run).where(Run.task_id == root.task_id)):
                values = dict(row.parameters)
                if "definition" in values:
                    values["definition"] = {
                        k: v for k, v in values["definition"].items() if k != "schedule_timezone"
                    }
                if "agent_data" in values:
                    scope = dict(values["agent_data"])
                    scope["definition"] = {
                        k: v for k, v in scope["definition"].items() if k != "schedule_timezone"
                    }
                    values["agent_data"] = scope
                row.parameters = values
            session.commit()
            with pytest.raises(ValueError, match="changed its original authority"):
                validate_workflow(session, workflow)
        response = follow(client, cid)
        assert response.status_code == 202, response.text
        drain()
        assert data_environment["calls"] == 2 and len(data_environment["jobs"]) == 2


@pytest.mark.parametrize(
    "content",
    [
        "Calculate the average in this file: https://example.com/data.csv",
        "Analyze this file from akademia.ai",
    ],
)
def test_current_network_target_does_not_reuse_an_old_local_dataset(data_environment, content):
    from app.chat import MessageBody
    from app.conversation_data_reference import resolve
    from app.models import Conversation

    with TestClient(app) as client:
        cid, _ = start(client, data_environment)
        drain()
        body = MessageBody(content=content)
        with session_factory()() as session:
            selected, reference = resolve(session, session.get(Conversation, cid), body, "chat")
            assert selected is body and reference is None
