import json

import pytest
from ai_station_runner.coding import CodingUnavailable
from ai_station_runner.cursor_adapter import prepare_cursor, proposal_result


def test_cursor_configuration_isolated_and_auth_is_only_a_directory_reference(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_station_runner.cursor_adapter.shutil.which", lambda _: "/installed/cursor-agent")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/user/config")
    monkeypatch.setenv("CURSOR_API_KEY", "fixture-do-not-copy")
    argv, env, workspace = prepare_cursor(
        tmp_path / "provider",
        prompt="Fix",
        selected=[{"path": "a.py", "content": "pass\n"}],
        guidance="Use tests",
    )
    assert argv[argv.index("--allowed-tools") + 1] == ""
    assert "--disable-project-configs" in argv and "--disable-auto-update" in argv
    assert env["XDG_CONFIG_HOME"] == "/user/config" and "CURSOR_API_KEY" not in env
    assert workspace.is_dir() and {p.name for p in workspace.iterdir()} == {".git"}
    assert "fixture-do-not-copy" not in json.dumps(env) + json.dumps(argv)
    assert "a.py" in argv[-1]


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "result", "subtype": "error", "result": "x"}],
        [{"type": "tool_call"}, {"type": "result", "subtype": "success", "result": "{}"}],
        [
            {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}},
            {"type": "result", "subtype": "success", "result": "{}"},
        ],
    ],
)
def test_cursor_requires_one_successful_text_result_without_tools(events):
    with pytest.raises(CodingUnavailable):
        proposal_result(events)
