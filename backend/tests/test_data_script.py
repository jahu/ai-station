import json

import pytest
from app.data_script import prepare_script


@pytest.mark.parametrize(
    "header",
    ["", '"""Analysis documentation."""\n', "from __future__ import annotations\n"],
)
def test_script_can_read_only_supplied_mapping_without_model_written_initialization(monkeypatch, header):
    monkeypatch.setenv("AI_STATION_INPUTS", json.dumps({"approved.xlsx": "/inputs/approved.xlsx"}))
    monkeypatch.setenv("AI_STATION_OUTPUT_DIR", "/outputs")
    source = header + '# Retain useful model comments.\nanswer = (inputs["approved.xlsx"], output_dir)\n'
    prepared = prepare_script(source)
    scope = {}
    exec(compile(prepared, "analysis.py", "exec"), scope)
    assert scope["answer"] == ("/inputs/approved.xlsx", "/outputs")
    assert "# Retain useful model comments." in prepared
    assert "approved.xlsx" not in prepared.split("# Retain useful model comments.")[0]
    assert set(scope["inputs"]) == {"approved.xlsx"}


def test_inline_future_import_and_docstring_keep_their_python_semantics(monkeypatch):
    monkeypatch.setenv("AI_STATION_INPUTS", "{}")
    monkeypatch.setenv("AI_STATION_OUTPUT_DIR", "/outputs")
    prepared = prepare_script('"module doc"; from __future__ import annotations; value = inputs\n')
    scope = {}
    exec(compile(prepared, "analysis.py", "exec"), scope)
    assert scope["__doc__"] == "module doc"
    assert scope["value"] == {}


def test_runtime_bindings_retain_source_bounds_and_reject_invalid_future_statements():
    with pytest.raises(ValueError, match="including runtime bindings"):
        prepare_script("#" + "a" * 31990)
    with pytest.raises(SyntaxError):
        prepare_script("value = 1\nfrom __future__ import annotations\n")


@pytest.mark.parametrize("imports", ["", "\nimport csv\nimport json\nimport os\n"])
@pytest.mark.parametrize("header", ["", '"""CSV export."""\nfrom __future__ import annotations\n'])
def test_csv_exports_work_with_missing_or_late_standard_imports(monkeypatch, tmp_path, imports, header):
    import csv

    monkeypatch.setenv("AI_STATION_INPUTS", "{}")
    monkeypatch.setenv("AI_STATION_OUTPUT_DIR", str(tmp_path))
    # Actual QA failure: csv.writer is used before an import at the very end,
    # including in the model's failed repair. Execute the full export, not just AST parsing.
    source = (
        header
        + """columns = ["produkt", "cena"]
rows = [["Mleko", "5.99"], ["Chleb", "3.50"], ["Jajka", "8.20"]]
with open(os.path.join(output_dir, "result.csv"), "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows(rows)
with open(os.path.join(output_dir, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"answer": "Dane przykładowe", "columns": columns, "rows": rows}, f)
"""
        + imports
    )
    prepared = prepare_script(source)
    assert source.splitlines()[-1] in prepared
    exec(compile(prepared, "analysis.py", "exec"), {})
    with (tmp_path / "result.csv").open(newline="", encoding="utf-8") as f:
        table = list(csv.reader(f))
    result = json.loads((tmp_path / "result.json").read_text())
    assert table == [result["columns"], *result["rows"]]
    assert table[0] == ["produkt", "cena"] and len(table) == 4


def test_bindings_do_not_supply_unrelated_missing_modules(monkeypatch):
    monkeypatch.setenv("AI_STATION_INPUTS", "{}")
    monkeypatch.setenv("AI_STATION_OUTPUT_DIR", "/outputs")
    with pytest.raises(NameError, match="openpyxl"):
        exec(compile(prepare_script("wb = openpyxl.Workbook()\n"), "analysis.py", "exec"), {})
