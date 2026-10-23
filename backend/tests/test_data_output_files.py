import io
import json
import zipfile

import pytest
from app.api import app
from app.data_agents import Script
from app.data_exports import validate
from app.db import session_factory
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from pydantic import ValidationError
from sqlalchemy import select
from test_conversation_data import drain, start
from test_data_inputs import workbook as input_workbook
from test_projects import owned_runner as owned_runner
from test_projects import repository as repository
from test_python_data_agents import create, finish
from test_python_data_agents import data_environment as data_environment


def workbook(**kwargs):
    value = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(input_workbook(**kwargs))) as source,
        zipfile.ZipFile(value, "w", zipfile.ZIP_DEFLATED) as out,
    ):
        for name in source.namelist():
            out.writestr(name, source.read(name))
        if "[Content_Types].xml" not in source.namelist():
            out.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
            )
        out.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
    return value.getvalue()


def chart(*, size=(320, 200), animation=False):
    value = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "Untrusted supplied chart metadata")
    image = Image.new("RGB", size, "navy")
    image.save(
        value,
        format="PNG",
        pnginfo=metadata,
        save_all=animation,
        append_images=[Image.new("RGB", size, "red")] if animation else [],
    )
    return value.getvalue()


@pytest.mark.parametrize("names", [["../../chart.png"], ["chart.svg"], ["report.pdf"], ["chart.png"] * 2])
def test_source_declaration_cannot_choose_paths_active_files_or_duplicates(names):
    with pytest.raises(ValidationError):
        Script(script="print('ok')", outputs=names)
    assert Script(script="print('legacy')").outputs == []


def test_png_is_reencoded_without_metadata_and_preserves_actual_pixels():
    raw = chart()
    clean = validate("chart.png", raw)
    with Image.open(io.BytesIO(clean)) as image:
        assert image.size == (320, 200) and not image.info
        assert image.getpixel((20, 20)) == (0, 0, 128)
    assert clean != raw


@pytest.mark.parametrize("data", [b"<svg onload='bad'/>", b"", chart(size=(4097, 1)), chart(animation=True)])
def test_invalid_or_unbounded_or_animated_chart_cannot_be_published(data):
    with pytest.raises((ValueError, OSError)):
        validate("chart.png", data)


@pytest.mark.parametrize(
    "data",
    [
        workbook(formula=True),
        workbook(member=("xl/vbaProject.bin", b"macro")),
        workbook(member=("xl/embeddings/oleObject1.bin", b"payload")),
        workbook(member=("xl/worksheets/_rels/sheet1.xml.rels", b"external")),
        workbook(
            member=(
                "[Content_Types].xml",
                '<Types><Override ContentType="application/vnd.ms-excel.macrosheet+xml"/></Types>',
            )
        ),
        workbook(
            sheet_xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><definedName>cmd|foo</definedName></worksheet>'
        ),
    ],
)
def test_generated_excel_rejects_formulas_and_active_package_parts(data):
    with pytest.raises(ValueError):
        validate("result.xlsx", data)


@pytest.mark.parametrize(
    "target", ['https://evil.example/x" TargetMode="External', "https://evil.example/x", "../../outside.xml"]
)
def test_generated_excel_rejects_external_and_escaping_relationships(target):
    original = workbook()
    value = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(value, "w") as out:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith(".rels"):
                data = data.replace(b"worksheets/sheet1.xml", target.encode())
            out.writestr(name, data)
    with pytest.raises(ValueError):
        validate("result.xlsx", value.getvalue())


def test_literal_workbook_and_text_are_verified_without_evaluation():
    data = workbook()
    assert validate("result.xlsx", data) == data
    assert validate("report.txt", "Wynik: 27\n".encode()) == "Wynik: 27\n".encode()
    for data in [b"bad\0text", b"\xff", b"a" * (128 * 1024 + 1)]:
        with pytest.raises(ValueError):
            validate("report.txt", data)


def test_incomplete_or_expanding_excel_is_not_a_usable_export():
    with pytest.raises(ValueError, match="complete"):
        validate("result.xlsx", input_workbook())
    with pytest.raises(ValueError):
        validate("result.xlsx", workbook(member=("xl/sharedStrings.xml", b"x" * (8 * 1024 * 1024 + 1))))


