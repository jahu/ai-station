"""Natural data follow-ups freeze a new local task rather than rerunning an agent."""

import json
from datetime import timedelta

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Agent, Artifact, Message, Run
from app.paths import safe_join
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agent_research_data import sources as sources
from test_conversation_agent_control import enable, result, send, step
from test_conversation_agent_control import saved as saved
from test_conversation_data import drain, start
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment

DEFAULTS = {"auto_install_dependencies": True, "auto_validate": True}


def completed(saved, state, *, create=False, input_count=1, **extra):
    api = saved[0]
    data = {"max_repairs": 1}
    if create:
        data["operation"] = "create"
    elif input_count:
        ids = []
        for index in range(input_count):
            upload = api.post(
                "/api/data/uploads",
                files={"file": (f"sales-{index}.csv", b"Item,Total\nApple,12\nPear,15\n", "text/csv")},
            )
            assert upload.status_code == 201
            step()
            ids.append(upload.json()["id"])
        data["input_artifact_ids"] = ids
        state["program_failures"] = 1
    enable(
        saved,
        **{
            "tools": ["python_data"],
            "goal": "Calculate the total",
            "model": state["model"],
            "data": data,
            **extra,
        },
    )
    queued = send(saved)
    step()
    for _ in range(30):
        if step() is None:
            break
    view = result(saved, queued["id"])
    assert view["agent_control_run"]["status"] == "succeeded", view
    return view


def follow(saved, *, mode="work", content="Sort this file by Total", **extra):
    return saved[0].post(
        f"/api/chat/conversations/{saved[1]}/messages",
        json={
            "content": content,
            "execution_mode": mode,
            **({"project_defaults": DEFAULTS} if mode == "work" else {}),
            **extra,
        },
    )


@pytest.mark.parametrize("mode", ["chat", "work"])
@pytest.mark.parametrize("content", ["Calculate the average in this file", "Add a column Sum to this file"])
def test_agent_inputs_start_a_separate_local_task_with_no_agent_or_network_scope(
    saved, data_environment, mode, content
):
    source = completed(saved, data_environment)
    with session_factory()() as db:
        old = db.get(Run, source["agent_control_run"]["result_run_id"])
        ids = old.metadata_json["data_result"]["input_artifact_ids"]
        old_agent_time = db.get(Agent, saved[2]).last_run_at
        artifact = db.get(Artifact, ids[0])
        original = safe_join(get_settings().data_dir, artifact.relative_path).read_bytes()
    sent = follow(saved, mode=mode, content=content)
    assert sent.status_code == 202, sent.text
    queued = sent.json()
    assert queued["task_id"] != source["agent_control_run"]["task_id"]
    assert queued["parameters"]["data"]["input_artifact_ids"] == ids
    assert queued["parameters"]["project_defaults"] is None
    assert queued["parameters"]["data_reference"]["source_kind"] == "agent_data_inputs"
    # The existing local generation contract includes network_read for inference;
    # it does not authorize a new research tool or network access in Python.
    from app.conversation_data import required_permissions
    from app.conversation_data_schema import DataScope

    scope = DataScope.model_validate(queued["parameters"]["data"])
    assert set(queued["effective_permissions"]) == set(required_permissions(scope))
    assert scope.context_tools() == []
    assert not {
        "network_external",
        "email_send",
        "external_ai",
        "browser",
        "http_connector_read",
    }.intersection(queued["effective_permissions"])
    for _ in range(25):
        if step() is None:
            break
    with session_factory()() as db:
        root = db.get(Run, queued["id"])
        assert root.agent_id is None and root.task.agent_id is None
        assert db.get(Agent, saved[2]).last_run_at == old_agent_time
        assert (
            len(
                list(
                    db.scalars(
                        select(Run).where(
                            Run.agent_id == saved[2],
                            Run.parent_run_id.is_(None),
                            Run.executor_type == "agent_workflow",
                        )
                    )
                )
            )
            == 1
        )
        assert (
            safe_join(get_settings().data_dir, db.get(Artifact, ids[0]).relative_path).read_bytes()
            == original
        )
        final = db.scalar(
            select(Run)
            .where(Run.task_id == root.task_id, Run.executor_type == "agent_data_result")
            .order_by(Run.created_at.desc())
        )
        assert final.status == "succeeded", final.error_message
        assert final.metadata_json["data_result"]["input_artifact_ids"] == ids
        from app.python_execution import PERMISSIONS

        python = db.get(Run, final.parameters["python_run_id"])
        assert set(python.effective_permissions) == set(PERMISSIONS)
        assert not db.scalar(
            select(Run.id).where(
                Run.task_id == root.task_id,
                Run.executor_type.in_(["agent_tool", "agent_page_coding"]),
            )
        )
    payload = data_environment["model_requests"][-1]["messages"][1]["content"]
    assert content in payload and "The total is 27." in payload


