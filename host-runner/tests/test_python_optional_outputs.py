import base64
import hashlib
import json
import sys
from uuid import UUID

import pytest
from ai_station_runner import python_container, python_job, python_runs
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.python_protocol import output_names_match
from pydantic import ValidationError
from test_python_runs import IMAGE, request
from test_python_runs import isolated_python as isolated_python


def legacy_request():
    return {
        "run_id": str(UUID(int=1)),
        "project_id": str(UUID(int=2)),
        "worktree_run_id": str(UUID(int=3)),
        "script_relative": "analysis.py",
        "script_sha256": "a" * 64,
        "script_artifact_id": None,
        "inputs": [],
        "expected_outputs": ["result.json"],
        "maximum_runtime": 120,
        "permissions": ["filesystem_read", "workspace_write", "python_execute"],
    }


def test_old_request_json_digest_replay_and_empty_optional_identity_are_unchanged(tmp_path, monkeypatch):
    old = legacy_request()
    encoded = json.dumps(old, separators=(",", ":"))
    for payload in [old, {**old, "optional_outputs": []}]:
        body = python_runs.PythonRequest.model_validate(payload)
        assert body.model_dump_json() == encoded
        assert "optional_outputs" not in body.model_dump(mode="json")
    saved = {"request": old, "digest": hashlib.sha256(encoded.encode()).hexdigest(), "image": IMAGE}
    monkeypatch.setattr(python_runs, "directory", lambda run_id: tmp_path)
    (tmp_path / "request.json").write_text(json.dumps(saved))
    assert python_runs.load_request(old["run_id"]) == saved

    class Manager:
        def inspect(self, run_id):
            assert run_id == old["run_id"]
            return {"executor": "python", "alive": False}

    assert python_runs.start_python(Manager(), body) == {"executor": "python", "alive": False}
    with pytest.raises(ValueError, match="another Python request"):
        python_runs.start_python(
            Manager(), python_runs.PythonRequest.model_validate({**old, "optional_outputs": ["chart.png"]})
        )


@pytest.mark.parametrize(
    "optional",
    [["../secret"], ["/etc/passwd"], ["same", "same"], ["report.csv"], [f"x{i}" for i in range(8)], None],
)
def test_optional_request_paths_overlap_duplicates_and_total_count_fail_closed(optional):
    with pytest.raises(ValidationError):
        request(optional_outputs=optional)


@pytest.mark.parametrize(
    "actual,valid",
    [
        (["required"], True),
        (["required", "plot"], True),
        (["required", "book"], True),
        (["required", "plot", "book"], True),
        ([], False),
        (["plot"], False),
        (["required", "book", "plot"], False),
        (["required", "plot", "plot"], False),
        (["required", "outside"], False),
        (["required", {}], False),
    ],
)
def test_report_requires_a_complete_prefix_and_ordered_optional_subset(actual, valid):
    assert output_names_match(["required"], ["plot", "book"], actual) is valid


def test_optional_dispatch_requires_actual_installed_image_support_before_staging(tmp_path, monkeypatch):
    body = request(optional_outputs=["chart.png"])
    monkeypatch.setattr(
        python_runs, "capabilities", lambda: {"available": True, "image_id": IMAGE, "optional_outputs": False}
    )

    class Manager:
        def inspect(self, run_id):
            raise ProcessNotOwned(run_id)

        def start(self, **kwargs):
            pytest.fail("Unsupported optional collection started a process")

    with pytest.raises(ValueError, match="does not support optional"):
        python_runs.start_python(Manager(), body)
    assert not (python_runs.directory(str(body.run_id)) / "inputs").exists()


