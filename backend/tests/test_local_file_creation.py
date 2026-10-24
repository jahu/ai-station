"""Creation from instructions needs explicit intent, never dummy file inputs."""

import pytest
from app.agent_schema import AgentSettings
from app.conversation_data_schema import DataScope
from app.data_schema import AgentDataScope
from pydantic import ValidationError
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_conversation_can_explicitly_create_files_without_uploaded_or_public_inputs():
    scope = DataScope(operation="create")
    assert scope.input_artifact_ids == [] and scope.research is None
    assert scope.files().model_dump(mode="json") == {
        "input_artifact_ids": [],
        "max_repairs": 1,
        "operation": "create",
    }


def test_persistent_agent_can_draft_explicit_file_creation_without_inputs():
    agent = AgentSettings(
        name="Create a workbook",
        goal="Create an XLSX with the integers 1 to 10 and their squares",
        model="auto",
        tools=["python_data"],
        data={"operation": "create", "input_artifact_ids": []},
    )
    assert agent.data.operation == "create" and not agent.enabled


@pytest.mark.parametrize("scope", [AgentDataScope, DataScope])
def test_missing_analysis_inputs_remain_invalid_without_an_explicit_creation_operation(scope):
    with pytest.raises(ValidationError):
        scope.model_validate({"input_artifact_ids": []})