def test_default_work_project_configuration_does_not_block_ordinary_data_reference(data_environment):
    with TestClient(app) as api:
        cid, first = start(api, data_environment, "work")
        drain()
        sent = api.post(
            f"/api/chat/conversations/{cid}/messages",
            json={
                "content": "Sort this file by Total",
                "execution_mode": "work",
                "project_defaults": DEFAULTS,
            },
        )
        assert sent.status_code == 202, sent.text
        assert sent.json()["parameters"]["data_reference"]["run_id"] == first["id"]
        assert sent.json()["parameters"]["project_defaults"] is None


@pytest.mark.parametrize(
    "problem",
    [
        "bytes",
        "snapshot",
        "report",
        "python",
        "workflow",
        "workflow_inputs",
        "project",
        "task",
        "scope",
        "permission",
        "partial",
    ],
)
def test_changed_agent_data_cannot_fall_back_or_start_new_work(saved, data_environment, problem):
    source = completed(saved, data_environment)
    with session_factory()() as db:
        control = db.get(Run, source["run_id"])
        final = db.get(Run, source["agent_control_run"]["result_run_id"])
        python = db.get(Run, final.parameters["python_run_id"])
        artifact = db.get(Artifact, final.metadata_json["data_result"]["input_artifact_ids"][0])
        if problem == "bytes":
            safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed")
        elif problem == "snapshot":
            final.parameters = {
                **final.parameters,
                "agent_data": {**final.parameters["agent_data"], "data_inputs": []},
            }
        elif problem == "report":
            final.metadata_json = {
                **final.metadata_json,
                "data_result": {**final.metadata_json["data_result"], "answer": "Invented"},
            }
        elif problem == "python":
            python.metadata_json = {**python.metadata_json, "process_confirmed_gone": False}
        elif problem == "workflow":
            final.parameters = {
                **final.parameters,
                "agent_data": {**final.parameters["agent_data"], "workflow_run_id": control.id},
            }
        elif problem == "workflow_inputs":
            workflow = db.get(Run, final.parameters["agent_data"]["workflow_run_id"])
            workflow.parameters = {**workflow.parameters, "data_inputs": []}
        elif problem == "project":
            python.project_id = None
        elif problem == "task":
            final.task_id = control.task_id
        elif problem == "scope":
            control.parameters = {**control.parameters, "scope": {}}
        elif problem == "permission":
            control.effective_permissions = []
        else:
            db.get(Message, source["id"]).metadata_json = {
                **db.get(Message, source["id"]).metadata_json,
                "partial": True,
            }
        db.commit()
    before = len(saved[0].get(f"/api/chat/conversations/{saved[1]}").json()["messages"])
    sent = follow(saved)
    assert sent.status_code == 422, sent.text
    assert len(saved[0].get(f"/api/chat/conversations/{saved[1]}").json()["messages"]) == before


def test_change_after_send_is_rejected_before_creating_a_new_workspace(saved, data_environment):
    source = completed(saved, data_environment)
    sent = follow(saved)
    assert sent.status_code == 202, sent.text
    with session_factory()() as db:
        final = db.get(Run, source["agent_control_run"]["result_run_id"])
        artifact = db.get(Artifact, final.metadata_json["data_result"]["input_artifact_ids"][0])
        safe_join(get_settings().data_dir, artifact.relative_path).write_bytes(b"changed after Send")
    step()
    with session_factory()() as db:
        root = db.get(Run, sent.json()["id"])
        assert root.status == "failed" and not list(
            db.scalars(select(Run).where(Run.parent_run_id == root.id))
        )


def test_completed_expired_agent_inputs_remain_readable_without_renewing_the_old_job(saved, data_environment):
    source = completed(saved, data_environment)
    past = (utcnow() - timedelta(hours=2)).isoformat()
    with session_factory()() as db:
        for row in db.scalars(select(Run).where(Run.task_id == source["agent_control_run"]["task_id"])):
            if "agent_coding_deadline" in row.parameters:
                row.parameters = {**row.parameters, "agent_coding_deadline": past}
        db.get(Agent, saved[2]).enabled = False
        db.commit()
    sent = follow(saved)
    assert sent.status_code == 202, sent.text
    for _ in range(25):
        if step() is None:
            break
    assert saved[0].get("/api/runs/" + sent.json()["id"]).json()["status"] == "succeeded"


