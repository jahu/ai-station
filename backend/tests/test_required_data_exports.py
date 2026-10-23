import json

import pytest
from app.api import app
from app.data_exports import required_exports
from app.db import session_factory
from app.engine import tick
from app.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_data_output_files import chart, workbook
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create, finish
from test_python_data_agents import data_environment as data_environment


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("Narysuj wykres z tych danych", ["chart.png"]),
        ("Stwórz wykres i Excela", ["chart.png", "result.xlsx"]),
        ("Create a chart and an Excel workbook", ["chart.png", "result.xlsx"]),
        ("Export the result as Excel", ["result.xlsx"]),
        ("Przygotuj plik Excel i raport tekstowy", ["result.xlsx", "report.txt"]),
        ("Zapisz wynik jako XLSX", ["result.xlsx"]),
        ("Generate chart.png, result.xlsx and report.txt", ["chart.png", "result.xlsx", "report.txt"]),
        ("Calculate the total", []),
        ("Analyze this Excel workbook", []),
        ("Create a chart from Excel", ["chart.png"]),
        ('Explain "Create a chart and Excel workbook"', []),
        ("```\nCreate a chart\n```", []),
        ("Bez wykresu oblicz sumę", []),
        ("Create an Excel workbook without a chart", ["result.xlsx"]),
        ("Do not create a chart", []),
        ("Nie twórz wykresu", []),
    ],
)
def test_only_current_explicit_creation_requires_file_outputs(goal, expected):
    assert required_exports(goal) == expected


def test_model_omitting_exports_cannot_discard_the_users_requested_files(data_environment):
    state = data_environment
    state.update(
        data_exports=1,
        declared_exports=[],
        exports={"chart.png": chart(), "result.xlsx": workbook(), "report.txt": b"Total: 27\n"},
    )
    with TestClient(app) as client:
        _, parent, _, _ = create(
            client, state, goal="Stwórz wykres i przygotuj plik Excel oraz raport tekstowy"
        )
        finish(client, parent)
        with session_factory()() as session:
            result = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
            )
            assert result.status == "succeeded", result.error_message
            exports = result.metadata_json["data_result"]["exports"]
            assert [item["filename"] for item in exports] == list(state["exports"])
        for item in exports:
            assert client.get(f"/api/artifacts/{item['artifact_id']}/file").status_code == 200
        requested = json.loads(state["model_requests"][0]["messages"][1]["content"])
        assert requested["runtime"]["required_outputs"] == ["result.json", "result.csv", *state["exports"]]
        assert state["calls"] == 1 and len(state["jobs"]) == 1


def test_requested_export_on_old_image_fails_before_model_inference(data_environment):
    with TestClient(app) as client:
        _, parent, _, _ = create(client, data_environment, goal="Draw a chart from these data")
        rows = finish(client, parent)
        assert any(row[2] == "failed" and "Rebuild" in row[3] for row in rows)
        assert not data_environment["jobs"] and data_environment["calls"] == 0


def test_queued_required_export_cannot_be_removed_from_both_declarations(data_environment):
    state = data_environment
    state.update(data_exports=1, declared_exports=[], exports={"chart.png": chart()})
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state, goal="Draw a chart from these data")
        with session_factory()() as session:
            for _ in range(8):
                tick(session, "require-exports")
                python = session.scalar(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "python")
                )
                if python:
                    generator = session.get(Run, python.parent_run_id)
                    generator.metadata_json = {**generator.metadata_json, "data_output_files": []}
                    python.parameters = {
                        **python.parameters,
                        "expected_outputs": ["result.json", "result.csv"],
                    }
                    session.commit()
                    break
            else:
                raise AssertionError("Python was not queued")
        finish(client, parent)
        assert not state["jobs"]
