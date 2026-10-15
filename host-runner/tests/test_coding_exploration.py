import json
from types import SimpleNamespace

import pytest
from ai_station_runner import public_http
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

    with pytest.raises(ValueError, match="8 requests"):
        explore(workspace, "Task", "", complete)
    assert len(calls) == 8


def test_exploration_without_web_rejects_fetch_and_search(workspace):
    for action in (
        {"tool": "fetch_url", "url": "https://www.koratimber.com/"},
        {"tool": "web_search", "query": "Kora Timber"},
    ):
        with pytest.raises(ValueError, match="Unsupported"):
            explore(workspace, "Task", "", lambda _: json.dumps(action))


def test_local_web_exploration_fetches_public_pages(workspace, monkeypatch):
    monkeypatch.setattr(
        public_http,
        "fetch_public",
        lambda url: {
            "url": url,
            "status": 200,
            "text": "Kora Timber company",
            "links": [],
            "untrusted": True,
        },
    )
    monkeypatch.setattr(public_http, "configured_search_url", lambda: "")
    actions = iter(
        [
            {"tool": "list_files", "prefix": "", "offset": 0},
            {"tool": "fetch_url", "url": "https://www.koratimber.com/"},
            {"tool": "finish", "files": ["index.html"]},
        ]
    )
    messages = []

    def complete(message):
        messages.append(message)
        return json.dumps(next(actions))

    selected, trace = explore(workspace, "Build the Kora Timber site", "", complete, web=True)
    assert selected[0]["path"] == "index.html"
    assert trace[1]["result"]["text"] == "Kora Timber company"
    assert "fetch_url" in messages[0]
    assert "web_search" not in messages[0]
    assert "There is no shell, browser or external service" not in messages[0]


def test_local_web_exploration_can_search_when_configured(workspace, monkeypatch):
    monkeypatch.setattr(public_http, "configured_search_url", lambda: "http://127.0.0.1:8878")
    monkeypatch.setattr(
        public_http,
        "search_web",
        lambda query: {
            "query": query,
            "sources": [{"url": "https://www.koratimber.com/"}],
            "untrusted": True,
        },
    )
    actions = iter(
        [
            {"tool": "web_search", "query": "Kora Timber"},
            {"tool": "finish", "files": ["index.html"]},
        ]
    )
    _, trace = explore(workspace, "Build the site", "", lambda _: json.dumps(next(actions)), web=True)
    assert trace[0]["result"]["sources"][0]["url"] == "https://www.koratimber.com/"


def test_local_web_exploration_fails_closed_on_private_fetch(workspace, monkeypatch):
    def refuse(url):
        raise ValueError("fetch_url requires a public http(s) URL")

    monkeypatch.setattr(public_http, "fetch_public", refuse)
    monkeypatch.setattr(public_http, "configured_search_url", lambda: "")
    with pytest.raises(ValueError, match="public http"):
        explore(
            workspace,
            "Task",
            "",
            lambda _: json.dumps({"tool": "fetch_url", "url": "http://127.0.0.1/"}),
            web=True,
        )


def test_web_exploration_prefetches_public_task_urls(workspace, monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {"url": url, "status": 200, "text": "live Kora Timber mill", "untrusted": True}

    monkeypatch.setattr(public_http, "fetch_public", fake_fetch)
    monkeypatch.setattr(public_http, "configured_search_url", lambda: "")
    actions = iter([{"tool": "finish", "files": ["index.html"]}])
    messages = []

    def complete(message):
        messages.append(message)
        return json.dumps(next(actions))

    _, trace = explore(
        workspace,
        "Zbuduj stronę https://www.koratimber.com/",
        "",
        complete,
        web=True,
    )
    assert calls == ["https://www.koratimber.com/"]
    assert trace[0]["request"]["source"] == "task"
    assert "live Kora Timber mill" in messages[0]
    assert "fetched automatically" in messages[0]


def test_exploration_without_web_does_not_prefetch_task_urls(workspace, monkeypatch):
    monkeypatch.setattr(
        public_http,
        "fetch_public",
        lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )
    _, trace = explore(
        workspace,
        "Clone https://www.koratimber.com/",
        "",
        lambda _: json.dumps({"tool": "finish", "files": ["index.html"]}),
    )
    assert all(item["request"].get("tool") != "fetch_url" for item in trace)


def test_web_exploration_has_a_twelve_request_budget(workspace, monkeypatch):
    monkeypatch.setattr(public_http, "configured_search_url", lambda: "")
    calls = []

    def complete(message):
        calls.append(message)
        return '{"tool":"list_files","prefix":"","offset":0}'

    with pytest.raises(ValueError, match="12 requests"):
        explore(workspace, "Task", "", complete, web=True)
    assert len(calls) == 12


def test_missing_finish_operation_is_corrected_without_guessing_or_writing(workspace, capsys):
    replies = iter([{"files": ["app.py"]}, {"tool": "finish", "files": ["app.py"]}])
    messages = []

    def complete(message):
        messages.append(message)
        return json.dumps(next(replies))

    selected, observations = explore(workspace, "Read app", "", complete)
    assert selected[0]["path"] == "app.py"
    assert len(messages) == 2 and "Operation was not executed" in messages[1]
    assert observations[0]["result"]["executed"] is False
    assert '"event": "tool.failed"' in capsys.readouterr().out
    assert (workspace / "app.py").read_text().endswith("return 1\n")


def test_malformed_declared_operation_gets_only_two_corrections(workspace):
    calls = []

    def complete(message):
        calls.append(message)
        return '{"tool":"read_file"}'

    with pytest.raises(ValueError, match="two corrections"):
        explore(workspace, "Task", "", complete)
    assert len(calls) == 3


def test_unknown_tool_fails_immediately_without_correction(workspace):
    calls = []

    def complete(message):
        calls.append(message)
        return '{"tool":"shell","command":"touch pwned"}'

    with pytest.raises(ValueError, match="Unsupported"):
        explore(workspace, "Task", "", complete)
    assert len(calls) == 1 and not (workspace / "pwned").exists()
