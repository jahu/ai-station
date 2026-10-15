import io
import json
import zipfile

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Run
from app.paths import safe_join
from fastapi.testclient import TestClient


def workbook(*, formula=False, member=None, sheet_xml=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sales" sheetId="1" r:id="sheet1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="sheet1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            sheet_xml
            or (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Item</t></is></c><c r="B1" t="inlineStr"><is><t>Total</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>Apple</t></is></c><c r="B2"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'
                if formula
                else '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>27</v></c></row></sheetData></worksheet>'
            ),
        )
        if member:
            z.writestr(*member)
    return output.getvalue()


def upload(client, name="sales.csv", content=b"Item,Total\nApple,12\nPear,15\n"):
    response = client.post("/api/data/uploads", files={"file": (name, content, "application/octet-stream")})
    assert response.status_code == 201, response.text
    return response.json()


def inspect(client, artifact):
    run_id = artifact["metadata"]["data_inspection_run_id"]
    with session_factory()() as session:
        assert tick(session, "data-worker") == run_id
    return client.get("/api/runs/" + run_id).json()


@pytest.mark.parametrize(
    "name,payload",
    [("sales.csv", b"Item;Total\nApple;12\nPear;15\n"), ("sales.xlsx", workbook(formula=True))],
)
def test_upload_queues_bounded_preview_with_original_source_and_lineage(name, payload):
    with TestClient(app) as client:
        artifact = upload(client, name, payload)
        with session_factory()() as session:
            assert session.get(Run, artifact["metadata"]["data_inspection_run_id"]).status == "queued"
        run = inspect(client, artifact)
        assert run["status"] == "succeeded", run
        sheet = run["metadata"]["data_preview"]["sheets"][0]
        assert sheet["column_count"] == 2
        if name.endswith(".xlsx"):
            assert sheet["formula_count"] == 1
            assert sheet["preview"][1][1] == "[Formula — not evaluated]"
        else:
            assert sheet["row_count"] == 3 and sheet["preview"][2] == ["Pear", "15"]
        output_id = run["metadata"]["preview_artifact_id"]
        output = client.get("/api/artifacts/" + output_id).json()
        assert output["parent_artifact_ids"] == [artifact["id"]]
        assert (
            json.loads(client.get("/api/artifacts/" + output_id + "/file").content)
            == run["metadata"]["data_preview"]
        )
        assert client.get("/api/artifacts/" + artifact["id"] + "/file").content == payload


@pytest.mark.parametrize(
    "name,payload",
    [
        ("broken.xlsx", b"not zip"),
        ("binary.csv", b"\xff\x00"),
        ("macro.xlsx", workbook(member=("xl/vbaProject.bin", b"macro"))),
        ("traversal.xlsx", workbook(member=("../file", b"escape"))),
        ("entities.xlsx", workbook(sheet_xml='<!DOCTYPE test [<!ENTITY x "expansion">]><test/>')),
    ],
)
def test_invalid_inputs_fail_without_a_preview_or_source_changes(name, payload):
    with TestClient(app) as client:
        artifact = upload(client, name, payload)
        run = inspect(client, artifact)
        assert run["status"] == "failed" and run["error_type"] == "DataInspectionFailed"
        assert not client.get("/api/artifacts?run_id=" + run["id"]).json()
        assert client.get("/api/artifacts/" + artifact["id"] + "/file").content == payload


def test_changed_hash_and_trashed_input_fail_closed_before_read():
    with TestClient(app) as client:
        artifact = upload(client)
        with session_factory()() as session:
            row = session.get(Artifact, artifact["id"])
            safe_join(get_settings().data_dir, row.relative_path).write_bytes(b"Changed bytes")
        assert inspect(client, artifact)["status"] == "failed"
        assert (
            client.post(
                "/api/data/inspections", json={"artifact_id": artifact["id"], "path": "/etc/passwd"}
            ).status_code
            == 422
        )


def test_stop_prevents_reading_and_no_preview_is_published():
    with TestClient(app) as client:
        artifact = upload(client)
        run_id = artifact["metadata"]["data_inspection_run_id"]
        assert client.post("/api/runs/" + run_id + "/cancel").status_code == 200
        with session_factory()() as session:
            assert tick(session, "data-worker") is None
        assert client.get("/api/runs/" + run_id).json()["status"] == "canceled"
        assert not client.get("/api/artifacts?run_id=" + run_id).json()


def test_preview_and_archive_limits(monkeypatch):
    from app.data_preview import inspect_csv, inspect_xlsx

    def check():
        return None

    csv_result = inspect_csv(("name,value\n" + "x,10\n" * 100).encode(), check)
    assert csv_result["sheets"][0]["row_count"] == 101
    assert len(csv_result["sheets"][0]["preview"]) == 20
    with pytest.raises(ValueError, match="column"):
        inspect_csv((",".join(["x"] * 129)).encode(), check)
    with pytest.raises(ValueError):
        inspect_xlsx(workbook(member=("xl/huge.xml", b"x" * (8 * 1024 * 1024 + 1))), check)


def test_upload_type_length_and_path_injection_are_bounded():
    with TestClient(app) as client:
        assert client.post("/api/data/uploads", files={"file": ("code.py", b"print(1)")}).status_code == 422
        assert client.post("/api/data/uploads", files={"file": ("empty.csv", b"")}).status_code == 413
        assert (
            client.post(
                "/api/data/uploads", content=b"", headers={"content-length": str(21 * 1024 * 1024)}
            ).status_code
            == 413
        )
        artifact = upload(client, "../../sales.csv")
        assert artifact["original_filename"] == "sales.csv"


def test_running_stop_discards_preview_before_publication(monkeypatch):
    from app import data_inputs
    from app.runs import request_cancel

    with TestClient(app) as client:
        artifact = upload(client)
        run_id = artifact["metadata"]["data_inspection_run_id"]

        def slow(data, check):
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            for _ in range(130):
                check()
            raise AssertionError("Cancellation was not observed")

        monkeypatch.setattr(data_inputs, "inspect_csv", slow)
        assert inspect(client, artifact)["status"] == "canceled"
        assert not client.get("/api/artifacts?run_id=" + run_id).json()


def test_redirected_or_trashed_inputs_are_rejected(tmp_path):
    from app.db import utcnow

    with TestClient(app) as client:
        artifact = upload(client)
        with session_factory()() as session:
            row = session.get(Artifact, artifact["id"])
            row.trashed_at = utcnow()
            session.commit()
        assert client.post("/api/data/inspections", json={"artifact_id": artifact["id"]}).status_code == 422
        assert inspect(client, artifact)["status"] == "failed"
        artifact2 = upload(client)
        with session_factory()() as session:
            row = session.get(Artifact, artifact2["id"])
            source = safe_join(get_settings().data_dir, row.relative_path)
            outside = tmp_path / "secret.csv"
            outside.write_text("Never include this secret")
            source.unlink()
            source.symlink_to(outside)
        result = inspect(client, artifact2)
        assert result["status"] == "failed"
        assert "Never include" not in str(result)


def test_sparse_excel_rows_keep_their_real_source_numbers():
    from app.data_preview import inspect_xlsx

    result = inspect_xlsx(
        workbook(
            sheet_xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="100"><c r="B100"><v>42</v></c></row></sheetData></worksheet>'
        ),
        lambda: None,
    )
    sheet = result["sheets"][0]
    assert sheet["row_count"] == 100 and sheet["preview_row_numbers"] == [100]
    assert sheet["preview"] == [["", "42"]]
