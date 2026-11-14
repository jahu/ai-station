import pytest
from app.assistant_decisions import invalid_decision_fallback
from app.providers import ProviderError


@pytest.mark.parametrize(
    "status,types,expected",
    [
        ("succeeded", ["git_diff", "archive"], "finish"),
        ("succeeded", ["json"], "error"),
        ("failed", ["git_diff", "archive"], "error"),
        ("interrupted", ["git_diff"], "error"),
    ],
)
def test_terminal_syntax_recovery_requires_authoritative_completed_outputs(status, types, expected):
    context = {
        "outcomes": [{"kind": "project", "count": 1}, {"kind": "local_changes", "count": 1}],
        "observations": [
            {"index": 1, "tool": "project.create_code", "status": status, "produced_types": types}
        ],
    }
    if expected == "error":
        with pytest.raises(ProviderError, match="completed results remain available"):
            invalid_decision_fallback(context)
    else:
        value = invalid_decision_fallback(context)
        assert value.kind == "finish" and value.evidence == [1]


def test_undeclared_goals_and_partial_counts_cannot_be_marked_complete():
    observed = [{"index": 1, "tool": "image.generate", "status": "succeeded", "produced_types": ["image"]}]
    with pytest.raises(ProviderError, match="planner could not prepare a valid tool action"):
        invalid_decision_fallback({"observations": observed})
    context = {"observations": observed, "outcomes": [{"kind": "image", "count": 2}]}
    with pytest.raises(ProviderError, match="No additional tool was executed"):
        invalid_decision_fallback(context)
    context["observations"] = [*observed, {**observed[0], "index": 2}]
    assert invalid_decision_fallback(context).kind == "finish"
