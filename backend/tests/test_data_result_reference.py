"""Result-file references select complete derived bytes rather than old inputs."""

import json

import pytest
from app.api import app
from app.conversation_data_reference import requested_result_file
from app.db import session_factory, utcnow
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_conversation_agent_control import saved as saved
from test_conversation_data import drain, start
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize(
    "text",
    [
        "Sort this result file",
        "Add a column to that output file",
        "Posortuj ten plik wynikowy",
        "Oblicz sumę w tym arkuszu wynikowym",
    ],
)
def test_current_output_file_operation_is_explicit(text):
    assert requested_result_file(text)


@pytest.mark.parametrize(
    "text",
    [
        "Explain this result file",
        "> Sort this result file",
        "Do not sort this result file",
        "Update my project to read this result file",
        "Calculate this result from these data",
    ],
)
def test_other_text_does_not_grant_result_execution(text):
    assert not requested_result_file(text)


def output(root):
    with session_factory()() as db:
        result = db.scalar(
            select(Run)
            .where(
                Run.task_id == root["task_id"],
                Run.executor_type == "agent_data_result",
                Run.status == "succeeded",
            )
            .order_by(Run.created_at.desc())
        )
        return result.metadata_json["data_result"]["result_input_artifact_ids"][0]


@pytest.mark.parametrize("mode", ["chat", "work"])
def test_each_result_continuation_uses_latest_complete_output(data_environment, mode):
    with TestClient(app) as api:
        cid, first = start(api, data_environment, mode)
        original = first["parameters"]["data"]["input_artifact_ids"]
        drain()
        first_output = output(first)
        assert first_output not in original
        response = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={"content": "Add a column to this result file", "execution_mode": mode},
        )
        assert response.status_code == 202, response.text
        second = response.json()
        assert second["parameters"]["data"]["input_artifact_ids"] == [first_output]
        assert second["parameters"]["data_reference"]["use_result_file"] is True
        data_environment.update(
            declared_exports=[],
            exports={
                "result.json": json.dumps(
                    {"answer": "The new total is 55.", "columns": ["Total"], "rows": [["55"]]}
                ).encode(),
                "result.csv": b"Total\n55\n",
            },
        )
        drain()
        second_output = output(second)
        assert second_output != first_output and second_output not in original
        third = api.post(
            "/api/chat/conversations/" + cid + "/messages",
            json={"content": "Sort this result file", "execution_mode": mode},
        )
        assert third.status_code == 202, third.text
        assert third.json()["parameters"]["data"]["input_artifact_ids"] == [second_output]
        drain()
        assert api.get("/api/chat/conversations/" + cid).json()["messages"][-1]["task_status"] == "succeeded"


def test_a_result_remains_usable_after_original_input_goes_to_trash(data_environment):
    with TestClient(app) as api:
        cid, first = start(api, data_environment)
        drain()
        result_id = output(first)
        with session_factory()() as db:
            db.get(Artifact, first["parameters"]["data"]["input_artifact_ids"][0]).trashed_at = utcnow()
            db.commit()
        sent = api.post(
            "/api/chat/conversations/" + cid + "/messages", json={"content": "Sort this result file"}
        )
        assert sent.status_code == 202, sent.text
        assert sent.json()["parameters"]["data"]["input_artifact_ids"] == [result_id]
        drain()
        assert api.get("/api/chat/conversations/" + cid).json()["messages"][-1]["task_status"] == "succeeded"


@pytest.mark.parametrize("change", ["bytes", "trash", "pointer", "inspection"])
def test_unavailable_result_never_falls_back_to_original(data_environment, change):
    with TestClient(app) as api:
        cid, first = start(api, data_environment)
        drain()
        aid = output(first)
        with session_factory()() as db:
            artifact = db.get(Artifact, aid)
            source = db.get(Run, artifact.run_id)
            if change == "bytes":
                from app.config import get_settings

                (get_settings().data_dir / artifact.relative_path).write_bytes(b"Total\n999\n")
            elif change == "trash":
                artifact.trashed_at = utcnow()
            elif change == "pointer":
                source.metadata_json = {
                    **source.metadata_json,
                    "data_result": {
                        **source.metadata_json["data_result"],
                        "result_input_artifact_ids": first["parameters"]["data"]["input_artifact_ids"],
                    },
                }
            else:
                db.get(Run, artifact.metadata_json["data_inspection_run_id"]).status = "failed"
            db.commit()
        before = len(api.get("/api/chat/conversations/" + cid).json()["messages"])
        sent = api.post(
            "/api/chat/conversations/" + cid + "/messages", json={"content": "Sort this result file"}
        )
        assert sent.status_code == 422, sent.text
        assert len(api.get("/api/chat/conversations/" + cid).json()["messages"]) == before


