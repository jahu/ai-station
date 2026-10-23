import pytest
from app.api import app
from app.db import session_factory
from app.models import Artifact, Run
from app.python_execution import PythonParameters
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_conversation_data import drain, start
from test_data_output_files import chart, workbook
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create, finish
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize(
    "optional", [["../file"], ["/file"], ["same", "same"], ["required"], [f"x{i}" for i in range(8)]]
)
def test_control_plane_validates_optional_scope_independently(optional):
    with pytest.raises(ValidationError):
        PythonParameters(
            worktree_id="00000000-0000-0000-0000-000000000001",
            script_relative="run.py",
            script_sha256="a" * 64,
            expected_outputs=["required"],
            optional_outputs=optional,
        )


def test_agent_collects_an_undeclared_chart_without_a_mandatory_chart_name(data_environment):
    state = data_environment
    state.update(data_exports=1, optional_outputs=True, declared_exports=[], exports={"chart.png": chart()})
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state, goal="Plot these data")
        finish(client, parent)
        with session_factory()() as session:
            python = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "python")
            )
            assert python.parameters["expected_outputs"] == ["result.json", "result.csv"]
            assert python.parameters["optional_outputs"] == ["chart.png", "result.xlsx", "report.txt"]
            result = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
            )
            assert result.status == "succeeded", result.error_message
            files = result.metadata_json["data_result"]["exports"]
            assert [item["filename"] for item in files] == ["chart.png"]
            assert session.get(Artifact, files[0]["artifact_id"]).thumbnail_relative_path
        assert client.get(f"/api/artifacts/{files[0]['artifact_id']}/file").status_code == 200
        assert state["calls"] == 1


def test_conversation_natural_plot_followup_keeps_inputs_and_exports_without_model_manifest(data_environment):
    state = data_environment
    state.update(data_exports=1, optional_outputs=True, declared_exports=[])
    with TestClient(app) as client:
        cid, first = start(client, state)
        drain()
        state["exports"] = {"chart.png": chart(), "result.xlsx": workbook()}
        response = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Plot these data", "web_search": {"enabled": True}},
        )
        assert response.status_code == 202, response.text
        second = response.json()
        assert second["parameters"]["data_reference"]["run_id"] == first["id"]
        drain()
        result = client.get(f"/api/chat/conversations/{cid}").json()["messages"][-1]
        assert result["task_status"] == "succeeded", result
        final = next(r for r in result["data_runs"] if r["metadata"].get("data_result"))
        assert {item["filename"] for item in final["metadata"]["data_result"]["exports"]} == {
            "chart.png",
            "result.xlsx",
        }
        assert state["calls"] == 2 and len(state["jobs"]) == 2


@pytest.mark.parametrize("support", [False, True])
def test_absent_optional_files_and_legacy_capability_keep_plain_analysis(data_environment, support):
    data_environment.update(data_exports=1, optional_outputs=support, declared_exports=[])
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment)
        finish(client, parent)
        with session_factory()() as session:
            python = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "python")
            )
            assert bool(python.parameters.get("optional_outputs")) is support
            result = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
            )
            assert result.status == "succeeded" and "exports" not in result.metadata_json["data_result"]


def test_optional_capture_policy_cannot_shrink_after_the_model_response(data_environment):
    from app.engine import tick

    state = data_environment
    state.update(data_exports=1, optional_outputs=True, declared_exports=[])
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state)
        with session_factory()() as session:
            for _ in range(8):
                tick(session, "freeze-optionals")
                python = session.scalar(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "python")
                )
                if python:
                    generator = session.get(Run, python.parent_run_id)
                    generator.metadata_json = {**generator.metadata_json, "data_optional_output_files": []}
                    python.parameters = {
                        k: v for k, v in python.parameters.items() if k != "optional_outputs"
                    }
                    session.commit()
                    break
            else:
                raise AssertionError("No Python child")
        finish(client, parent)
        assert not state["jobs"] and state["calls"] == 1


@pytest.mark.parametrize("mutation", ["unapproved", "before_required"])
def test_control_plane_never_adopts_forged_optional_reports(data_environment, monkeypatch, mutation):
    import copy

    from app.runner_client import RunnerClient

    state = data_environment
    state.update(data_exports=1, optional_outputs=True, declared_exports=[], exports={"chart.png": chart()})
    original = RunnerClient.request

    def request(self, method, path, payload=None):
        value = original(self, method, path, payload)
        if method == "GET" and path.startswith("/v1/runs/python/") and path.endswith("/report"):
            value = copy.deepcopy(value)
            if mutation == "unapproved":
                value["outputs"][-1]["name"] = "unapproved.html"
            else:
                value["outputs"] = [value["outputs"][-1], *value["outputs"][:-1]]
        return value

    monkeypatch.setattr(RunnerClient, "request", request)
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state, goal="Plot these data")
        rows = finish(client, parent)
        assert any(row[1:3] == ("python", "failed") for row in rows)
        with session_factory()() as session:
            assert not [
                a.id for a in session.scalars(select(Artifact)) if a.metadata_json.get("agent_data_export")
            ]
        assert state["calls"] == 1 and len(state["jobs"]) == 1
