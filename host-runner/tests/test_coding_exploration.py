import json
from types import SimpleNamespace

import pytest
from ai_station_runner.coding_exploration import explore


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("def target():\n    return 1\n")
    (tmp_path / ".env").write_text("SECRET")
    (tmp_path / "secret.key").write_text("SECRET")
    (tmp_path / "redirect.py").symlink_to(tmp_path / ".env")
    monkeypatch.setattr(
        "ai_station_runner.coding_exploration.Repository",
        lambda *a, **k: SimpleNamespace(
            read=lambda _: SimpleNamespace(stdout="app.py\0.env\0secret.key\0redirect.py\0")
        ),
    )
    return tmp_path


def test_exploration_observations_and_final_snapshots(workspace):
    actions = iter(
        [
            {"tool": "list_files", "prefix": "", "offset": 0},
            {"tool": "search_files", "query": "target", "prefix": ""},
            {"tool": "read_file", "path": "app.py"},
            {"tool": "finish", "files": ["app.py", "new.py"]},
        ]
    )
    messages = []

    def complete(message):
        messages.append(message)
        return json.dumps(next(actions))

    selected, trace = explore(workspace, "Fix target", "Keep tests", complete)
    assert trace[0]["result"]["files"] == ["app.py"]
    assert trace[1]["result"]["matches"][0]["line"] == 1
    assert selected[1]["content"] is None and selected[0]["sha256"]
    assert "SECRET" not in "".join(messages)
    assert (workspace / "app.py").read_text().endswith("return 1\n")
    assert not (workspace / "new.py").exists()


@pytest.mark.parametrize(
    "action",
    [
        {"tool": "shell", "command": "touch pwned"},
        {"tool": "read_file", "path": "../outside"},
        {"tool": "read_file", "path": ".env"},
        {"tool": "read_file", "path": "redirect.py"},
        {"tool": "finish", "files": ["secret.key"]},
        {"tool": "list_files", "prefix": "", "offset": -1},
        {"tool": "search_files", "query": "", "prefix": ""},
        {"tool": "finish", "files": []},
    ],
)
def test_exploration_rejects_unapproved_operations_and_paths(workspace, action):
    with pytest.raises(ValueError):
        explore(workspace, "Task", "", lambda _: json.dumps(action))
    assert not (workspace / "pwned").exists()


def test_exploration_has_a_finite_request_budget(workspace):
    calls = []

    def complete(message):
        calls.append(message)
        return '{"tool":"list_files","prefix":"","offset":0}'

    with pytest.raises(ValueError, match="eight requests"):
        explore(workspace, "Task", "", complete)
    assert len(calls) == 8