def create(api, state, *, agent=False, goal="Create a CSV table with a Total of 27"):
    if agent:
        response = api.post(
            "/api/agents",
            json={
                "name": "File creator",
                "goal": goal,
                "model": state["model"],
                "tools": ["python_data"],
                "data": {"operation": "create"},
                "enabled": True,
            },
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["data_readiness"]["ready"] and saved["data"]["operation"] == "create"
        response = api.post(
            "/api/agents/" + saved["id"] + "/run", json={"expected_updated_at": saved["updated_at"]}
        )
    else:
        conv = api.post("/api/chat/conversations", json={"model": "unused", "execution_mode": "chat"}).json()
        response = api.post(
            "/api/chat/conversations/" + conv["id"] + "/messages",
            json={"content": goal, "data": {"operation": "create", "model": state["model"]}},
        )
    assert response.status_code == 202, response.text
    return response.json()


def drain(root):
    from app.db import session_factory
    from app.engine import tick
    from app.models import Run
    from sqlalchemy import select

    for _ in range(30):
        with session_factory()() as db:
            if tick(db, "file-creation-worker") is None:
                break
    else:
        raise AssertionError("Queue did not drain")
    with session_factory()() as db:
        return list(db.scalars(select(Run).where(Run.task_id == root["task_id"]).order_by(Run.created_at)))


@pytest.mark.parametrize("agent", [False, True])
def test_creation_uses_existing_worker_empty_input_map_and_verified_exports(data_environment, agent):
    import json

    from app.api import app
    from app.db import session_factory
    from app.models import Artifact
    from fastapi.testclient import TestClient
    from test_data_output_files import chart, workbook

    data_environment.update(data_exports=1, exports={"result.xlsx": workbook(), "chart.png": chart()})
    with TestClient(app) as api:
        root = create(
            api, data_environment, agent=agent, goal="Create an Excel workbook and a chart with a Total of 27"
        )
        rows = drain(root)
        assert all(r.status == "succeeded" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        generation = next(r for r in rows if r.executor_type == "agent_data_generate")
        request = json.loads(generation.parameters["messages"][1]["content"])
        assert (
            request["operation"] == "create"
            and request["inputs"] == []
            and request["runtime"]["input_map"] == {}
        )
        assert "intentionally empty" in generation.parameters["messages"][0]["content"]
        python = next(r for r in rows if r.executor_type == "python")
        assert python.parameters["inputs"] == [] and python.parameters["input_artifact_ids"] == []
        result = next(r for r in rows if r.executor_type == "agent_data_result").metadata_json["data_result"]
        assert result["operation"] == "create" and result["input_artifact_ids"] == []
        assert {x["filename"] for x in result["exports"]} == {"result.xlsx", "chart.png"}
        assert (
            api.get("/api/artifacts/" + result["download_artifact_id"] + "/file").content
            == b"Total\r\n27\r\n"
        )
        with session_factory()() as db:
            script = db.get(Artifact, result["script_artifact_id"])
            assert script.parent_artifact_ids == []
            for output in result["exports"]:
                assert script.id in db.get(Artifact, output["artifact_id"]).parent_artifact_ids
        assert len(data_environment["jobs"]) == 1


def test_bounded_script_repair_retains_empty_scope_and_creation_intent(data_environment):
    import json

    from app.api import app
    from fastapi.testclient import TestClient

    data_environment["program_failures"] = 1
    with TestClient(app) as api:
        rows = drain(create(api, data_environment))
        generations = [r for r in rows if r.executor_type == "agent_data_generate"]
        assert len(generations) == 2 and len(data_environment["jobs"]) == 2
        for r in generations:
            q = json.loads(r.parameters["messages"][1]["content"])
            assert q["operation"] == "create" and q["inputs"] == [] and q["runtime"]["input_map"] == {}
        result = next(
            r for r in rows if r.executor_type == "agent_data_result" and r.metadata_json.get("data_result")
        )
        assert (
            result.metadata_json["data_result"]["operation"] == "create"
            and result.metadata_json["data_result"]["attempt"] == 1
        )


@pytest.mark.parametrize("change", ["operation", "permission", "stop", "expired"])
def test_creation_authority_is_checked_before_python_dispatch(data_environment, change):
    from datetime import timedelta

    from app.api import app
    from app.db import session_factory, utcnow
    from app.engine import tick
    from app.models import Run
    from app.task_control import cancel_task
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    with TestClient(app) as api:
        root = create(api, data_environment)
        for _ in range(15):
            with session_factory()() as db:
                run = db.scalar(
                    select(Run).where(Run.task_id == root["task_id"], Run.executor_type == "python")
                )
                if run:
                    assert run.status == "queued"
                    if change == "operation":
                        scope = run.parameters["agent_data"]
                        definition = scope["definition"]
                        run.parameters = {
                            **run.parameters,
                            "agent_data": {
                                **scope,
                                "definition": {
                                    **definition,
                                    "data": {"input_artifact_ids": [], "operation": "analyze"},
                                },
                            },
                        }
                    elif change == "permission":
                        run.effective_permissions = ["filesystem_read"]
                    elif change == "stop":
                        cancel_task(db, run.task)
                    else:
                        run.parameters = {
                            **run.parameters,
                            "agent_coding_deadline": (utcnow() - timedelta(seconds=1)).isoformat(),
                        }
                    db.commit()
                    break
                tick(db, "creation-prepare")
        else:
            raise AssertionError("No queued Python")
        rows = drain(root)
        assert not data_environment["jobs"]
        assert not any(r.metadata_json.get("data_result") for r in rows)


@pytest.mark.parametrize(
    "value",
    [
        {"operation": "create", "input_artifact_ids": ["00000000-0000-0000-0000-000000000001"]},
        {"operation": "create", "research": {"fetch_urls": ["https://example.com/"]}},
        {"operation": True},
        {"operation": "shell"},
    ],
)
def test_creation_never_silently_drops_inputs_or_adds_sources(value):
    with pytest.raises(ValidationError):
        DataScope.model_validate(value)


def test_creation_defaults_omit_operation_from_legacy_scope_and_agent_identity():
    from uuid import uuid4

    ids = [str(uuid4())]
    plain = AgentDataScope(input_artifact_ids=ids)
    assert plain.model_dump(mode="json") == {"input_artifact_ids": ids, "max_repairs": 1}
    assert DataScope(input_artifact_ids=ids).model_dump(mode="json") == {
        "input_artifact_ids": ids,
        "max_repairs": 1,
        "model": "auto",
        "maximum_runtime": 600,
    }
    with pytest.raises(ValidationError):
        AgentSettings(
            name="No network",
            goal="Create a file",
            tools=["python_data", "web_search"],
            data={"operation": "create"},
        )


@pytest.mark.parametrize(
    "content",
    [
        "Create a CSV table with the numbers 1 to 10 and their squares",
        "Utwórz nowy arkusz Excel z liczbami 1 do 10",
        "Please create a workbook showing a sample monthly budget",
    ],
)
def test_clear_current_file_creation_routes_without_planner_or_web(content):
    from app.chat import MessageBody
    from app.file_creation import prepare_turn

    body = prepare_turn(MessageBody(content=content), "chat")
    assert body.data.operation == "create" and not body.web_search.enabled and body.reasoning is None


@pytest.mark.parametrize(
    "content",
    [
        "Explain how to create an Excel workbook",
        "Create a CSV from those data",
        "Create an Excel from the uploaded file",
        "> Create a CSV table with ten rows",
        "Create an Excel comparing current prices",
        "Create a workbook from https://example.com/",
        "Create a photograph of a workbook",
    ],
)
def test_unclear_source_or_other_capability_does_not_gain_creation(content):
    from app.file_creation import requested

    assert not requested(content)


def test_quick_agent_creation_is_disabled_and_tied_to_current_instructions():
    from app.factory import draft_agent

    draft = draft_agent("Create an agent that creates a CSV table with the integers 1 to 10")
    assert draft.tools == ["python_data"] and draft.data["operation"] == "create" and not draft.enabled
    existing = draft_agent("Create an agent that analyses an uploaded CSV file")
    assert not existing.data or existing.data.get("operation") != "create"


def test_natural_created_workbook_followup_reads_actual_inspected_output(data_environment):
    import json

    from app.api import app
    from fastapi.testclient import TestClient
    from test_data_output_files import workbook

    data_environment.update(data_exports=1, exports={"result.xlsx": workbook()})
    with TestClient(app) as api:
        root = create(api, data_environment, goal="Create an Excel workbook with a Total of 27")
        rows = drain(root)
        result = next(r for r in rows if r.executor_type == "agent_data_result").metadata_json["data_result"]
        created = result["created_input_artifact_ids"]
        assert len(created) == 1
        response = api.post(
            "/api/chat/conversations/" + root["conversation_id"] + "/messages",
            json={"content": "Calculate the total from those data"},
        )
        assert response.status_code == 202, response.text
        followup = response.json()
        assert followup["parameters"]["data"]["input_artifact_ids"] == created
        assert "operation" not in followup["parameters"]["data"]
        assert followup["parameters"]["data_reference"]["created_from_instructions"] is True
        later = drain(followup)
        assert all(r.status == "succeeded" for r in later), [
            (r.executor_type, r.status, r.error_message) for r in later
        ]
        generation = next(r for r in later if r.executor_type == "agent_data_generate")
        q = json.loads(generation.parameters["messages"][1]["content"])
        assert q["inputs"][0]["input_name"] == created[0] + ".xlsx" and "operation" not in q
        assert len(data_environment["jobs"]) == 2


@pytest.mark.parametrize("change", ["trash", "bytes", "pointer"])
def test_created_file_reuse_checks_original_result_and_bytes(data_environment, change):
    from app.api import app
    from app.config import get_settings
    from app.db import session_factory, utcnow
    from app.models import Artifact, Run
    from fastapi.testclient import TestClient

    with TestClient(app) as api:
        root = create(api, data_environment)
        rows = drain(root)
        result = next(r for r in rows if r.executor_type == "agent_data_result")
        with session_factory()() as db:
            stored = db.get(Run, result.id)
            aid = stored.metadata_json["data_result"]["created_input_artifact_ids"][0]
            artifact = db.get(Artifact, aid)
            if change == "trash":
                artifact.trashed_at = utcnow()
            elif change == "bytes":
                (get_settings().data_dir / artifact.relative_path).write_bytes(b"changed")
            else:
                stored.metadata_json = {
                    **stored.metadata_json,
                    "data_result": {**stored.metadata_json["data_result"], "created_input_artifact_ids": []},
                }
            db.commit()
        response = api.post(
            "/api/chat/conversations/" + root["conversation_id"] + "/messages",
            json={"content": "Calculate the total from those data"},
        )
        assert response.status_code == 422, response.text
        assert len(data_environment["jobs"]) == 1


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_natural_first_send_is_durable_and_keeps_external_conversation_model_unused(
    data_environment, monkeypatch, mode
):
    from uuid import uuid4

    from app.api import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        "app.coding_model_routing.select_coding_model", lambda session: {"model": data_environment["model"]}
    )
    body = {
        "client_request_id": str(uuid4()),
        "selection": {"provider": "local-openai-compatible", "model": "unused", "execution_mode": mode},
        "content": "Create a CSV table with a Total of 27",
    }
    with TestClient(app) as api:
        response = api.post("/api/chat/turns", json=body)
        assert response.status_code == 202, response.text
        root = response.json()["run"]
        assert (
            root["parameters"]["data"]["operation"] == "create"
            and not root["parameters"]["web_search"]["enabled"]
        )
        assert "external_ai" not in root["effective_permissions"]
        assert api.post("/api/chat/turns", json=body).json() == response.json()
        rows = drain(root)
        assert any(r.metadata_json.get("data_result", {}).get("operation") == "create" for r in rows), [
            (r.executor_type, r.status, r.error_message) for r in rows
        ]
        assert len(data_environment["jobs"]) == 1


@pytest.mark.parametrize(
    "goal,filename",
    [
        ("Create a spreadsheet with ten rows", "result.xlsx"),
        ("Utwórz nowy arkusz Excel z liczbami 1 do 10", "result.xlsx"),
        ("Create a text file with a weekly checklist", "report.txt"),
        ("Utwórz plik tekstowy z listą zadań", "report.txt"),
    ],
)
def test_requested_creation_file_is_mandatory_even_if_model_omits_its_manifest(goal, filename):
    from app.data_exports import required_exports

    assert filename in required_exports(goal)
