"""A real local-model response redundantly listed the two mandatory table files."""

import json

import pytest
from app.data_agents import Script
from app.data_exports import OutputFiles
from pydantic import ValidationError
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def test_model_may_redundantly_declare_exact_mandatory_tables_without_new_exports():
    value = Script.model_validate_json(
        json.dumps(
            {
                "script": "print('ok')",
                "outputs": ["result.csv", "result.json", "result.xlsx", "chart.png", "report.txt"],
            }
        )
    )
    assert value.outputs == ["result.xlsx", "chart.png", "report.txt"]
    assert value.script == "print('ok')"
    with pytest.raises(ValidationError):
        OutputFiles(outputs=["result.json"])


@pytest.mark.parametrize(
    "outputs",
    [
        ["result.json", "../../result.csv"],
        ["/outputs/result.csv"],
        ["other.json"],
        ["result.csv", "result.csv"],
        ["result.json", "chart.png", "chart.png"],
        ["result.csv", "result.json", "result.xlsx", "chart.png", "report.txt", "sixth"],
        ["result.csv", 1],
        "result.csv",
        {"result.csv": True},
    ],
)
def test_normalization_never_accepts_unknown_paths_duplicates_or_unbounded_shapes(outputs):
    with pytest.raises(ValidationError):
        Script(script="print('ok')", outputs=outputs)


def test_actual_worker_keeps_fixed_native_outputs_and_records_redundant_declarations(data_environment):
    from app.api import app
    from app.db import session_factory
    from app.models import RunEvent
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from test_data_output_files import chart, workbook
    from test_local_file_creation import create, drain

    data_environment.update(
        data_exports=1,
        exports={
            "result.xlsx": workbook(),
            "chart.png": chart(),
            "report.txt": b"Created from instructions\n",
        },
        declared_exports=["result.csv", "result.json", "result.xlsx", "chart.png", "report.txt"],
    )
    with TestClient(app) as api:
        rows = drain(
            create(
                api,
                data_environment,
                goal="Create an Excel workbook, a chart and a text report with a Total of 27",
            )
        )
        assert all(row.status == "succeeded" for row in rows), [
            (row.executor_type, row.status, row.error_message) for row in rows
        ]
        generation = next(row for row in rows if row.executor_type == "agent_data_generate")
        assert generation.metadata_json["mandatory_data_output_declarations"] == ["result.csv", "result.json"]
        assert generation.metadata_json["declared_data_output_files"] == [
            "result.xlsx",
            "chart.png",
            "report.txt",
        ]
        python = next(row for row in rows if row.executor_type == "python")
        assert python.parameters["expected_outputs"] == [
            "result.json",
            "result.csv",
            "chart.png",
            "result.xlsx",
            "report.txt",
        ]
        result = next(row for row in rows if row.executor_type == "agent_data_result").metadata_json[
            "data_result"
        ]
        assert {item["filename"] for item in result["exports"]} == {"result.xlsx", "chart.png", "report.txt"}
        with session_factory()() as db:
            event = db.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == generation.id, RunEvent.event_type == "data.outputs.mandatory_declared"
                )
            )
            assert event.payload == {"filenames": ["result.csv", "result.json"]}
        assert len(data_environment["jobs"]) == 1 and data_environment["calls"] == 1
