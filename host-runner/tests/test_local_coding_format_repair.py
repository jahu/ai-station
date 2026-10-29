"""Retry local proposal formatting once before any common executor writes."""

import json
from types import SimpleNamespace

import pytest
from ai_station_runner import local_coding_job

SELECTED = [{"path": "src/index.html", "content": "<h1>Original</h1>"}]
VALID = {"summary": "Update title", "files": [{"path": "src/index.html", "content": "<h1>Updated</h1>"}]}


@pytest.mark.parametrize(
    "invalid",
    [
        "not JSON",
        json.dumps({**VALID, "summary": {"title": "Wrong type"}}),
        json.dumps({**VALID, "files": VALID["files"] * 2}),
        json.dumps({**VALID, "files": [{"path": "unselected.py", "content": "unsafe"}]}),
    ],
)
def test_one_corrected_completion_keeps_the_original_snapshot_and_bounded_budget(
    monkeypatch, capsys, invalid
):
    requests = []

    def complete(body, message, *, max_tokens):
        requests.append((message, max_tokens))
        return (invalid if len(requests) == 1 else json.dumps(VALID)), {"name": "fake-local"}

    monkeypatch.setattr(local_coding_job, "collect_completion", complete)
    body = SimpleNamespace(prompt="Update title", guidance="Keep the selected source")
    text, provider = local_coding_job.collect_proposal(body, SELECTED)
    assert json.loads(text) == VALID and provider == {"name": "fake-local"}
    assert len(requests) == 2 and [r[1] for r in requests] == [8192, 8192]
    assert requests[1][0].startswith(requests[0][0])
    assert "SAME task and selected files" in requests[1][0]
    assert "Use each selected path at most once" in requests[1][0]
    assert SELECTED[0]["content"] == "<h1>Original</h1>"
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "coding.proposal.rejected" and event["attempt"] == 1


def test_repeated_invalid_summary_stops_after_two_attempts(monkeypatch, capsys):
    calls = []

    def complete(*args, **kwargs):
        calls.append(True)
        return json.dumps({**VALID, "summary": None}), {}

    monkeypatch.setattr(local_coding_job, "collect_completion", complete)
    with pytest.raises(ValueError, match="Invalid coding summary"):
        local_coding_job.collect_proposal(SimpleNamespace(prompt="Change", guidance=""), SELECTED)
    assert len(calls) == 2
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["attempt"] for e in events] == [1, 2]


def test_transport_or_truncation_failure_is_not_replayed(monkeypatch):
    calls = []

    def complete(*args, **kwargs):
        calls.append(True)
        raise ValueError("Local coding output was truncated")

    monkeypatch.setattr(local_coding_job, "collect_completion", complete)
    with pytest.raises(ValueError, match="truncated"):
        local_coding_job.collect_proposal(SimpleNamespace(prompt="Change", guidance=""), SELECTED)
    assert len(calls) == 1


def test_valid_proposal_does_not_spend_an_extra_completion(monkeypatch, capsys):
    calls = []

    def complete(*args, **kwargs):
        calls.append(True)
        return json.dumps(VALID), {}

    monkeypatch.setattr(local_coding_job, "collect_completion", complete)
    text, _ = local_coding_job.collect_proposal(SimpleNamespace(prompt="Change", guidance=""), SELECTED)
    assert json.loads(text) == VALID and len(calls) == 1
    assert not capsys.readouterr().out


@pytest.mark.parametrize("large", [False, True])
def test_ambiguous_edit_correction_retains_other_occurrences_and_large_file_policy(
    monkeypatch, capsys, large
):
    name = "QA Example Garden"
    prefix = "x" * 32001 if large else ""
    original = prefix + f"<title>{name}</title><h1>{name}</h1><footer>{name}</footer>"
    selected = [{"path": "src/index.html", "content": original}]
    invalid = {
        "summary": "Rename heading",
        "files": [{"path": "src/index.html", "replacements": [{"old": name, "new": name + " — Updated"}]}],
    }
    unique = {"old": f"<h1>{name}</h1>", "new": f"<h1>{name} — Updated</h1>"}
    expected = original.replace(unique["old"], unique["new"])
    good = {
        "summary": "Change only heading",
        "files": [
            {"path": "src/index.html", **({"replacements": [unique]} if large else {"content": expected})}
        ],
    }
    requests = []

    def complete(body, message, *, max_tokens):
        requests.append(message)
        return json.dumps(invalid if len(requests) == 1 else good), {}

    monkeypatch.setattr(local_coding_job, "collect_completion", complete)
    text, _ = local_coding_job.collect_proposal(
        SimpleNamespace(prompt="Change only h1", guidance=""), selected
    )
    from ai_station_runner.coding_files import parse_proposal

    parsed = parse_proposal(text, selected, local_context=True)
    assert parsed["files"][0]["content"] == expected
    assert "<title>" + name + "</title>" in expected and "<footer>" + name + "</footer>" in expected
    assert len(requests) == 2 and "complete content field" in requests[1]
    assert "32000 UTF-8 bytes" in requests[1] and "For larger existing files" in requests[1]
    event = json.loads(capsys.readouterr().out)
    assert "found 3 matches" in event["reason"]
    assert selected[0]["content"] == original