@pytest.mark.parametrize("workbook", [False, True])
def test_created_agent_file_reuses_complete_inspected_download_not_table_preview(
    saved, data_environment, workbook
):
    from test_data_output_files import workbook as make_workbook

    if workbook:
        data_environment.update(data_exports=1, exports={"result.xlsx": make_workbook()})
    else:
        preview = {"answer": "Created 25 rows", "columns": ["Total"], "rows": [[str(n)] for n in range(20)]}
        data_environment.update(
            exports={
                "result.json": json.dumps(preview).encode(),
                "result.csv": ("Total\n" + "\n".join(str(n) for n in range(25)) + "\n").encode(),
            },
            declared_exports=[],
        )
    source = completed(saved, data_environment, create=True)
    with session_factory()() as db:
        final = db.get(Run, source["agent_control_run"]["result_run_id"])
        ids = final.metadata_json["data_result"]["created_input_artifact_ids"]
        artifact = db.get(Artifact, ids[0])
        original = safe_join(get_settings().data_dir, artifact.relative_path).read_bytes()
        assert artifact.original_filename == ("result.xlsx" if workbook else "result.csv")
        if not workbook:
            assert len(final.metadata_json["data_result"]["rows"]) == 20
            assert len(original.splitlines()) == 26 and original.splitlines()[-1] == b"24"
    sent = follow(saved, content="Count rows in this file")
    assert sent.status_code == 202, sent.text
    params = sent.json()["parameters"]
    assert params["data"]["input_artifact_ids"] == ids
    assert params["data"].get("operation", "analyze") == "analyze"
    assert params["data_reference"]["created_from_instructions"] is True
    drain()
    detail = saved[0].get("/api/chat/conversations/" + saved[1]).json()
    assert detail["messages"][-1]["task_status"] == "succeeded", detail["messages"][-1]
    assert saved[0].get("/api/artifacts/" + ids[0] + "/file").content == original


@pytest.mark.parametrize("kind", ["public", "document"])
def test_agent_captured_sources_are_reused_offline_without_refetching(saved, data_environment, sources, kind):
    from test_agent_documents import upload_document

    extra = {"tools": ["python_data", "http_fetch"], "fetch_urls": ["https://data.example.com/numbers"]}
    if kind == "document":
        from app.agent_documents import reviewed_scope
        from app.document_schema import AgentDocumentScope

        upload = upload_document(saved[0], b"Observed values: 12 and 15.")
        with session_factory()() as db:
            reviewed = reviewed_scope(db, AgentDocumentScope(artifact_ids=[upload["id"]]), freeze=True)
        extra = {"tools": ["python_data", "read_documents"], "documents": reviewed.model_dump(mode="json")}
    source = completed(saved, data_environment, input_count=0, **extra)
    with session_factory()() as db:
        result_run = db.get(Run, source["agent_control_run"]["result_run_id"])
        ids = result_run.metadata_json["data_result"]["input_artifact_ids"]
        assert len(ids) == 1
    previous_fetches = list(sources["fetch"])
    sent = follow(saved, content="Calculate the average from these data")
    assert sent.status_code == 202, sent.text
    params = sent.json()["parameters"]
    assert params["data"]["input_artifact_ids"] == ids
    assert params["data_reference"]["captured_sources"][0]["artifact_id"] == ids[0]
    assert params["data"].get("research") is None and params["data"].get("documents") is None
    drain()
    assert (
        saved[0].get("/api/chat/conversations/" + saved[1]).json()["messages"][-1]["task_status"]
        == "succeeded"
    )
    assert sources["fetch"] == previous_fetches and not sources["search"]


def test_several_agent_inputs_require_group_or_explicit_selection(saved, data_environment):
    completed(saved, data_environment, input_count=2)
    assert follow(saved).status_code == 422
    selected = follow(saved, content="Sort these input files by Total")
    assert selected.status_code == 202, selected.text
    assert len(selected.json()["parameters"]["data"]["input_artifact_ids"]) == 2
    drain()


@pytest.mark.parametrize(
    "text",
    [
        'Explain "Add a column to this file"',
        "> Sort this file",
        "Do not edit this file",
        "Update my project to import this file",
    ],
)
def test_non_current_operations_do_not_select_agent_data(text):
    from app.conversation_data_reference import requested

    assert not requested(text)


def test_latest_failed_data_agent_never_reuses_an_older_success(saved, data_environment):
    completed(saved, data_environment)
    data_environment["bad_report"] = True
    queued = send(saved)
    drain()
    assert result(saved, queued["id"])["agent_control_run"]["status"] == "failed"
    sent = follow(saved)
    assert sent.status_code == 422, sent.text