def test_native_stream_rejects_unapproved_reordered_and_duplicate_optional_files(tmp_path, monkeypatch):
    body = request(optional_outputs=["chart.png", "report.txt"])
    monkeypatch.setattr(python_job, "directory", lambda run_id: tmp_path)

    def collect(name, outputs):
        python_job.collect_output(
            str(body.run_id),
            body,
            {"event": "output", "name": name, "data": base64.b64encode(b"value").decode()},
            outputs,
        )

    outputs = []
    collect("report.csv", outputs)
    collect("report.txt", outputs)
    for bad in ["chart.png", "report.txt", "outside.txt"]:
        with pytest.raises(ValueError):
            collect(bad, outputs)
    assert [item["name"] for item in outputs] == ["report.csv", "report.txt"]
    assert len(list(tmp_path.iterdir())) == 2


@pytest.fixture
def wrapped_cpu(tmp_path, monkeypatch, capsys):
    """Real disposable CPU child; production's fixed paths are mapped only in tests."""
    output = tmp_path / "outputs"
    output.mkdir()
    script = tmp_path / "analysis.py"
    popen = python_container.subprocess.Popen
    read = python_container.read_output

    def start(argv, **kwargs):
        assert argv == [sys.executable, "-I", "-u", "/inputs/script.py"]
        assert kwargs["cwd"] == "/outputs" and kwargs["start_new_session"] is True
        kwargs["cwd"] = output
        kwargs["env"] = {**kwargs["env"], "AI_STATION_OUTPUT_DIR": str(output)}
        return popen([*argv[:-1], str(script)], **kwargs)

    monkeypatch.setattr(python_container.subprocess, "Popen", start)
    monkeypatch.setattr(python_container, "read_output", lambda name: read(name, str(output)))

    def run(source, *, required=None, optional=None):
        script.write_text(source)
        body = {"maximum_runtime": 5, "expected_outputs": required or ["result.csv"], "inputs": {}}
        if optional is not None:
            body["optional_outputs"] = optional
        python_container.execute(body)
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    return run


@pytest.mark.parametrize(
    "optional,created,expected",
    [
        (None, False, ["result.csv"]),
        (["chart.png"], False, ["result.csv"]),
        (["chart.png"], True, ["result.csv", "chart.png"]),
        (["missing.txt", "chart.png"], True, ["result.csv", "chart.png"]),
    ],
)
def test_actual_cpu_wrapper_collects_only_present_approved_optional_files(
    wrapped_cpu, optional, created, expected
):
    source = "from pathlib import Path\nPath('result.csv').write_text('Total\\n27\\n')\n"
    if created:
        source += "Path('chart.png').write_bytes(b'optional file bytes')\n"
    events = wrapped_cpu(source, optional=optional)
    assert events[-1] == {"event": "result", "exit_code": 0, "outputs": expected, "error": None}
    assert [event["name"] for event in events if event["event"] == "output"] == expected


@pytest.mark.parametrize(
    "unsafe",
    [
        "Path('chart.png').symlink_to('result.csv')",
        "Path('other').write_text('x'); os.link('other','chart.png')",
        "os.mkfifo('chart.png')",
        "Path('chart.png').mkdir()",
    ],
)
def test_unsafe_optional_file_fails_without_publishing_even_required_files(wrapped_cpu, unsafe):
    events = wrapped_cpu(
        "import os\nfrom pathlib import Path\nPath('result.csv').write_text('ok')\n" + unsafe,
        optional=["chart.png"],
    )
    assert not [event for event in events if event["event"] == "output"]
    assert events[-1]["error"] and events[-1]["outputs"] == []


def test_missing_required_file_cannot_be_replaced_by_an_optional_file(wrapped_cpu):
    events = wrapped_cpu(
        "from pathlib import Path\nPath('chart.png').write_text('optional')", optional=["chart.png"]
    )
    assert events[-1]["error"] and events[-1]["outputs"] == []


def test_optional_files_obey_the_same_total_limit(wrapped_cpu, monkeypatch):
    monkeypatch.setattr(python_container, "MAX_OUTPUT_TOTAL", 5)
    events = wrapped_cpu(
        "from pathlib import Path\nPath('result.csv').write_text('abcd')\nPath('chart.png').write_text('efgh')",
        optional=["chart.png"],
    )
    assert events[-1]["error"] and events[-1]["outputs"] == []