@pytest.mark.parametrize(
    "content",
    ["Narysuj wykres z tych danych", "Create a chart from this file", "Stwórz raport Excel z tych danych"],
)
def test_natural_export_request_keeps_the_original_data_scope(content):
    from app.conversation_data_reference import requested

    assert requested(content)


@pytest.mark.parametrize("entry", ["agent", "chat"])
def test_full_data_flow_publishes_only_verified_downloads_and_chart_lineage(data_environment, entry):
    state = data_environment
    state.update(
        data_exports=1,
        exports={"chart.png": chart(), "result.xlsx": workbook(), "report.txt": b"Total: 27\n"},
    )
    with TestClient(app) as client:
        if entry == "agent":
            _, parent, _, _ = create(client, state)
            finish(client, parent)
        else:
            _, parent = start(client, state)
            drain()
        with session_factory()() as session:
            final = session.scalar(
                select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "agent_data_result")
            )
            assert final.status == "succeeded", final.error_message
            result = final.metadata_json["data_result"]
            files = result["exports"]
            assert [item["filename"] for item in files] == list(state["exports"])
            exported = [session.get(Artifact, item["artifact_id"]) for item in files]
            raw = []
            for item in exported:
                assert item.run_id == final.id and item.metadata_json["agent_data_export"]
                assert set(result["input_artifact_ids"]) <= set(item.parent_artifact_ids)
                source = session.get(Artifact, item.parent_artifact_ids[0])
                assert source.metadata_json["internal_data_output"]
                raw.append(source.id)
            assert exported[0].artifact_type == "image" and exported[0].thumbnail_relative_path
            assert exported[0].sha256 != session.get(Artifact, raw[0]).sha256
        visible = {item["id"] for item in client.get("/api/artifacts?limit=100").json()}
        assert not visible.intersection(raw)
        for aid in raw:
            assert client.get(f"/api/artifacts/{aid}/file").status_code == 409
        for file in files:
            response = client.get(f"/api/artifacts/{file['artifact_id']}/file")
            assert response.status_code == 200 and response.headers["content-type"].startswith(
                file["mime_type"]
            )
        assert state["calls"] == 1
        assert (
            list(state["exports"])
            == json.loads(state["model_requests"][0]["messages"][1]["content"])["runtime"][
                "available_optional_outputs"
            ]
        )


def test_legacy_image_cannot_claim_new_output_support_or_launch_python(data_environment):
    state = data_environment
    state["exports"] = {"chart.png": chart()}
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state)
        rows = finish(client, parent)
        failed = [row for row in rows if row[2] == "failed"]
        assert failed and "Rebuild" in failed[0][3]
        assert not state["jobs"]


def test_invalid_file_uses_same_bounded_repair_without_publishing_exports(data_environment):
    state = data_environment
    state.update(data_exports=1, exports={"chart.png": b"not a chart"})
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state)
        rows = finish(client, parent)
        assert any(row[1:3] == ("agent_data_result", "failed") for row in rows)
        assert state["calls"] == 2
        assert "repair" in state["model_requests"][-1]["messages"][1]["content"]
        with session_factory()() as session:
            assert not [
                a for a in session.scalars(select(Artifact)) if a.metadata_json.get("agent_data_export")
            ]


def test_python_dispatch_rejects_changed_output_declaration_before_execution(data_environment):
    from app.engine import tick

    state = data_environment
    state.update(data_exports=1, exports={"chart.png": chart()})
    with TestClient(app) as client:
        _, parent, _, _ = create(client, state)
        with session_factory()() as session:
            for _ in range(8):
                tick(session, "prepare-file-output")
                source = session.scalar(
                    select(Run).where(Run.task_id == parent["task_id"], Run.executor_type == "python")
                )
                if source:
                    source.parameters = {
                        **source.parameters,
                        "expected_outputs": ["result.json", "result.csv", "report.txt"],
                    }
                    session.commit()
                    break
            else:
                raise AssertionError("Python child was not published")
        finish(client, parent)
        assert not state["jobs"]