def test_result_from_a_conversation_agent_starts_an_agentless_task(saved, data_environment):
    from test_agent_data_reference import completed

    source = completed(saved, data_environment)
    with session_factory()() as db:
        final = db.get(Run, source["agent_control_run"]["result_run_id"])
        ids = final.metadata_json["data_result"]["result_input_artifact_ids"]
    sent = saved[0].post(
        "/api/chat/conversations/" + saved[1] + "/messages", json={"content": "Sort this result file"}
    )
    assert sent.status_code == 202, sent.text
    assert sent.json()["parameters"]["data"]["input_artifact_ids"] == ids
    assert sent.json()["parameters"]["data_reference"]["use_result_file"] is True
    drain()
    with session_factory()() as db:
        root = db.get(Run, sent.json()["id"])
        assert root.agent_id is None and root.task.agent_id is None
    assert (
        saved[0].get("/api/chat/conversations/" + saved[1]).json()["messages"][-1]["task_status"]
        == "succeeded"
    )


@pytest.mark.parametrize("workbook", [False, True])
def test_complete_result_file_is_selected_with_workbook_preference(data_environment, workbook):
    from app.config import get_settings
    from test_data_output_files import workbook as make_workbook

    if workbook:
        data_environment.update(data_exports=1, exports={"result.xlsx": make_workbook()})
    else:
        data_environment.update(
            declared_exports=[],
            exports={
                "result.json": json.dumps(
                    {
                        "answer": "Created 25 result rows",
                        "columns": ["Total"],
                        "rows": [[str(n)] for n in range(20)],
                    }
                ).encode(),
                "result.csv": ("Total\n" + "\n".join(str(n) for n in range(25)) + "\n").encode(),
            },
        )
    with TestClient(app) as api:
        cid, first = start(api, data_environment)
        drain()
        aid = output(first)
        with session_factory()() as db:
            artifact = db.get(Artifact, aid)
            source = db.get(Run, artifact.run_id)
            data = source.metadata_json["data_result"]
            assert aid == (
                next(item["artifact_id"] for item in data["exports"] if item["filename"] == "result.xlsx")
                if workbook
                else data["download_artifact_id"]
            )
            raw = (get_settings().data_dir / artifact.relative_path).read_bytes()
            if not workbook:
                assert (
                    len(data["rows"]) == 20 and len(raw.splitlines()) == 26 and raw.splitlines()[-1] == b"24"
                )
        sent = api.post(
            "/api/chat/conversations/" + cid + "/messages", json={"content": "Count rows in this result file"}
        )
        assert sent.status_code == 202, sent.text
        assert sent.json()["parameters"]["data"]["input_artifact_ids"] == [aid]
        assert sent.json()["parameters"]["data_inputs"][0]["suffix"] == (".xlsx" if workbook else ".csv")
        drain()
        assert api.get("/api/artifacts/" + aid + "/file").content == raw


def test_changed_result_after_send_fails_before_workspace(data_environment):
    from app.config import get_settings
    from test_conversation_agent_control import step

    with TestClient(app) as api:
        cid, first = start(api, data_environment)
        drain()
        aid = output(first)
        sent = api.post(
            "/api/chat/conversations/" + cid + "/messages", json={"content": "Sort this result file"}
        )
        assert sent.status_code == 202, sent.text
        with session_factory()() as db:
            artifact = db.get(Artifact, aid)
            (get_settings().data_dir / artifact.relative_path).write_bytes(b"Total\nmutated\n")
        step()
        with session_factory()() as db:
            root = db.get(Run, sent.json()["id"])
            assert root.status == "failed"
            assert not db.scalar(select(Run.id).where(Run.parent_run_id == root.id))
