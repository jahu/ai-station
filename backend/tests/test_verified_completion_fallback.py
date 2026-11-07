import pytest
from app.assistant_decisions import invalid_decision_fallback


@pytest.mark.parametrize(
    "status,types,expected",
    [
        ("succeeded", ["git_diff", "archive"], "finish"),
        ("succeeded", ["json"], "clarify"),
        ("failed", ["git_diff", "archive"], "clarify"),
        ("interrupted", ["git_diff"], "clarify"),
    ],
)
def test_terminal_syntax_recovery_requires_authoritative_completed_outputs(status, types, expected):
    context = {
        "outcomes": [{"kind": "project", "count": 1}, {"kind": "local_changes", "count": 1}],
        "observations": [
            {"index": 1, "tool": "project.create_code", "status": status, "produced_types": types}
        ],
    }
    value = invalid_decision_fallback(context)
    assert value.kind == expected
    assert value.evidence == ([1] if expected == "finish" else [])


def test_undeclared_goals_and_partial_counts_cannot_be_marked_complete():
    observed = [{"index": 1, "tool": "image.generate", "status": "succeeded", "produced_types": ["image"]}]
    assert invalid_decision_fallback({"observations": observed}).kind == "clarify"
    context = {"observations": observed, "outcomes": [{"kind": "image", "count": 2}]}
    assert invalid_decision_fallback(context).kind == "clarify"
    context["observations"] = [*observed, {**observed[0], "index": 2}]
    assert invalid_decision_fallback(context).kind == "finish"
