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
