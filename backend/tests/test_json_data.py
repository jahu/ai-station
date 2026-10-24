"""Raw JSON inputs retain structure, limits, inspection and offline data authority."""

import json

import pytest
from app.api import app
from app.config import get_settings
from app.data_json_preview import inspect_json
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_data_inputs import inspect, upload
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import data_environment as data_environment


def check():
    return None


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"values":[NaN]}',
        b'{"values":[Infinity]}',
        b'{"values":[-Infinity]}',
        b'{"value":1e9999}',
        b'{"value":',
        b"null",
        b"123",
        b'"text"',
        b"\xff",
        b'{"\\ud800":1}',
        b'{"value":"\\udfff"}',
    ],
)
def test_invalid_or_ambiguous_json_is_rejected(raw):
    with pytest.raises(ValueError):
        inspect_json(raw, check)


def test_nested_records_preview_keeps_real_columns_without_flattening_sources():
    raw = json.dumps(
        [
            {"Item": "A", "Price": 12, "Details": {"tags": ["red", "green"]}},
            {"Item": "B", "Price": "15", "Details": {"tags": ["blue"]}},
        ]
    ).encode()
    result = inspect_json(raw, check)
    assert result["format"] == "json" and result["root_type"] == "array"
    sheet = result["sheets"][0]
    assert sheet["column_names"] == ["Item", "Price", "Details"]
    assert sheet["row_count"] == 2 and sheet["column_count"] == 3
    assert sheet["preview"][0] == ['"A"', "12", '{"tags": ["red", "green"]}']
    assert sheet["preview"][1][1] == '"15"'


@pytest.mark.parametrize("value", [{}, [], [1, "two", {"nested": 3}], {"nested": {"records": [1, 2, 3]}}])
def test_objects_arrays_and_mixed_values_have_bounded_inspectable_previews(value):
    result = inspect_json(json.dumps(value).encode(), check)
    assert result["sheets"][0]["row_count"] == len(value)
    assert result["sheets"][0]["formula_count"] == 0


def test_json_limits_apply_to_full_values_not_only_the_preview(monkeypatch):
    from app import data_json_preview as preview

    monkeypatch.setattr(preview, "MAX_JSON_BYTES", 1024)
    with pytest.raises(ValueError, match="4 MiB"):
        inspect_json(b'{"long":"' + b"a" * 1024 + b'"}', check)
    monkeypatch.setattr(preview, "MAX_JSON_NODES", 20)
    with pytest.raises(ValueError, match="too many"):
        inspect_json(json.dumps([1] * 21).encode(), check)
    with pytest.raises(ValueError, match="too many"):
        inspect_json(json.dumps([{}] * 21).encode(), check)
    monkeypatch.setattr(preview, "MAX_JSON_NODES", 100_000)
    monkeypatch.setattr(preview, "MAX_JSON_BYTES", 4096)
    with pytest.raises(ValueError, match="nesting"):
        inspect_json(b"[" * 34 + b"0" + b"]" * 34, check)
    with pytest.raises(ValueError, match="nesting"):
        inspect_json(b"[" * 1200 + b"0" + b"]" * 1200, check)


def test_preview_cells_rows_and_columns_are_bounded_but_counts_cover_actual_json():
    value = [{"long": "a" * 1000, **{f"field{n}": n for n in range(25)}} for _ in range(30)]
    sheet = inspect_json(json.dumps(value).encode(), check)["sheets"][0]
    assert sheet["row_count"] == 30 and sheet["column_count"] == 26
    assert len(sheet["preview"]) == len(sheet["column_names"]) == 20
    assert all(len(row) == 20 and all(len(cell) <= 200 for cell in row) for row in sheet["preview"])


def test_inspection_observes_cancel_during_traversal():
    calls = []

    def stop():
        calls.append(True)
        if len(calls) > 3:
            raise InterruptedError("Stopped")

    with pytest.raises(InterruptedError):
        inspect_json(b'{"values":[1,2,3,4]}', stop)


def test_upload_json_queues_ordinary_inspection_preserving_source_bytes_and_lineage():
    raw = b'{"label":"<script>untrusted()</script>","records":[12,15]}'
    with TestClient(app) as api:
        artifact = upload(api, "source.json", raw)
        assert artifact["mime_type"] == "application/json" and artifact["type"] == "document"
        run = inspect(api, artifact)
        assert run["status"] == "succeeded", run
        preview = run["metadata"]["data_preview"]
        assert preview["format"] == "json" and preview["sheets"][0]["column_names"] == ["Key", "Value"]
        saved = api.get("/api/artifacts/" + run["metadata"]["preview_artifact_id"]).json()
        assert saved["parent_artifact_ids"] == [artifact["id"]]
        assert api.get("/api/artifacts/" + artifact["id"] + "/file").content == raw


def test_json_upload_limit_and_failed_inspection_remain_distinct():
    from app.data_json_preview import MAX_JSON_BYTES

    with TestClient(app) as api:
        response = api.post("/api/data/uploads", files={"file": ("huge.json", b"x" * (MAX_JSON_BYTES + 1))})
        assert response.status_code == 413
        artifact = upload(api, "broken.json", b'{"broken":')
        run = inspect(api, artifact)
        assert run["status"] == "failed" and run["error_type"] == "DataInspectionFailed"
        assert not api.get("/api/artifacts?run_id=" + run["id"]).json()
        assert api.get("/api/artifacts/" + artifact["id"] + "/file").content == b'{"broken":'


def test_stored_json_uses_existing_data_pipeline_without_public_research(data_environment):
    raw = json.dumps([{"Item": f"Item{n}", "Price": n} for n in range(30)]).encode()
    with TestClient(app) as api:
        artifact = upload(api, "records.json", raw)
        assert inspect(api, artifact)["status"] == "succeeded"
        response = api.post(
            "/api/agents",
            json={
                "name": "JSON analyst",
                "goal": "Calculate totals from the entire JSON",
                "model": data_environment["model"],
                "tools": ["python_data"],
                "data": {"input_artifact_ids": [artifact["id"]]},
                "enabled": True,
            },
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        parent = api.post(
            "/api/agents/" + agent["id"] + "/run", json={"expected_updated_at": agent["updated_at"]}
        ).json()
        for _ in range(24):
            with session_factory()() as s:
                if tick(s, "json-data-worker") is None:
                    break
        with session_factory()() as s:
            rows = list(s.scalars(select(Run).where(Run.task_id == parent["task_id"])))
            assert all(r.status == "succeeded" for r in rows), [
                (r.executor_type, r.status, r.error_message) for r in rows
            ]
            generation = next(r for r in rows if r.executor_type == "agent_data_generate")
            request = json.loads(generation.parameters["messages"][1]["content"])
            assert request["inputs"][0]["format"] == "json" and request["inputs"][0]["root_type"] == "array"
            assert request["inputs"][0]["sheets"][0]["row_count"] == 30
            assert len(request["inputs"][0]["sheets"][0]["sample"]) == 3
            assert (
                "JSON inputs contain complete original objects"
                in generation.parameters["messages"][0]["content"]
            )
            assert not any(r.executor_type == "agent_tool" for r in rows)
            python = next(r for r in rows if r.executor_type == "python")
            assert "network_read" not in python.effective_permissions
            assert (
                get_settings().data_dir / s.get(Artifact, artifact["id"]).relative_path
            ).read_bytes() == raw
